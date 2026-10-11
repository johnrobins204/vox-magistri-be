import asyncio
import time
import types

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.services.inference_service import OllamaInferenceService
from app.services.repos import InMemorySessionStore


@pytest.fixture
def svc():
    settings = types.SimpleNamespace(
        ollama=types.SimpleNamespace(
            base_url="http://127.0.0.1:1", model="stub", timeout_seconds=1.0
        )
    )
    service = OllamaInferenceService(settings)
    yield service
    asyncio.run(service.shutdown())


@pytest.fixture
def store():
    s = InMemorySessionStore()
    s.create_session("s1")
    s.create_message("s1", "u1", {"role": "user", "content": "hello"})
    return s


def wait_idle(svc, timeout=5.0):
    deadline = time.monotonic() + timeout
    while svc._queue.unfinished_tasks != 0:
        if time.monotonic() > deadline:
            pytest.fail("inference worker did not become idle")
        time.sleep(0.01)


def test_reply_is_new_assistant_message(svc, store, monkeypatch):
    monkeypatch.setattr(svc.client, "generate", lambda prompt, **kw: "stub reply")
    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    msgs = store.list_messages("s1")
    assert len(msgs) == 2
    assert msgs[0]["id"] == "u1"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "stub reply"
    assert msgs[1]["id"] != "u1"
    assert msgs[1]["meta"]["reply_to"] == "u1"


def test_user_message_not_modified(svc, store, monkeypatch):
    monkeypatch.setattr(svc.client, "generate", lambda prompt, **kw: "stub reply")
    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    user = next(m for m in store.list_messages("s1") if m["id"] == "u1")
    assert user["role"] == "user"
    assert user["content"] == "hello"
    assert user["status"] == "completed"


def test_reply_message_is_completed_and_unlinked(svc, store, monkeypatch):
    monkeypatch.setattr(svc.client, "generate", lambda prompt, **kw: "stub reply")
    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    reply = store.list_messages("s1")[1]
    assert reply["status"] == "completed"
    assert reply["client_message_id"] is None
    assert reply["meta"] == {"reply_to": "u1"}


def test_error_path_preserves_user_message(svc, store, monkeypatch):
    def boom(prompt, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(svc.client, "generate", boom)
    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    msgs = store.list_messages("s1")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello"
    assert msgs[0]["status"] == "error"
    assert msgs[0]["meta"]["error"] == "boom"


def test_cancel_before_start_preserved(svc, store, monkeypatch):
    def fail_if_called(prompt, **kw):
        raise AssertionError("generate must not be called for a cancelled job")

    monkeypatch.setattr(svc.client, "generate", fail_if_called)
    svc.cancel("u1")
    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    msgs = store.list_messages("s1")
    assert len(msgs) == 1
    assert msgs[0]["status"] == "cancelled"
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello"


def test_status_and_messages_endpoints_after_reply(svc, store, monkeypatch):
    monkeypatch.setattr(svc.client, "generate", lambda prompt, **kw: "stub reply")
    app = create_app(services={"inference": svc, "session": store})
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(app) as c:
        svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
        wait_idle(svc)

        status_resp = c.get("/api/v1/sessions/s1/messages/u1/status", headers=headers)
        assert status_resp.status_code == 200
        body = status_resp.json()
        assert body["message_id"] == "u1"
        assert body["status"] == "completed"

        list_resp = c.get("/api/v1/sessions/s1/messages", headers=headers)
        assert list_resp.status_code == 200
        items = list_resp.json()
        assert len(items) == 2
        assert items[1]["role"] == "assistant"
        assert items[1]["meta"]["reply_to"] == "u1"


def test_store_write_failure_is_reported_as_error(svc, store, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr(svc.client, "generate", lambda prompt, **kw: "stub reply")
    monkeypatch.setattr(store, "create_message", boom)
    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    msgs = store.list_messages("s1")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello"
    assert msgs[0]["status"] == "error"
    assert msgs[0]["meta"]["error"] == "store down"


def test_append_reply_adds_completed_assistant_message(svc, store):
    reply_id = svc._append_reply(store, "s1", "u1", "stub reply")

    msgs = store.list_messages("s1")
    assert len(msgs) == 2
    assert msgs[0]["id"] == "u1"
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello"
    reply = msgs[1]
    assert isinstance(reply_id, str)
    assert reply["id"] == reply_id != "u1"
    assert reply["role"] == "assistant"
    assert reply["content"] == "stub reply"
    assert reply["status"] == "completed"
    assert reply["client_message_id"] is None
    assert reply["meta"] == {"reply_to": "u1"}


def test_append_reply_propagates_store_errors(svc, store, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr(store, "create_message", boom)

    with pytest.raises(RuntimeError, match="store down"):
        svc._append_reply(store, "s1", "u1", "stub reply")
    assert len(store.list_messages("s1")) == 1
