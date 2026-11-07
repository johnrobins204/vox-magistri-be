"""Shared correction helper (SPEC-0016 WP-4, REQ-0027; T-30..T-34)."""

from queue import Full

import pytest

from app.intelligence.prompt_builders import build_chat_messages
from app.services.messages import (
    MAX_INPUT_CHARS,
    CorrectionError,
    correct_message,
    find_reply,
    regenerate_reply,
)
from tests.session_helpers import FakeInference


def _seed(store, *, user_status: str = "completed") -> None:
    store.create_session("s1")
    store.create_message(
        "s1", "u1", {"role": "user", "content": "hi", "meta": None}, status=user_status
    )
    store.create_message(
        "s1",
        "a1",
        {"role": "assistant", "content": "old", "meta": {"reply_to": "u1"}},
        status="completed",
    )


def _snapshot(store):
    return store.list_messages("s1")


def test_find_reply(session_store):
    _seed(session_store)
    session_store.create_message(
        "s1",
        "a2",
        {"role": "assistant", "content": "other", "meta": {"reply_to": "u2"}},
        status="completed",
    )

    reply = find_reply(session_store, "s1", "u1")

    assert reply["id"] == "a1"
    assert reply["content"] == "old"
    reply["content"] = "changed"
    reply["meta"]["reply_to"] = "x"
    stored = session_store.get_message("s1", "a1")
    assert stored["content"] == "old"
    assert stored["meta"]["reply_to"] == "u1"
    assert find_reply(session_store, "s1", "nope") is None


def test_correct_edit_and_canon(session_store):
    _seed(session_store)

    edited = correct_message(store=session_store, session_id="s1", message_id="a1", content="new")

    assert edited["content"] == "new"
    assert len(edited["meta"]["revisions"]) == 1
    assert edited["meta"]["revisions"][0]["reason"] == "edit"
    assert edited["meta"]["revisions"][0]["content"] == "old"

    # Canon-only on the user message works while its regenerate is in flight.
    session_store.update_message_status("s1", "u1", "queued")
    retconned = correct_message(store=session_store, session_id="s1", message_id="u1", canon=False)
    assert retconned["canon"] is False
    assert retconned["content"] == "hi"


def test_correct_rejects(session_store):
    _seed(session_store)
    before = _snapshot(session_store)

    cases = [
        ("u1", {"content": "x"}, 400, "Only assistant replies can be edited"),
        ("a1", {"content": ""}, 400, None),
        ("a1", {"content": "   "}, 400, None),
        ("a1", {"content": "x" * (MAX_INPUT_CHARS + 1)}, 400, None),
        ("a1", {}, 400, "Nothing to update"),
    ]
    for message_id, fields, status_code, detail in cases:
        with pytest.raises(CorrectionError) as info:
            correct_message(store=session_store, session_id="s1", message_id=message_id, **fields)
        assert info.value.status_code == status_code
        if detail is not None:
            assert info.value.detail == detail
        assert _snapshot(session_store) == before

    with pytest.raises(CorrectionError) as info:
        correct_message(store=session_store, session_id="nope", message_id="a1", content="x")
    assert (info.value.status_code, info.value.detail) == (404, "Session not found")

    with pytest.raises(CorrectionError) as info:
        correct_message(store=session_store, session_id="s1", message_id="missing", content="x")
    assert (info.value.status_code, info.value.detail) == (404, "Message not found")
    assert _snapshot(session_store) == before


@pytest.mark.parametrize("user_status", ["queued", "running"])
def test_correct_content_blocked_while_regenerating(session_store, user_status):
    _seed(session_store, user_status=user_status)
    before = _snapshot(session_store)

    with pytest.raises(CorrectionError) as info:
        correct_message(store=session_store, session_id="s1", message_id="a1", content="new")

    assert (info.value.status_code, info.value.detail) == (409, "Reply is being regenerated")
    assert _snapshot(session_store) == before


def test_regenerate_enqueues_user_message(session_store):
    _seed(session_store)
    inference = FakeInference()
    before = _snapshot(session_store)

    user, queued = regenerate_reply(
        store=session_store, inference=inference, session_id="s1", reply_id="a1"
    )

    assert user["id"] == "u1"
    assert queued is True
    assert len(inference.calls) == 1
    assert inference.calls[0] == {
        "session_id": "s1",
        "message_id": "u1",
        "prompt": "hi",
        "store": session_store,
    }
    assert _snapshot(session_store) == before


def test_regenerate_rejects(session_store):
    _seed(session_store)
    session_store.create_message(
        "s1", "a3", {"role": "assistant", "content": "orphan", "meta": None}, status="completed"
    )
    session_store.create_message(
        "s1",
        "a4",
        {"role": "assistant", "content": "dangling", "meta": {"reply_to": "gone"}},
        status="completed",
    )
    before = _snapshot(session_store)
    inference = FakeInference()

    def attempt(session_id, reply_id):
        return regenerate_reply(
            store=session_store, inference=inference, session_id=session_id, reply_id=reply_id
        )

    rejects = [
        ("nope", "a1", 404, "Session not found"),
        ("s1", "missing", 404, "Message not found"),
        ("s1", "u1", 400, "Only assistant replies can be regenerated"),
        ("s1", "a3", 400, "Reply has no source message"),
        ("s1", "a4", 400, "Reply has no source message"),
    ]
    for session_id, reply_id, status_code, detail in rejects:
        with pytest.raises(CorrectionError) as info:
            attempt(session_id, reply_id)
        assert (info.value.status_code, info.value.detail) == (status_code, detail)
    assert inference.calls == []
    assert _snapshot(session_store) == before

    for status in ("queued", "running"):
        session_store.update_message_status("s1", "u1", status)
        with pytest.raises(CorrectionError) as info:
            attempt("s1", "a1")
        assert (info.value.status_code, info.value.detail) == (409, "Reply is being regenerated")
    assert inference.calls == []

    session_store.update_message_status("s1", "u1", "completed")
    user, queued = regenerate_reply(
        store=session_store, inference=FakeInference(accept=False), session_id="s1", reply_id="a1"
    )
    assert user["id"] == "u1"
    assert queued is False


def _queue_full(svc, monkeypatch) -> None:
    """The real enqueue sees a full queue: it writes queued, then error, and returns False."""

    def put_nowait(job):
        raise Full

    monkeypatch.setattr(svc._queue, "put_nowait", put_nowait)


@pytest.mark.parametrize(
    "prior_status, prior_meta",
    [("completed", None), ("cancelled", None), ("error", {"error": "boom"})],
)
def test_regenerate_queue_full_restores_user_message(
    session_store, stub_svc, monkeypatch, prior_status, prior_meta
):
    session_store.create_session("s1")
    session_store.create_message(
        "s1", "u1", {"role": "user", "content": "hi", "meta": prior_meta}, status=prior_status
    )
    session_store.create_message(
        "s1",
        "a1",
        {"role": "assistant", "content": "old", "meta": {"reply_to": "u1"}},
        status="completed",
    )
    _queue_full(stub_svc, monkeypatch)

    def next_prompt():
        prompt = build_chat_messages(
            "sys",
            session_store.list_messages("s1"),
            "next",
            "again",
            max_turns=10,
            max_field_len=1000,
        )
        return [(m["role"], m["content"]) for m in prompt]

    before = next_prompt()
    _, queued = regenerate_reply(
        store=session_store, inference=stub_svc, session_id="s1", reply_id="a1"
    )

    assert queued is False
    stored = session_store.get_message("s1", "u1")
    assert stored["status"] == prior_status
    assert (stored["meta"] or {}).get("error") == (prior_meta or {}).get("error")
    assert "inference queue full" not in repr(stored["meta"])
    # A rejected request changes nothing the next prompt is built from; the reply stays in it.
    assert next_prompt() == before
    assert ("assistant", "old") in before
    if prior_status == "completed":
        assert ("user", "hi") in before
