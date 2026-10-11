"""Prompt pipeline wired into the inference worker, shared by REST and WS (SPEC-0006, WP-10).

Worker, REST and WS tests with a recording stub for `client.chat`; no network, no Ollama.
"""

import asyncio
import copy
import logging

import pytest

from app.config import AppSettings, Settings
from app.intelligence.prompt_builders import (
    DM_ROLE_PROMPT,
    _truncate,
    build_system_prompt,
    load_voice_configs,
)
from tests.session_helpers import AUTH, make_stub_service, wait_idle

VOICE_LINE = (
    "VOICE: TONE:neutral|PERSONA:classic_dm|VERBOSITY:normal|SENSE:balanced|CONSEQ:moderate"
)


def _expected_system() -> str:
    return build_system_prompt(Settings().prompts, load_voice_configs())


def _recording_chat(svc, monkeypatch) -> list[list[dict]]:
    """Replace client.chat with a recorder; each reply is 'reply-N' for the Nth call."""
    calls: list[list[dict]] = []

    def _chat(messages, **kw):
        calls.append(copy.deepcopy(messages))
        return f"reply-{len(calls)}"

    monkeypatch.setattr(svc.client, "chat", _chat)
    return calls


def _add_completed(store, session_id: str, message_id: str, role: str, content: str) -> None:
    store.create_message(session_id, message_id, {"role": role, "content": content})
    store.update_message_status(session_id, message_id, "completed")


@pytest.fixture
def make_svc():
    """Build services with real settings; each one is shut down after the test."""
    services = []

    def _make(**settings_kwargs):
        svc = make_stub_service(**settings_kwargs)
        services.append(svc)
        return svc

    yield _make
    for svc in services:
        asyncio.run(svc.shutdown())


@pytest.fixture
def svc(make_svc):
    return make_svc()


# T-23
def test_worker_sends_built_message_list(svc, session_store, monkeypatch):
    calls = _recording_chat(svc, monkeypatch)
    session_store.create_session("s1")
    _add_completed(session_store, "s1", "u0", "user", "earlier question")
    _add_completed(session_store, "s1", "a0", "assistant", "earlier answer")
    session_store.create_message("s1", "u1", {"role": "user", "content": "hello"})

    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=session_store)
    wait_idle(svc)

    assert calls == [
        [
            {"role": "system", "content": _expected_system()},
            {"role": "user", "content": "earlier question"},
            {"role": "assistant", "content": "earlier answer"},
            {"role": "user", "content": "hello"},
        ]
    ]
    replies = [m for m in session_store.list_messages("s1") if m["id"] not in ("u0", "a0", "u1")]
    assert len(replies) == 1
    assert replies[0]["role"] == "assistant"
    assert replies[0]["content"] == "reply-1"
    assert replies[0]["status"] == "completed"
    assert replies[0]["meta"] == {"reply_to": "u1"}


# T-24
def test_rest_back_to_back_second_request_sees_first_reply(stub_client, stub_svc, monkeypatch):
    calls = _recording_chat(stub_svc, monkeypatch)
    sid = stub_client.post("/api/v1/sessions").json()["session_id"]

    for text in ("first", "second"):
        resp = stub_client.post(
            f"/api/v1/sessions/{sid}/messages", json={"content": text}, headers=AUTH
        )
        assert resp.status_code == 202
    wait_idle(stub_svc)

    system = {"role": "system", "content": _expected_system()}
    assert calls[0] == [system, {"role": "user", "content": "first"}]
    assert calls[1] == [
        system,
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply-1"},
        {"role": "user", "content": "second"},
    ]


# T-25
def test_ws_back_to_back_second_request_sees_first_reply(stub_client, stub_svc, monkeypatch):
    calls = _recording_chat(stub_svc, monkeypatch)
    sid = stub_client.post("/api/v1/sessions").json()["session_id"]

    with stub_client.websocket_connect(f"/api/v1/ws/sessions/{sid}") as ws:
        ws.receive_json()  # snapshot
        for text in ("first", "second"):
            ws.send_json({"action": "user_message", "text": text})
            events = [ws.receive_json() for _ in range(3)]
            assert [e["type"] for e in events] == ["entry", "entry", "done"]

    system = {"role": "system", "content": _expected_system()}
    assert calls[0] == [system, {"role": "user", "content": "first"}]
    assert calls[1] == [
        system,
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply-1"},
        {"role": "user", "content": "second"},
    ]


# T-26
def test_settings_limits_are_honoured(make_svc, session_store, monkeypatch):
    svc = make_svc(app=AppSettings(max_turns=2, max_field_len=10))
    calls = _recording_chat(svc, monkeypatch)
    session_store.create_session("s1")
    _add_completed(session_store, "s1", "u0", "user", "old-zero")
    _add_completed(session_store, "s1", "a0", "assistant", "old-one")
    _add_completed(session_store, "s1", "u1", "user", "A" * 40)
    _add_completed(session_store, "s1", "a1", "assistant", "B" * 40)
    current = "the current question is long"
    session_store.create_message("s1", "cur", {"role": "user", "content": current})

    svc.enqueue(session_id="s1", message_id="cur", prompt=current, store=session_store)
    wait_idle(svc)

    assert calls[0] == [
        {"role": "system", "content": _expected_system()},
        {"role": "user", "content": _truncate("A" * 40, 10)},
        {"role": "assistant", "content": _truncate("B" * 40, 10)},
        {"role": "user", "content": current},
    ]


# T-27
def test_session_without_history_needs_no_campaign(svc, session_store, monkeypatch):
    calls = _recording_chat(svc, monkeypatch)
    session_store.create_session("s1")
    session_store.create_message("s1", "u1", {"role": "user", "content": "hello"})

    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=session_store)
    wait_idle(svc)

    assert calls[0] == [
        {"role": "system", "content": _expected_system()},
        {"role": "user", "content": "hello"},
    ]
    assert calls[0][0]["role"] == "system"


# T-28
def test_prompt_text_is_never_logged(svc, session_store, monkeypatch, caplog):
    sentinel = "SENTINEL-7f3a"
    calls = _recording_chat(svc, monkeypatch)
    session_store.create_session("s1")
    _add_completed(session_store, "s1", "u0", "user", f"question {sentinel}")
    _add_completed(session_store, "s1", "a0", "assistant", "answer")
    session_store.create_message("s1", "u1", {"role": "user", "content": f"hello {sentinel}"})

    with caplog.at_level(logging.INFO):
        svc.enqueue(
            session_id="s1", message_id="u1", prompt=f"hello {sentinel}", store=session_store
        )
        wait_idle(svc)

    assert any(sentinel in m["content"] for m in calls[0])  # the text really was sent
    for record in caplog.records:
        assert sentinel not in record.getMessage()
        assert sentinel not in str(record.__dict__)

    built = [r for r in caplog.records if r.getMessage() == "prompt.built"]
    assert len(built) == 1
    assert isinstance(built[0].history_count, int)
    assert isinstance(built[0].message_count, int)


# T-29
def test_service_survives_empty_voice_config(make_svc, session_store, monkeypatch):
    monkeypatch.setattr("app.services.inference_service.load_voice_configs", lambda: {})
    svc = make_svc()
    calls = _recording_chat(svc, monkeypatch)
    session_store.create_session("s1")
    session_store.create_message("s1", "u1", {"role": "user", "content": "hello"})

    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=session_store)
    wait_idle(svc)

    system = calls[0][0]["content"]
    assert calls[0][0]["role"] == "system"
    assert DM_ROLE_PROMPT in system
    assert VOICE_LINE in system
    user = next(m for m in session_store.list_messages("s1") if m["id"] == "u1")
    assert user["status"] == "completed"


# Extra (G-6, worker path): error, cancelled, queued and running turns never reach later history.
def test_failed_cancelled_and_unsent_turns_stay_out_of_later_history(
    svc, session_store, monkeypatch
):
    calls: list[list[dict]] = []

    def _chat(messages, **kw):
        calls.append(copy.deepcopy(messages))
        if len(calls) == 1:
            raise RuntimeError("boom")
        return f"reply-{len(calls)}"

    monkeypatch.setattr(svc.client, "chat", _chat)
    session_store.create_session("s1")
    session_store.create_message("s1", "u0", {"role": "user", "content": "fails"})
    svc.enqueue(session_id="s1", message_id="u0", prompt="fails", store=session_store)
    wait_idle(svc)

    session_store.create_message("s1", "u1", {"role": "user", "content": "works"})
    svc.enqueue(session_id="s1", message_id="u1", prompt="works", store=session_store)
    wait_idle(svc)

    session_store.create_message("s1", "u2", {"role": "user", "content": "cancelled"})
    svc.cancel("u2")
    svc.enqueue(session_id="s1", message_id="u2", prompt="cancelled", store=session_store)
    wait_idle(svc)

    session_store.create_message("s1", "u3", {"role": "user", "content": "never sent"})

    session_store.create_message("s1", "u4", {"role": "user", "content": "last"})
    svc.enqueue(session_id="s1", message_id="u4", prompt="last", store=session_store)
    wait_idle(svc)

    system = {"role": "system", "content": _expected_system()}
    assert len(calls) == 3  # u2 was cancelled before it started, so chat was not called for it
    assert calls[1] == [system, {"role": "user", "content": "works"}]
    assert calls[2] == [
        system,
        {"role": "user", "content": "works"},
        {"role": "assistant", "content": "reply-2"},
        {"role": "user", "content": "last"},
    ]
