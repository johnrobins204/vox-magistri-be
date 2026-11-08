"""SPEC-0021 WP-1: server-owned meta.kind classifies command rows and replies (PAT-ARCH-013)."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.intelligence.tool_handler import NARRATIVE_TOOLS, message_kind
from app.services.messages import regenerate_reply, submit_user_message
from app.services.repos import SqliteSessionStore
from app.services.tool_service import ToolService
from app.type_defs import MessageKind
from tests.session_helpers import AUTH, FakeInference, make_stub_service, wait_idle
from tests.test_slash_dispatch import ScriptedRng, _post

NARRATIVE = MessageKind.NARRATIVE
ADMIN = MessageKind.ADMIN


@pytest.fixture
def slash_env(monkeypatch):
    """Copy of tests/test_slash_dispatch.py::slash_env (REST + worker, recording chat stub)."""
    ts = ToolService(discover_on_init=True, default_context={"rng": ScriptedRng([3, 4])})
    svc = make_stub_service(tool_service=ts)
    ts.default_context["inference"] = svc
    chat_calls: list[list[dict]] = []

    def _chat(messages, **kw):
        chat_calls.append(messages)
        return "stub reply"

    monkeypatch.setattr(svc.client, "chat", _chat)
    store = SqliteSessionStore(":memory:")
    store.create_session("s1")
    app = create_app(services={"inference": svc, "session": store, "tool": ts})
    with TestClient(app) as client:
        yield SimpleNamespace(ts=ts, svc=svc, store=store, client=client, chat_calls=chat_calls)
    asyncio.run(svc.shutdown())
    store.close()


# T-1
def test_message_kind_classifies_none_and_tool_names():
    assert message_kind(None) == NARRATIVE
    assert message_kind("narrate") == NARRATIVE
    for name in ("rules", "monster", "help", "zzz"):
        assert message_kind(name) == ADMIN
    for name in NARRATIVE_TOOLS:
        assert message_kind(name) == NARRATIVE


# T-2
def test_narrative_tools_set_and_attack_roll_are_narrative():
    assert NARRATIVE_TOOLS == frozenset({"narrate", "attack", "roll"})
    assert message_kind("attack") == NARRATIVE
    assert message_kind("roll") == NARRATIVE


# T-3
def test_submit_user_message_sets_kind_and_strips_client_value(session_store):
    session_store.create_session("s1")
    inference = FakeInference()
    cases = [
        ({"content": "/rules grapple"}, ADMIN),
        ({"content": "hello"}, NARRATIVE),
        ({"content": "/narrate x"}, NARRATIVE),
        ({"content": "/nope"}, ADMIN),
        ({"content": "hello", "meta": {"kind": "admin"}}, NARRATIVE),
    ]
    for payload, _ in cases:
        submit_user_message(
            store=session_store, inference=inference, session_id="s1", payload=payload
        )
    stored = session_store.list_messages("s1")
    assert [m["meta"]["kind"] for m in stored] == [expected for _, expected in cases]


# T-4
def test_slash_and_chat_rows_and_replies_carry_kind(slash_env):
    for content in ("/rules x", "/narrate a storm", "hello", "/nope hi"):
        _post(slash_env, content)
    wait_idle(slash_env.svc)

    msgs = slash_env.store.list_messages("s1")
    by_content = {m["content"]: m for m in msgs if m["role"] == "user"}
    assert by_content["/rules x"]["meta"]["kind"] == ADMIN
    assert by_content["/narrate a storm"]["meta"]["kind"] == NARRATIVE
    assert by_content["hello"]["meta"]["kind"] == NARRATIVE
    nope = by_content["/nope hi"]
    assert nope["status"] == "error"
    assert nope["meta"]["kind"] == ADMIN
    replies = {m["meta"]["reply_to"]: m for m in msgs if m["role"] == "assistant"}
    assert replies[by_content["/rules x"]["id"]]["meta"]["kind"] == ADMIN
    assert replies[by_content["/narrate a storm"]["id"]]["meta"]["kind"] == NARRATIVE
    assert replies[by_content["hello"]["id"]]["meta"]["kind"] == NARRATIVE
    assert nope["id"] not in replies


# T-5
def test_regenerate_keeps_admin_kind_and_tool_on_rules_reply(slash_env):
    _post(slash_env, "/rules x")
    wait_idle(slash_env.svc)
    reply = next(m for m in slash_env.store.list_messages("s1") if m["role"] == "assistant")

    regenerate_reply(
        store=slash_env.store, inference=slash_env.svc, session_id="s1", reply_id=reply["id"]
    )
    wait_idle(slash_env.svc)

    revised = slash_env.store.get_message("s1", reply["id"])
    assert revised["meta"]["kind"] == ADMIN
    assert revised["meta"]["tool"] == "rules"


# T-10
def test_submit_user_message_stores_narrative_only_only_when_true(session_store):
    session_store.create_session("s1")
    inference = FakeInference()
    for payload in (
        {"content": "hi", "narrative_only": True},
        {"content": "hi", "narrative_only": False},
        {"content": "hi"},
    ):
        submit_user_message(
            store=session_store, inference=inference, session_id="s1", payload=payload
        )
    stored = session_store.list_messages("s1")
    assert stored[0]["meta"]["narrative_only"] is True
    assert "narrative_only" not in stored[1]["meta"]
    assert "narrative_only" not in stored[2]["meta"]


# T-11
def test_client_meta_cannot_set_narrative_only(session_store):
    session_store.create_session("s1")
    submit_user_message(
        store=session_store,
        inference=FakeInference(),
        session_id="s1",
        payload={"content": "hi", "meta": {"narrative_only": True}},
    )
    assert "narrative_only" not in session_store.list_messages("s1")[0]["meta"]


# T-12
@pytest.mark.parametrize(
    "extra, stored_flag",
    [
        ({"narrative_only": True}, True),
        ({"narrative_only": False}, None),
        ({}, None),
    ],
)
def test_ws_narrative_only_flag_is_stored_on_user_row(
    stub_client, stub_svc, session_store, extra, stored_flag
):
    session_store.create_session("s1")
    with stub_client.websocket_connect("/api/v1/ws/sessions/s1") as ws:
        ws.receive_json()  # snapshot
        ws.send_json({"action": "user_message", "text": "hi", **extra})
        ws.receive_json()  # user entry
        ws.receive_json()  # reply entry
        ws.receive_json()  # done
    user = next(m for m in session_store.list_messages("s1") if m["role"] == "user")
    # Stored values are only True; None means the key is absent.
    assert user["meta"].get("narrative_only") is stored_flag


def test_ws_non_bool_narrative_only_is_rejected_before_storing(
    stub_client, stub_svc, session_store
):
    session_store.create_session("s1")
    with stub_client.websocket_connect("/api/v1/ws/sessions/s1") as ws:
        ws.receive_json()  # snapshot
        ws.send_json({"action": "user_message", "text": "hi", "narrative_only": "yes"})
        evt = ws.receive_json()
    assert evt["type"] == "error"
    assert evt["message"] == "narrative_only must be a boolean"
    assert session_store.list_messages("s1") == []


# T-13
def test_rest_narrative_only_flag_is_stored_and_documented(stub_client, stub_svc, session_store):
    session_store.create_session("s1")
    resp = stub_client.post(
        "/api/v1/sessions/s1/messages",
        json={"content": "hi", "narrative_only": True},
        headers=AUTH,
    )
    assert resp.status_code == 202
    wait_idle(stub_svc)
    user = next(m for m in session_store.list_messages("s1") if m["role"] == "user")
    assert user["meta"]["narrative_only"] is True

    schema = stub_client.get("/openapi.json").json()["components"]["schemas"]["MessageCreateReq"]
    prop = schema["properties"]["narrative_only"]
    assert prop["type"] == "boolean"
    assert prop["default"] is False
