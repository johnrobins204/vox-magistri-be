"""Worker regenerates a reply in place with revision capture (SPEC-0016 WP-6, REQ-0027)."""

import asyncio
from types import SimpleNamespace

import pytest

from app.services.messages import correct_message, find_reply, regenerate_reply, submit_user_message
from app.services.tool_service import ToolService
from tests.session_helpers import make_stub_service, wait_idle


class ScriptedRng:
    """Scripted random source: randint(1, sides) pops the next scripted value."""

    def __init__(self, values):
        self._values = list(values)

    def randint(self, a, b):
        assert a == 1
        return self._values.pop(0)


@pytest.fixture
def env(session_store):
    """Worker over a real :memory: store; the chat stub returns whatever `reply_text["v"]` holds."""
    svc = make_stub_service()
    reply_text = {"v": "v1"}
    chat_calls: list[list[dict]] = []

    def _chat(messages, **kw):
        chat_calls.append(messages)
        return reply_text["v"]

    svc.client.chat = _chat
    session_store.create_session("s1")
    yield SimpleNamespace(
        svc=svc, store=session_store, reply_text=reply_text, chat_calls=chat_calls
    )
    asyncio.run(svc.shutdown())


def _turn(svc, store, content: str) -> dict:
    message, created, queued = submit_user_message(
        store=store, inference=svc, session_id="s1", payload={"content": content}
    )
    assert created and queued
    wait_idle(svc)
    return message


def _reply(store, user_id: str) -> dict:
    reply = find_reply(store, "s1", user_id)
    assert reply is not None
    return reply


def _regenerate(svc, store, reply_id: str) -> None:
    _, queued = regenerate_reply(store=store, inference=svc, session_id="s1", reply_id=reply_id)
    assert queued
    wait_idle(svc)


def _revision_pairs(message: dict) -> list[tuple[str, str]]:
    return [(r["content"], r["reason"]) for r in message["meta"].get("revisions", [])]


def test_regenerate_revises_in_place(env):
    user = _turn(env.svc, env.store, "hi")
    reply = _reply(env.store, user["id"])
    assert reply["content"] == "v1"

    env.reply_text["v"] = "v2"
    _regenerate(env.svc, env.store, reply["id"])

    assert len(env.store.list_messages("s1")) == 2
    revised = _reply(env.store, user["id"])
    assert revised["id"] == reply["id"]
    assert revised["content"] == "v2"
    assert _revision_pairs(revised) == [("v1", "regenerate")]
    assert revised["meta"]["reply_to"] == user["id"]
    assert revised["status"] == "completed"
    assert env.store.get_message("s1", user["id"])["status"] == "completed"


def test_regenerate_after_operator_edit_keeps_both_revisions(env):
    user = _turn(env.svc, env.store, "hi")
    reply = _reply(env.store, user["id"])

    correct_message(store=env.store, session_id="s1", message_id=reply["id"], content="E")
    env.reply_text["v"] = "v2"
    _regenerate(env.svc, env.store, reply["id"])

    revised = _reply(env.store, user["id"])
    assert revised["content"] == "v2"
    assert _revision_pairs(revised) == [("v1", "edit"), ("E", "regenerate")]


def test_regenerate_prompt_is_prior_turns_only(env):
    env.reply_text["v"] = "r1"
    user1 = _turn(env.svc, env.store, "u1")
    first_reply = _reply(env.store, user1["id"])
    correct_message(store=env.store, session_id="s1", message_id=first_reply["id"], canon=False)

    env.reply_text["v"] = "r2"
    user2 = _turn(env.svc, env.store, "u2")
    reply2 = _reply(env.store, user2["id"])

    _regenerate(env.svc, env.store, reply2["id"])

    prompt = env.chat_calls[-1]
    assert prompt[-1] == {"role": "user", "content": "u2"}
    assert [m["content"] for m in prompt[1:]] == ["u1", "u2"]
    assert all(m["content"] not in ("r1", "r2") for m in prompt)


def test_failed_regenerate_keeps_text(env):
    user = _turn(env.svc, env.store, "hi")
    reply = _reply(env.store, user["id"])

    def _boom(messages, **kw):
        raise RuntimeError("model down")

    env.svc.client.chat = _boom
    _regenerate(env.svc, env.store, reply["id"])

    failed_user = env.store.get_message("s1", user["id"])
    assert failed_user["status"] == "error"
    assert failed_user["meta"]["error"] == "model down"
    unchanged = _reply(env.store, user["id"])
    assert unchanged["content"] == "v1"
    assert "revisions" not in unchanged["meta"]
    assert len(env.store.list_messages("s1")) == 2

    env.svc.client.chat = lambda messages, **kw: "v2"
    _regenerate(env.svc, env.store, reply["id"])

    recovered = _reply(env.store, user["id"])
    assert recovered["content"] == "v2"
    assert _revision_pairs(recovered) == [("v1", "regenerate")]
    assert env.store.get_message("s1", user["id"])["status"] == "completed"


def test_tool_reply_regenerated(session_store):
    ts = ToolService(discover_on_init=True, default_context={"rng": ScriptedRng([3, 4])})
    svc = make_stub_service(tool_service=ts)
    session_store.create_session("s1")
    try:
        user = _turn(svc, session_store, "/roll 1d4")
        reply = _reply(session_store, user["id"])
        assert reply["content"].endswith("= 3")
        assert reply["meta"]["total"] == 3

        _regenerate(svc, session_store, reply["id"])

        assert len(session_store.list_messages("s1")) == 2
        revised = _reply(session_store, user["id"])
        assert revised["id"] == reply["id"]
        assert revised["content"].endswith("= 4")
        assert revised["meta"]["total"] == 4
        assert revised["meta"]["tool"] == "roll"
        assert _revision_pairs(revised) == [(reply["content"], "regenerate")]
    finally:
        asyncio.run(svc.shutdown())


def test_non_canon_reply_stays_non_canon_after_regenerate(env):
    user = _turn(env.svc, env.store, "hi")
    reply = _reply(env.store, user["id"])
    correct_message(store=env.store, session_id="s1", message_id=reply["id"], canon=False)

    env.reply_text["v"] = "v2"
    _regenerate(env.svc, env.store, reply["id"])

    revised = _reply(env.store, user["id"])
    assert revised["content"] == "v2"
    assert revised["canon"] is False


def test_append_reply_returns_existing_id_for_answered_user_message(env):
    user = _turn(env.svc, env.store, "hi")
    reply = _reply(env.store, user["id"])

    returned = env.svc._append_reply(env.store, "s1", user["id"], "v3")

    assert returned == reply["id"]
    assert len(env.store.list_messages("s1")) == 2
    assert _reply(env.store, user["id"])["content"] == "v3"
