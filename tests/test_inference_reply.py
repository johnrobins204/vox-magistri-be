import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.services.repos import SqliteSessionStore
from tests.session_helpers import AUTH, make_stub_service, wait_idle


class _SpyStore(SqliteSessionStore):
    """Records every update_message_status call as (session_id, message_id, status, meta)."""

    def __init__(self):
        super().__init__(":memory:")
        self.calls: list[tuple] = []

    def update_message_status(self, session_id, message_id, status, meta=None):
        self.calls.append((session_id, message_id, status, meta))
        super().update_message_status(session_id, message_id, status, meta=meta)


@pytest.fixture
def svc():
    service = make_stub_service()
    yield service
    asyncio.run(service.shutdown())


@pytest.fixture
def store():
    s = _SpyStore()
    s.create_session("s1")
    s.create_message("s1", "u1", {"role": "user", "content": "hello"})
    yield s
    s.close()


def test_reply_is_new_assistant_message(svc, store, monkeypatch):
    monkeypatch.setattr(svc.client, "chat", lambda messages, **kw: "stub reply")
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
    monkeypatch.setattr(svc.client, "chat", lambda messages, **kw: "stub reply")
    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    user = next(m for m in store.list_messages("s1") if m["id"] == "u1")
    assert user["role"] == "user"
    assert user["content"] == "hello"
    assert user["status"] == "completed"


def test_reply_message_is_completed_and_unlinked(svc, store, monkeypatch):
    monkeypatch.setattr(svc.client, "chat", lambda messages, **kw: "stub reply")
    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    reply = store.list_messages("s1")[1]
    assert reply["status"] == "completed"
    assert reply["client_message_id"] is None
    assert reply["meta"] == {"reply_to": "u1"}


def test_error_path_preserves_user_message(svc, store, monkeypatch):
    def boom(messages, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(svc.client, "chat", boom)
    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    msgs = store.list_messages("s1")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello"
    assert msgs[0]["status"] == "error"
    assert msgs[0]["meta"]["error"] == "boom"


def test_cancel_before_start_preserved(svc, store, monkeypatch):
    def fail_if_called(messages, **kw):
        raise AssertionError("chat must not be called for a cancelled job")

    monkeypatch.setattr(svc.client, "chat", fail_if_called)
    svc.cancel("u1")
    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    msgs = store.list_messages("s1")
    assert len(msgs) == 1
    assert msgs[0]["status"] == "cancelled"
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello"


def test_status_and_messages_endpoints_after_reply(svc, store, monkeypatch):
    monkeypatch.setattr(svc.client, "chat", lambda messages, **kw: "stub reply")
    app = create_app(services={"inference": svc, "session": store})
    headers = AUTH

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


def test_worker_writes_status_via_update_message_status(svc, store, monkeypatch):
    monkeypatch.setattr(svc.client, "chat", lambda messages, **kw: "stub reply")
    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    u1_calls = [c for c in store.calls if c[1] == "u1"]
    assert [c[2] for c in u1_calls] == ["queued", "running", "completed"]
    for _, _, _, meta in u1_calls:
        assert meta["updated_by"] == "inference_worker"

    reply = store.list_messages("s1")[1]
    assert reply["role"] == "assistant"
    assert ("s1", reply["id"], "completed", None) in store.calls
    assert reply["meta"] == {"reply_to": "u1"}

    user = next(m for m in store.list_messages("s1") if m["id"] == "u1")
    assert user["status"] == "completed"
    assert user["meta"]["updated_by"] == "inference_worker"


def test_error_status_and_meta_written_in_one_call(svc, store, monkeypatch):
    def boom(messages, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(svc.client, "chat", boom)
    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    u1_calls = [c for c in store.calls if c[1] == "u1"]
    error_calls = [c for c in u1_calls if c[2] == "error"]
    assert len(error_calls) == 1
    _, _, _, meta = error_calls[0]
    assert meta["error"] == "boom"
    assert meta["updated_by"] == "inference_worker"
    assert u1_calls[-1] is error_calls[0]
    assert not hasattr(svc, "_update_message_meta")

    user = next(m for m in store.list_messages("s1") if m["id"] == "u1")
    assert user["status"] == "error"
    assert user["meta"]["error"] == "boom"


def test_store_write_failure_is_reported_as_error(svc, store, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr(svc.client, "chat", lambda messages, **kw: "stub reply")
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


def test_unknown_message_write_is_logged_and_worker_survives(svc, store, monkeypatch, caplog):
    monkeypatch.setattr(svc.client, "chat", lambda messages, **kw: "stub reply")

    with caplog.at_level(logging.ERROR):
        svc.enqueue(session_id="s1", message_id="ghost", prompt="hi", store=store)
        wait_idle(svc)

    assert any(
        r.levelno == logging.ERROR and r.getMessage() == "update_message_status failed"
        for r in caplog.records
    )
    assert svc._worker.is_alive()

    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
    wait_idle(svc)

    user = next(m for m in store.list_messages("s1") if m["id"] == "u1")
    assert user["status"] == "completed"
