"""Narrative-only context filter in build_chat_messages (SPEC-0021 WP-3; T-14..T-19, ADR-0015).

Builder tests use literal dicts. Worker tests use a recording `client.chat` and a real store.
"""

import asyncio
import copy

import pytest

from app.intelligence.prompt_builders import build_chat_messages
from app.services.messages import find_reply, regenerate_reply, submit_user_message
from tests.session_helpers import make_stub_service, wait_idle

SYSTEM = "SYS"
KW = {"max_field_len": 1000}


def _row(mid, role, content, *, kind=None, canon=None, status="completed"):
    row = {"id": mid, "role": role, "content": content, "status": status, "meta": {}}
    if kind is not None:
        row["meta"]["kind"] = kind
    if canon is not None:
        row["canon"] = canon
    return row


def _msg(role, content):
    return {"role": role, "content": content}


# T-14
def test_flag_off_keeps_admin_rows(monkeypatch):
    history = [
        _row("n1", "user", "story", kind="narrative"),
        _row("a1", "user", "/roll 1d20", kind="admin"),
        _row("a1r", "assistant", "rolled 14", kind="admin"),
        _row("c", "user", "now", status="running"),
    ]
    expected = [
        _msg("system", SYSTEM),
        _msg("user", "story"),
        _msg("user", "/roll 1d20"),
        _msg("assistant", "rolled 14"),
        _msg("user", "now"),
    ]

    omitted = build_chat_messages(SYSTEM, history, "c", "now", max_turns=10, **KW)
    flag_false = build_chat_messages(
        SYSTEM, history, "c", "now", max_turns=10, narrative_only=False, **KW
    )

    assert omitted == expected
    assert flag_false == expected


# T-15
def test_narrative_only_drops_admin_pairs():
    history = [
        _row("n1", "user", "story?", kind="narrative"),
        _row("n1r", "assistant", "story!", kind="narrative"),
        _row("a1", "user", "/rules grapple", kind="admin"),
        _row("a1r", "assistant", "rules answer", kind="admin"),
        _row("c", "user", "now", status="running"),
    ]

    messages = build_chat_messages(
        SYSTEM, history, "c", "now", max_turns=10, narrative_only=True, **KW
    )

    assert messages == [
        _msg("system", SYSTEM),
        _msg("user", "story?"),
        _msg("assistant", "story!"),
        _msg("user", "now"),
    ]


# T-16
def test_narrative_only_keeps_missing_kind_and_skips_non_canon():
    history = [
        _row("u0", "user", "old question"),
        _row("r0", "assistant", "old answer"),
        _row("n1", "assistant", "hidden", kind="narrative", canon=False),
        _row("c", "user", "now", status="running"),
    ]

    messages = build_chat_messages(
        SYSTEM, history, "c", "now", max_turns=10, narrative_only=True, **KW
    )

    assert messages == [
        _msg("system", SYSTEM),
        _msg("user", "old question"),
        _msg("assistant", "old answer"),
        _msg("user", "now"),
    ]


# T-17
def test_admin_rows_do_not_count_toward_max_turns():
    history = [
        _row("n1", "user", "first", kind="narrative"),
        _row("n2", "assistant", "second", kind="narrative"),
        _row("a1", "user", "/roll", kind="admin"),
        _row("a1r", "assistant", "r1", kind="admin"),
        _row("a2", "user", "/roll", kind="admin"),
        _row("a2r", "assistant", "r2", kind="admin"),
        _row("c", "user", "now", status="running"),
    ]

    messages = build_chat_messages(
        SYSTEM, history, "c", "now", max_turns=2, narrative_only=True, **KW
    )

    assert messages == [
        _msg("system", SYSTEM),
        _msg("user", "first"),
        _msg("assistant", "second"),
        _msg("user", "now"),
    ]


@pytest.fixture
def svc():
    service = make_stub_service()
    yield service
    asyncio.run(service.shutdown())


def _recording_chat(svc, monkeypatch) -> list[list[dict]]:
    calls: list[list[dict]] = []

    def _chat(messages, **kw):
        calls.append(copy.deepcopy(messages))
        return f"reply-{len(calls)}"

    monkeypatch.setattr(svc.client, "chat", _chat)
    return calls


def _store_admin_and_narrative_rows(store) -> None:
    store.create_session("s1")
    store.create_message(
        "s1",
        "n0",
        {"role": "user", "content": "tell me", "meta": {"kind": "narrative"}},
        status="completed",
    )
    store.create_message(
        "s1",
        "n0r",
        {"role": "assistant", "content": "told", "meta": {"kind": "narrative"}},
        status="completed",
    )
    store.create_message(
        "s1",
        "a1",
        {"role": "user", "content": "/roll 1d20", "meta": {"kind": "admin"}},
        status="completed",
    )
    store.create_message(
        "s1",
        "a1r",
        {"role": "assistant", "content": "rolled 14", "meta": {"kind": "admin"}},
        status="completed",
    )


# T-18
def test_worker_flag_excludes_admin_rows_only_for_flagged_turn(svc, session_store, monkeypatch):
    _store_admin_and_narrative_rows(session_store)
    calls = _recording_chat(svc, monkeypatch)

    submit_user_message(
        store=session_store,
        inference=svc,
        session_id="s1",
        payload={"content": "where now?", "narrative_only": True},
    )
    wait_idle(svc)
    submit_user_message(
        store=session_store,
        inference=svc,
        session_id="s1",
        payload={"content": "again"},
    )
    wait_idle(svc)

    system = calls[0][0]
    assert calls[0] == [
        system,
        _msg("user", "tell me"),
        _msg("assistant", "told"),
        _msg("user", "where now?"),
    ]
    assert calls[1] == [
        system,
        _msg("user", "tell me"),
        _msg("assistant", "told"),
        _msg("user", "/roll 1d20"),
        _msg("assistant", "rolled 14"),
        _msg("user", "where now?"),
        _msg("assistant", "reply-1"),
        _msg("user", "again"),
    ]


# T-19
def test_regenerate_reuses_flag_from_stored_user_row(svc, session_store, monkeypatch):
    _store_admin_and_narrative_rows(session_store)
    calls = _recording_chat(svc, monkeypatch)
    submit_user_message(
        store=session_store,
        inference=svc,
        session_id="s1",
        payload={"content": "where now?", "narrative_only": True},
    )
    wait_idle(svc)
    user = next(m for m in session_store.list_messages("s1") if m["content"] == "where now?")
    reply = find_reply(session_store, "s1", user["id"])
    assert reply is not None

    _, queued = regenerate_reply(
        store=session_store, inference=svc, session_id="s1", reply_id=reply["id"]
    )
    assert queued
    wait_idle(svc)

    assert len(calls) == 2
    assert calls[1] == calls[0]
