"""REST message routes and removal of /api/v1/stream (SPEC-0004, WP-2, items 6-11)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.factory import create_app
from tests.session_helpers import AUTH, FakeInference, wait_idle


def _new_session(client: TestClient) -> str:
    resp = client.post("/api/v1/sessions")
    assert resp.status_code == 201
    return resp.json()["session_id"]


def test_rest_post_message_response_shape(stub_client):
    sid = _new_session(stub_client)

    resp = stub_client.post(
        f"/api/v1/sessions/{sid}/messages", json={"content": "hello"}, headers=AUTH
    )

    assert resp.status_code == 202
    body = resp.json()
    assert {"message_id", "status", "queue_position"} <= set(body)
    uuid.UUID(body["message_id"])
    assert body["status"] == "queued"
    assert resp.headers["Location"] == f"/api/v1/sessions/{sid}/messages/{body['message_id']}"


def test_rest_post_message_idempotent(stub_client, stub_svc):
    sid = _new_session(stub_client)
    payload = {"content": "hello", "client_message_id": "c-rest-1"}

    first = stub_client.post(f"/api/v1/sessions/{sid}/messages", json=payload, headers=AUTH)
    second = stub_client.post(f"/api/v1/sessions/{sid}/messages", json=payload, headers=AUTH)

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["message_id"] == first.json()["message_id"]
    assert "status" in second.json()

    wait_idle(stub_svc)
    messages = stub_client.get(f"/api/v1/sessions/{sid}/messages", headers=AUTH).json()
    assert len(messages) == 2
    assert [m["role"] for m in messages] == ["user", "assistant"]


def test_rest_post_message_queue_full_returns_429(session_store):
    app = create_app(services={"inference": FakeInference(accept=False), "session": session_store})
    with TestClient(app) as client:
        sid = _new_session(client)

        resp = client.post(
            f"/api/v1/sessions/{sid}/messages", json={"content": "hello"}, headers=AUTH
        )

        assert resp.status_code == 429
        assert resp.headers["Retry-After"] == "5"
        body = resp.json()
        assert body["status"] == "queued_full"
        assert body["retry_after"] == 5
        assert "message_id" in body
        # The user message stays stored when the queue rejects it.
        stored = session_store.list_messages(sid)
        assert [m["id"] for m in stored] == [body["message_id"]]


def test_rest_post_message_too_long_is_400(stub_client, session_store):
    sid = _new_session(stub_client)

    resp = stub_client.post(
        f"/api/v1/sessions/{sid}/messages", json={"content": "x" * (1024 * 4 + 1)}, headers=AUTH
    )

    assert resp.status_code == 400
    assert session_store.list_messages(sid) == []


def test_rest_post_message_unknown_session_is_404(stub_client):
    resp = stub_client.post("/api/v1/sessions/nope/messages", json={"content": "hi"}, headers=AUTH)

    assert resp.status_code == 404


def _route_paths(routes):
    """All route paths, descending into included routers (FastAPI wraps them)."""
    for route in routes:
        path = getattr(route, "path", None)
        if path:
            yield path
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _route_paths(inner.routes)


def test_stream_endpoint_removed(stub_client):
    # app.routes only lists the wrapper for included routers, so walk into them.
    assert "/api/v1/stream" not in set(_route_paths(stub_client.app.routes))

    with pytest.raises(WebSocketDisconnect):
        with stub_client.websocket_connect("/api/v1/stream"):
            pass
    # With a valid Bearer header the removed route would accept; it must not.
    with pytest.raises(WebSocketDisconnect):
        with stub_client.websocket_connect("/api/v1/stream", headers=AUTH):
            pass
