"""The single session WebSocket (SPEC-0004, WP-4, test items 17-27 and 26a)."""

from datetime import datetime
from queue import Full

import pytest
from fastapi.routing import APIWebSocketRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.v1.ws import ws_send
from app.factory import create_app
from tests.session_helpers import AUTH, FakeInference, wait_idle


def _new_session(client) -> str:
    resp = client.post("/api/v1/sessions")
    assert resp.status_code == 201
    return resp.json()["session_id"]


def _ws_url(sid: str) -> str:
    return f"/api/v1/ws/sessions/{sid}"


# 17
def test_ws_connect_sends_snapshot_from_store(stub_client, session_store):
    sid = _new_session(stub_client)
    session_store.create_message(sid, "m1", {"role": "user", "content": "hi"})

    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        snap = ws.receive_json()

    assert snap["type"] == "snapshot"
    assert snap["session_id"] == sid
    assert len(snap["entries"]) == 1
    assert snap["entries"][0]["id"] == "m1"
    assert isinstance(snap["snapshot_at"], float)
    assert "run_id" not in snap


# 18
def test_ws_user_message_is_stored_with_reply_semantics(stub_client, stub_svc):
    sid = _new_session(stub_client)

    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        ws.receive_json()  # snapshot
        ws.send_json({"action": "user_message", "text": "hello"})
        user_evt = ws.receive_json()
        reply_evt = ws.receive_json()
        done = ws.receive_json()

    assert user_evt["type"] == "entry"
    user = user_evt["entry"]
    assert user["role"] == "user"
    assert user["content"] == "hello"

    assert reply_evt["type"] == "entry"
    reply = reply_evt["entry"]
    assert reply["role"] == "assistant"
    assert reply["content"] == "stub reply"
    assert reply["meta"]["reply_to"] == user["id"]

    assert done == {"type": "done", "message_id": user["id"], "reply_id": reply["id"]}

    listed = stub_client.get(f"/api/v1/sessions/{sid}/messages", headers=AUTH).json()
    assert len(listed) == 2
    assert listed[0]["role"] == "user"
    assert listed[0]["content"] == "hello"
    assert listed[0]["status"] == "completed"
    assert listed[1]["role"] == "assistant"
    assert listed[1]["meta"]["reply_to"] == listed[0]["id"]
    assert [m["id"] for m in listed] == [user["id"], reply["id"]]

    snap = stub_client.get(f"/api/v1/intel/sessions/{sid}/snapshot").json()
    assert [e["id"] for e in snap["entries"]] == [user["id"], reply["id"]]


# 19
def test_ws_sees_messages_created_via_rest(stub_client, stub_svc):
    sid = _new_session(stub_client)
    stub_client.post(f"/api/v1/sessions/{sid}/messages", json={"content": "hi"}, headers=AUTH)
    wait_idle(stub_svc)
    listed_ids = [
        m["id"] for m in stub_client.get(f"/api/v1/sessions/{sid}/messages", headers=AUTH).json()
    ]

    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        snap = ws.receive_json()

    assert len(snap["entries"]) == 2
    assert [e["id"] for e in snap["entries"]] == listed_ids


# 20
def test_ws_client_message_id_is_idempotent(stub_client, stub_svc, session_store, monkeypatch):
    calls: list[list[dict]] = []

    def counting_chat(messages, **kw):
        calls.append(messages)
        return "stub reply"

    monkeypatch.setattr(stub_svc.client, "chat", counting_chat)
    sid = _new_session(stub_client)
    payload = {"action": "user_message", "text": "hello", "client_message_id": "c1"}

    rounds = []
    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        ws.receive_json()  # snapshot
        for _ in range(2):
            ws.send_json(payload)
            rounds.append([ws.receive_json() for _ in range(3)])

    for events in rounds:
        assert [e["type"] for e in events] == ["entry", "entry", "done"]
    user_ids = [events[0]["entry"]["id"] for events in rounds]
    reply_ids = [events[1]["entry"]["id"] for events in rounds]
    assert user_ids[0] == user_ids[1]
    assert reply_ids[0] == reply_ids[1]

    assert len(session_store.list_messages(sid)) == 2
    assert len(calls) == 1


# 21
def test_ws_inference_error_sends_error_event(stub_client, stub_svc, session_store, monkeypatch):
    def failing_chat(messages, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(stub_svc.client, "chat", failing_chat)
    sid = _new_session(stub_client)

    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        ws.receive_json()  # snapshot
        ws.send_json({"action": "user_message", "text": "hello"})
        entry = ws.receive_json()
        err = ws.receive_json()
        ws.send_json({"action": "status"})
        status_evt = ws.receive_json()

    assert entry["type"] == "entry"
    assert entry["entry"]["role"] == "user"
    assert err == {"type": "error", "message_id": entry["entry"]["id"], "message": "boom"}

    stored = session_store.list_messages(sid)
    assert len(stored) == 1
    assert stored[0]["status"] == "error"

    assert status_evt["type"] == "status"


# 22
@pytest.mark.parametrize("bad_id", ["does-not-exist", "1"])
def test_ws_unknown_session_closes_1008(stub_client, session_store, bad_id):
    with pytest.raises(WebSocketDisconnect) as exc:
        with stub_client.websocket_connect(_ws_url(bad_id)):
            pass

    assert exc.value.code == 1008
    assert session_store.get_session(bad_id) is None


# 23
def test_ws_bad_input_gets_error_event_and_stays_open(stub_client, session_store):
    sid = _new_session(stub_client)
    bad_inputs = [
        {"action": "nope"},
        {"action": "user_message", "text": ""},
        {"action": "user_message"},
        {"action": "user_message", "text": "x", "client_message_id": 5},
    ]

    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        ws.receive_json()  # snapshot
        for bad in bad_inputs:
            ws.send_json(bad)
            evt = ws.receive_json()
            assert evt["type"] == "error"
            assert evt["message"]
        ws.send_json({"action": "status"})
        assert ws.receive_json()["type"] == "status"

    assert session_store.list_messages(sid) == []


# 23b (SPEC-0004 WP-4h): malformed frames are reported as errors and keep the socket open
def test_ws_non_json_frame_gets_error_event_and_stays_open(stub_client, session_store):
    sid = _new_session(stub_client)

    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        ws.receive_json()  # snapshot
        ws.send_text("this is not json")
        evt = ws.receive_json()
        assert evt["type"] == "error"
        assert evt["message"]
        ws.send_json({"action": "status"})
        assert ws.receive_json()["type"] == "status"

    assert session_store.list_messages(sid) == []


# 24
def test_ws_reply_wait_is_bounded(session_store, monkeypatch):
    monkeypatch.setattr("app.api.v1.ws._reply_timeout_seconds", lambda _inference: 0.3)
    app = create_app(services={"inference": FakeInference(), "session": session_store})

    with TestClient(app) as c:
        sid = _new_session(c)
        with c.websocket_connect(_ws_url(sid)) as ws:
            ws.receive_json()  # snapshot
            ws.send_json({"action": "user_message", "text": "hello"})
            entry = ws.receive_json()
            err = ws.receive_json()

    assert entry["type"] == "entry"
    assert err["type"] == "error"
    assert "Timed out" in err["message"]
    assert err["message_id"] == entry["entry"]["id"]

    stored = session_store.list_messages(sid)
    assert len(stored) == 1
    assert stored[0]["status"] == "queued"


# 25
def test_ws_queue_full_sends_error_event(session_store):
    app = create_app(services={"inference": FakeInference(accept=False), "session": session_store})

    with TestClient(app) as c:
        sid = _new_session(c)
        with c.websocket_connect(_ws_url(sid)) as ws:
            ws.receive_json()  # snapshot
            ws.send_json({"action": "user_message", "text": "hello"})
            entry = ws.receive_json()
            err = ws.receive_json()

    assert entry["type"] == "entry"
    assert err["type"] == "error"
    assert "queue full" in err["message"]
    assert err["message_id"] == entry["entry"]["id"]

    stored = session_store.list_messages(sid)
    assert [m["id"] for m in stored] == [entry["entry"]["id"]]


# 26
def test_ws_cancelled_job_sends_error_event(stub_client, stub_svc, session_store, monkeypatch):
    chat_calls: list[list[dict]] = []

    def must_not_chat(messages, **kw):
        chat_calls.append(messages)
        raise AssertionError("chat must not be called for a cancelled job")

    monkeypatch.setattr(stub_svc.client, "chat", must_not_chat)

    orig_enqueue = stub_svc.enqueue

    def enqueue_cancelled(*, session_id, message_id, prompt, store):
        stub_svc.cancel(message_id)
        return orig_enqueue(
            session_id=session_id, message_id=message_id, prompt=prompt, store=store
        )

    monkeypatch.setattr(stub_svc, "enqueue", enqueue_cancelled)
    sid = _new_session(stub_client)

    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        ws.receive_json()  # snapshot
        ws.send_json({"action": "user_message", "text": "hello"})
        entry = ws.receive_json()
        err = ws.receive_json()

    assert entry["type"] == "entry"
    assert err == {"type": "error", "message_id": entry["entry"]["id"], "message": "cancelled"}

    stored = session_store.list_messages(sid)
    assert len(stored) == 1
    assert stored[0]["status"] == "cancelled"
    assert chat_calls == []


def _leaf_routes(routes):
    # FastAPI 0.141 nests included routers (`_IncludedRouter.original_router`), so
    # `app.routes` only shows those wrappers; walk down to the real route objects.
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _leaf_routes(nested.routes)
        else:
            yield route


# 26a
def test_exactly_one_ws_route(stub_client):
    paths = [
        r.path for r in _leaf_routes(stub_client.app.routes) if isinstance(r, APIWebSocketRoute)
    ]

    assert paths == ["/api/v1/ws/sessions/{session_id}"]


# 27
async def test_ws_send_does_not_swallow_non_disconnect_errors():
    class BoomSocket:
        async def send_json(self, data, mode="text"):
            raise ValueError("boom")

    with pytest.raises(ValueError):
        await ws_send(BoomSocket(), {"a": 1})

    class RecordingSocket:
        def __init__(self):
            self.sent = []

        async def send_json(self, data, mode="text"):
            self.sent.append(data)

    recorder = RecordingSocket()
    await ws_send(recorder, {"t": datetime(2026, 1, 1)})

    assert isinstance(recorder.sent[0]["t"], str)
    assert recorder.sent[0]["t"].startswith("2026-01-01")


# SPEC-0016 WP-7: WebSocket `regenerate` action (REQ-0027)
def _one_turn(ws) -> tuple[str, str]:
    ws.receive_json()  # snapshot
    ws.send_json({"action": "user_message", "text": "hello"})
    user_id = ws.receive_json()["entry"]["id"]
    reply_id = ws.receive_json()["entry"]["id"]
    ws.receive_json()  # done
    return user_id, reply_id


def _seed_turn(store, sid: str) -> tuple[str, str]:
    store.create_message(sid, "u1", {"role": "user", "content": "hi"}, status="completed")
    store.create_message(
        sid,
        "a1",
        {"role": "assistant", "content": "stub reply", "meta": {"reply_to": "u1"}},
        status="completed",
    )
    return "u1", "a1"


# T-60
def test_ws_regenerate(stub_client, stub_svc, monkeypatch):
    sid = _new_session(stub_client)
    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        user_id, reply_id = _one_turn(ws)
        monkeypatch.setattr(stub_svc.client, "chat", lambda messages, **kw: "v2")

        ws.send_json({"action": "regenerate", "message_id": reply_id})
        user_evt = ws.receive_json()
        reply_evt = ws.receive_json()
        done = ws.receive_json()

    assert user_evt["type"] == "entry"
    assert user_evt["entry"]["id"] == user_id
    assert user_evt["entry"]["role"] == "user"

    assert reply_evt["type"] == "entry"
    reply = reply_evt["entry"]
    assert reply["id"] == reply_id
    assert reply["content"] == "v2"
    assert len(reply["meta"]["revisions"]) == 1
    assert reply["meta"]["revisions"][0]["content"] == "stub reply"
    assert reply["canon"] is True

    assert done == {"type": "done", "message_id": user_id, "reply_id": reply_id}


# T-61
def test_ws_regenerate_errors_keep_socket(stub_client, session_store):
    sid = _new_session(stub_client)
    user_id, reply_id = _seed_turn(session_store, sid)
    bad_requests = [
        ({"action": "regenerate"}, "message_id is required"),
        ({"action": "regenerate", "message_id": ""}, "message_id is required"),
        ({"action": "regenerate", "message_id": 5}, "message_id is required"),
        ({"action": "regenerate", "message_id": "nope"}, "Message not found"),
        ({"action": "regenerate", "message_id": user_id}, "assistant"),
    ]

    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        ws.receive_json()  # snapshot
        for request, expected in bad_requests:
            ws.send_json(request)
            evt = ws.receive_json()
            assert evt["type"] == "error"
            assert expected in evt["message"]
        ws.send_json({"action": "status"})
        assert ws.receive_json()["type"] == "status"


def test_ws_regenerate_queue_full_sends_error_with_user_id(session_store):
    app = create_app(services={"inference": FakeInference(accept=False), "session": session_store})

    with TestClient(app) as c:
        sid = _new_session(c)
        user_id, reply_id = _seed_turn(session_store, sid)
        with c.websocket_connect(_ws_url(sid)) as ws:
            ws.receive_json()  # snapshot
            ws.send_json({"action": "regenerate", "message_id": reply_id})
            err = ws.receive_json()
            ws.send_json({"action": "status"})
            status_evt = ws.receive_json()

    assert err["type"] == "error"
    assert "queue full" in err["message"]
    assert err["message_id"] == user_id
    assert status_evt["type"] == "status"


def _queue_full_until_released(svc, monkeypatch) -> dict:
    """The real enqueue sees a full queue while state["full"] is True."""
    state = {"full": True}
    accept = svc._queue.put_nowait

    def put_nowait(job):
        if state["full"]:
            raise Full
        accept(job)

    monkeypatch.setattr(svc._queue, "put_nowait", put_nowait)
    return state


def _capture_prompts(svc, monkeypatch) -> list:
    prompts: list = []

    def chat(messages, **kw):
        prompts.append([(m["role"], m["content"]) for m in messages])
        return "again reply"

    monkeypatch.setattr(svc.client, "chat", chat)
    return prompts


def test_ws_regenerate_queue_full_keeps_user_turn_in_next_prompt(
    stub_client, stub_svc, session_store, monkeypatch
):
    sid = _new_session(stub_client)
    user_id, reply_id = _seed_turn(session_store, sid)
    full = _queue_full_until_released(stub_svc, monkeypatch)
    prompts = _capture_prompts(stub_svc, monkeypatch)

    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        ws.receive_json()  # snapshot
        ws.send_json({"action": "regenerate", "message_id": reply_id})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["message_id"] == user_id
        assert session_store.get_message(sid, user_id)["status"] == "completed"

        full["full"] = False
        ws.send_json({"action": "user_message", "text": "again"})
        ws.receive_json()  # entry
        ws.receive_json()  # reply
        ws.receive_json()  # done

    assert prompts
    assert ("user", "hi") in prompts[-1]
    assert ("assistant", "stub reply") in prompts[-1]


# T-62
def test_ws_failed_regenerate(stub_client, stub_svc, session_store, monkeypatch):
    sid = _new_session(stub_client)
    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        user_id, reply_id = _one_turn(ws)

        def failing_chat(messages, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(stub_svc.client, "chat", failing_chat)
        ws.send_json({"action": "regenerate", "message_id": reply_id})
        ws.receive_json()  # user entry
        err = ws.receive_json()

    assert err == {"type": "error", "message_id": user_id, "message": "boom"}
    reply = session_store.get_message(sid, reply_id)
    assert reply["content"] == "stub reply"


# T-63
def test_ws_snapshot_shows_rest_correction(stub_client, stub_svc):
    sid = _new_session(stub_client)
    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        _, reply_id = _one_turn(ws)

    resp = stub_client.patch(
        f"/api/v1/sessions/{sid}/messages/{reply_id}", json={"content": "edited"}, headers=AUTH
    )
    assert resp.status_code == 200

    with stub_client.websocket_connect(_ws_url(sid)) as ws:
        snap = ws.receive_json()

    entry = next(e for e in snap["entries"] if e["id"] == reply_id)
    assert entry["content"] == "edited"
    assert entry["canon"] is True
    assert entry["meta"]["revisions"][0]["content"] == "stub reply"
