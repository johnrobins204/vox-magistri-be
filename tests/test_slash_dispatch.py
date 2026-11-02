"""Slash dispatch and the shared Ollama lock (SPEC-0007, WP-6 and WP-7).

T-43..T-45 (WP-6): `OllamaInferenceService.generate` and the worker's `client.chat` run under one
`_ollama_lock`.
T-32..T-42 (WP-7): the worker runs `/name args` through `ToolService` (no chat builder, no
`client.chat`, lock not held) and stores the result as an assistant reply or a user-message error.
No network and no Ollama: `client.chat` is replaced with a recording stub.
Every thread join and event wait has a timeout so a regression fails instead of hanging.
"""

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.factory import create_app
from app.intelligence.prompt_builders import (
    NarratorVoiceParams,
    build_narrator_prompt,
    build_rules_prompt,
)
from app.intelligence.tools.rules import TRAINING_DISCLAIMER
from app.reference.rules import Rule
from app.services.build_services import build_services
from app.services.repos import SqliteSessionStore, make_default_repos
from app.services.tool_service import ToolService
from tests.session_helpers import AUTH, make_stub_service, wait_idle

JOIN_TIMEOUT = 5.0


class ScriptedRng:
    """Scripted random source: randint(1, sides) pops the next scripted value."""

    def __init__(self, values):
        self._values = list(values)
        self.calls = []

    def randint(self, a, b):
        assert a == 1
        self.calls.append((a, b))
        return self._values.pop(0)


@pytest.fixture
def slash_env(monkeypatch):
    """REST + worker with the real discovered registry; `client.chat` is a recording stub."""
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


def _post(env, content: str):
    resp = env.client.post("/api/v1/sessions/s1/messages", json={"content": content}, headers=AUTH)
    assert resp.status_code == 202
    return resp


def _by_id(messages, message_id):
    return next(m for m in messages if m["id"] == message_id)


def _narrate_prompt(text: str) -> str:
    p = get_settings().prompts
    params = NarratorVoiceParams(
        tone=p.dm_voice.tone,
        dm_persona=p.dm_voice.persona,
        verbosity=p.verbosity_default,
        sensory_focus=p.dm_voice.sensory_focus,
        consequence_level=p.dm_voice.consequence_level,
    )
    return build_narrator_prompt(text, params, None)


WS_URL = "/api/v1/ws/sessions/s1"


@pytest.fixture
def svc():
    service = make_stub_service()
    yield service
    asyncio.run(service.shutdown())


# T-43
def test_generate_holds_the_ollama_lock(svc, monkeypatch):
    seen = {}

    def _chat(messages, **kw):
        seen["locked"] = svc._ollama_lock.locked()
        seen["messages"] = messages
        return "generated"

    monkeypatch.setattr(svc.client, "chat", _chat)

    assert svc.generate("p") == "generated"
    assert seen["locked"] is True
    assert seen["messages"] == [{"role": "user", "content": "p"}]
    assert svc._ollama_lock.locked() is False


# T-44
def test_worker_chat_holds_the_ollama_lock(svc, session_store, monkeypatch):
    seen = {}

    def _chat(messages, **kw):
        seen["locked"] = svc._ollama_lock.locked()
        return "worker reply"

    monkeypatch.setattr(svc.client, "chat", _chat)
    session_store.create_session("s1")
    session_store.create_message("s1", "u1", {"role": "user", "content": "hello"})

    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=session_store)
    wait_idle(svc)

    assert seen == {"locked": True}
    replies = [m for m in session_store.list_messages("s1") if m["role"] == "assistant"]
    assert len(replies) == 1
    assert replies[0]["content"] == "worker reply"
    assert replies[0]["meta"] == {"reply_to": "u1"}
    assert svc._ollama_lock.locked() is False


# T-45
def test_generate_calls_do_not_overlap(svc, monkeypatch):
    counter_lock = threading.Lock()
    release = threading.Event()
    first_in = threading.Event()
    active = 0
    max_active = 0

    def _chat(messages, **kw):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        first_in.set()
        release.wait(JOIN_TIMEOUT)
        with counter_lock:
            active -= 1
        return "gen"

    monkeypatch.setattr(svc.client, "chat", _chat)
    results: list[str] = []
    errors: list[BaseException] = []

    def _call():
        try:
            results.append(svc.generate("p"))
        except BaseException as exc:  # reported by the assertions below
            errors.append(exc)

    threads = [threading.Thread(target=_call, daemon=True) for _ in range(2)]
    for t in threads:
        t.start()
    assert first_in.wait(JOIN_TIMEOUT), "first generate never reached the chat stub"
    # Give a second, unlocked call time to enter the chat stub if nothing serializes it.
    time.sleep(0.2)
    release.set()
    for t in threads:
        t.join(JOIN_TIMEOUT)

    assert not any(t.is_alive() for t in threads), "generate calls did not return"
    assert errors == []
    assert results == ["gen", "gen"]
    assert max_active == 1


# T-32
def test_rest_clear_is_unknown_tool_error_and_never_reaches_llm(slash_env):
    resp = _post(slash_env, "/clear")
    assert resp.status_code == 202
    wait_idle(slash_env.svc)

    msgs = slash_env.store.list_messages("s1")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["status"] == "error"
    assert msgs[0]["meta"]["error"] == "Unknown tool: clear"
    assert slash_env.chat_calls == []


# T-33
def test_rest_slash_roll_creates_tool_reply(slash_env):
    _post(slash_env, "/roll 2d6")
    wait_idle(slash_env.svc)

    msgs = slash_env.store.list_messages("s1")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    user, reply = msgs
    assert user["status"] == "completed"
    assert reply["status"] == "completed"
    assert reply["content"] == "2d6: [3, 4] = 7"
    assert reply["meta"]["tool"] == "roll"
    assert reply["meta"]["reply_to"] == user["id"]
    assert reply["meta"]["total"] == 7
    assert slash_env.chat_calls == []


# T-35
def test_rest_unknown_slash_command_marks_user_message_error(slash_env):
    _post(slash_env, "/nope hi")
    wait_idle(slash_env.svc)

    msgs = slash_env.store.list_messages("s1")
    assert len(msgs) == 1
    assert msgs[0]["status"] == "error"
    assert msgs[0]["meta"]["error"] == "Unknown tool: nope"
    assert slash_env.chat_calls == []


# T-37
def test_slash_tool_error_marks_user_message_error(slash_env):
    _post(slash_env, "/roll 1d1")
    wait_idle(slash_env.svc)

    msgs = slash_env.store.list_messages("s1")
    assert len(msgs) == 1
    assert msgs[0]["status"] == "error"
    assert msgs[0]["meta"]["error"] == "Dice sides must be 2-1000"
    assert slash_env.chat_calls == []


# T-38
def test_slash_narrate_runs_in_worker_without_deadlock(slash_env):
    _post(slash_env, "/narrate a storm")
    # Fails after the wait_idle timeout if the worker held _ollama_lock while narrate's generate ran.
    wait_idle(slash_env.svc)

    msgs = slash_env.store.list_messages("s1")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    user, reply = msgs
    assert user["status"] == "completed"
    assert reply["content"] == "stub reply"
    assert reply["meta"] == {"tool": "narrate", "reply_to": user["id"]}
    assert slash_env.chat_calls == [[{"role": "user", "content": _narrate_prompt("a storm")}]]


# T-39
def test_non_slash_messages_use_chat_path(slash_env):
    contents = ["hello", "/ roll 2d6", "path/to/x", "say /roll"]
    ids = []
    for content in contents:
        msg_id = f"u{len(ids)}"
        slash_env.store.create_message("s1", msg_id, {"role": "user", "content": content})
        slash_env.svc.enqueue(
            session_id="s1", message_id=msg_id, prompt=content, store=slash_env.store
        )
        ids.append(msg_id)
    wait_idle(slash_env.svc)

    assert len(slash_env.chat_calls) == len(contents)
    assert [c[-1]["content"] for c in slash_env.chat_calls] == contents
    assert slash_env.ts.default_context["rng"].calls == []
    msgs = slash_env.store.list_messages("s1")
    for msg_id in ids:
        replies = [
            m for m in msgs if m["role"] == "assistant" and m["meta"].get("reply_to") == msg_id
        ]
        assert len(replies) == 1
        assert replies[0]["content"] == "stub reply"
        assert replies[0]["meta"] == {"reply_to": msg_id}


# T-40
@pytest.fixture
def plain_env(monkeypatch):
    svc = make_stub_service()
    chat_calls: list[list[dict]] = []

    def _chat(messages, **kw):
        chat_calls.append(messages)
        return "stub reply"

    monkeypatch.setattr(svc.client, "chat", _chat)
    store = SqliteSessionStore(":memory:")
    store.create_session("s1")
    yield SimpleNamespace(svc=svc, store=store, chat_calls=chat_calls)
    asyncio.run(svc.shutdown())
    store.close()


def test_without_tool_service_slash_goes_to_chat(plain_env):
    plain_env.store.create_message("s1", "u1", {"role": "user", "content": "/roll 2d6"})
    plain_env.svc.enqueue(
        session_id="s1", message_id="u1", prompt="/roll 2d6", store=plain_env.store
    )
    wait_idle(plain_env.svc)

    assert len(plain_env.chat_calls) == 1
    replies = [m for m in plain_env.store.list_messages("s1") if m["role"] == "assistant"]
    assert len(replies) == 1
    assert replies[0]["content"] == "stub reply"
    assert replies[0]["meta"] == {"reply_to": "u1"}


# T-41
def test_worker_passes_server_context_to_tool(slash_env):
    seen: dict = {}

    def echo(args, ctx):
        seen.update(ctx)
        return f"echoed {args}"

    slash_env.ts.register_tool("echo", echo)
    slash_env.store.create_message("s1", "u1", {"role": "user", "content": "/echo x"})
    slash_env.svc.enqueue(session_id="s1", message_id="u1", prompt="/echo x", store=slash_env.store)
    wait_idle(slash_env.svc)

    assert seen["store"] is slash_env.store
    assert seen["session_id"] == "s1"
    assert seen["message_id"] == "u1"
    assert seen["rng"] is slash_env.ts.default_context["rng"]
    assert seen["inference"] is slash_env.svc
    replies = [m for m in slash_env.store.list_messages("s1") if m["role"] == "assistant"]
    assert len(replies) == 1
    assert replies[0]["content"] == "echoed x"
    assert slash_env.chat_calls == []


# T-42
def test_tool_bug_marks_error_and_worker_survives(slash_env):
    def boom(args, ctx):
        raise RuntimeError("boom")

    slash_env.ts.register_tool("bad", boom)
    slash_env.store.create_message("s1", "u1", {"role": "user", "content": "/bad x"})
    slash_env.svc.enqueue(session_id="s1", message_id="u1", prompt="/bad x", store=slash_env.store)
    slash_env.store.create_message("s1", "u2", {"role": "user", "content": "hello"})
    slash_env.svc.enqueue(session_id="s1", message_id="u2", prompt="hello", store=slash_env.store)
    wait_idle(slash_env.svc)

    msgs = slash_env.store.list_messages("s1")
    first = _by_id(msgs, "u1")
    assert first["status"] == "error"
    assert first["meta"]["error"] == "boom"
    assert [m for m in msgs if m["meta"].get("reply_to") == "u1"] == []
    second = _by_id(msgs, "u2")
    assert second["status"] == "completed"
    reply = [m for m in msgs if m["meta"].get("reply_to") == "u2"]
    assert len(reply) == 1
    assert reply[0]["content"] == "stub reply"


# WP-8: the WebSocket path (ws.py is not edited; it reads the store the worker writes).
def _ws_send_and_collect(client, text: str, count: int) -> list[dict]:
    with client.websocket_connect(WS_URL) as ws:
        assert ws.receive_json()["type"] == "snapshot"
        ws.send_json({"action": "user_message", "text": text})
        return [ws.receive_json() for _ in range(count)]


# T-34
def test_ws_slash_roll_creates_tool_reply(slash_env):
    user_evt, reply_evt, done = _ws_send_and_collect(slash_env.client, "/roll 2d6", 3)

    assert user_evt["type"] == "entry"
    user = user_evt["entry"]
    assert user["role"] == "user"
    assert reply_evt["type"] == "entry"
    reply = reply_evt["entry"]
    assert reply["role"] == "assistant"
    assert reply["content"] == "2d6: [3, 4] = 7"
    assert reply["meta"]["tool"] == "roll"
    assert reply["meta"]["reply_to"] == user["id"]
    assert reply["meta"]["total"] == 7
    assert done == {"type": "done", "message_id": user["id"], "reply_id": reply["id"]}
    assert slash_env.chat_calls == []


# WP-8 (requested): /narrate over WS, same contract as T-38.
def test_ws_slash_narrate_creates_tool_reply(slash_env):
    user_evt, reply_evt, done = _ws_send_and_collect(slash_env.client, "/narrate a storm", 3)

    user = user_evt["entry"]
    reply = reply_evt["entry"]
    assert reply["role"] == "assistant"
    assert reply["content"] == "stub reply"
    assert reply["meta"] == {"tool": "narrate", "reply_to": user["id"]}
    assert done == {"type": "done", "message_id": user["id"], "reply_id": reply["id"]}
    assert slash_env.chat_calls == [[{"role": "user", "content": _narrate_prompt("a storm")}]]


# T-36
def test_ws_unknown_slash_command_sends_error_event(slash_env):
    user_evt, err = _ws_send_and_collect(slash_env.client, "/nope hi", 2)

    user = user_evt["entry"]
    assert user_evt["type"] == "entry"
    assert err == {"type": "error", "message": "Unknown tool: nope", "message_id": user["id"]}
    msgs = slash_env.store.list_messages("s1")
    assert [m["role"] for m in msgs] == ["user"]
    assert msgs[0]["status"] == "error"
    assert slash_env.chat_calls == []


@pytest.fixture
def prod_env(monkeypatch):
    """Production composition (`build_services`) behind the real app; `client.chat` is a stub."""
    repos = make_default_repos()
    store = repos["session"]
    store.create_session("s1")
    services = build_services(repos, enable_tool_discovery=True)
    services["tool"].default_context["rng"] = ScriptedRng([3, 4])
    svc = services["inference"]
    chat_calls: list[list[dict]] = []

    def _chat(messages, **kw):
        chat_calls.append(messages)
        return "stub reply"

    monkeypatch.setattr(svc.client, "chat", _chat)
    app = create_app(services=services)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, chat_calls=chat_calls)
    asyncio.run(svc.shutdown())
    store.close()


# WP-8: red until build_services wires the ToolService into the inference service.
def test_ws_production_graph_dispatches_slash_roll(prod_env):
    user_evt, reply_evt, done = _ws_send_and_collect(prod_env.client, "/roll 2d6", 3)

    reply = reply_evt["entry"]
    assert reply["content"] == "2d6: [3, 4] = 7"
    assert reply["meta"]["tool"] == "roll"
    assert reply["meta"]["reply_to"] == user_evt["entry"]["id"]
    assert done["reply_id"] == reply["id"]
    assert prod_env.chat_calls == []


# WP-8: red until build_services wires the ToolService into the inference service.
def test_ws_production_graph_unknown_slash_is_error(prod_env):
    user_evt, err = _ws_send_and_collect(prod_env.client, "/nope hi", 2)

    assert err == {
        "type": "error",
        "message": "Unknown tool: nope",
        "message_id": user_evt["entry"]["id"],
    }
    assert prod_env.chat_calls == []


def _opportunity_rule() -> Rule:
    return Rule(
        id="opportunity-attacks",
        name="Opportunity Attacks",
        edition="5.5e",
        source="5e 2024 Rules",
        publisher="Wizards of the Coast",
        third_party=False,
        source_key="srd-2024_combat_opportunity-attacks",
        description=(
            "When a hostile creature you can see leaves your reach, you can use your "
            "reaction to make one melee attack against that creature."
        ),
    )


# SPEC-0014 T-41: /rules with no catalog answers from training; the disclaimer is appended.
def test_rules_slash_without_catalog_answers_from_training(slash_env):
    _post(slash_env, "/rules what is a bonus action")
    wait_idle(slash_env.svc)

    msgs = slash_env.store.list_messages("s1")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    user, reply = msgs
    assert user["status"] == "completed"
    assert reply["content"] == "stub reply\n\n" + TRAINING_DISCLAIMER
    assert reply["meta"] == {
        "tool": "rules",
        "source": "training",
        "rule_ids": [],
        "reply_to": user["id"],
    }
    assert slash_env.chat_calls == [
        [{"role": "user", "content": build_rules_prompt("what is a bonus action", [])}]
    ]


# SPEC-0014 T-42: /rules with a catalog answers from the rule text; no disclaimer.
def test_rules_slash_with_catalog_answers_from_rules(slash_env):
    rule = _opportunity_rule()
    slash_env.ts.default_context["reference"] = {"rules": [rule]}
    _post(slash_env, "/rules how do opportunity attacks work")
    wait_idle(slash_env.svc)

    msgs = slash_env.store.list_messages("s1")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    user, reply = msgs
    assert user["status"] == "completed"
    assert reply["content"] == "stub reply"
    assert reply["meta"] == {
        "tool": "rules",
        "source": "rules",
        "rule_ids": ["opportunity-attacks"],
        "reply_to": user["id"],
    }
    assert len(slash_env.chat_calls) == 1
    assert rule.description in slash_env.chat_calls[0][-1]["content"]
