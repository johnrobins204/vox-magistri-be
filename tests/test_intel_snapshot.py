"""Snapshot route reads the shared session store with uuid ids (SPEC-0004, WP-3, items 12-16)."""

import json

from tests.session_helpers import AUTH, wait_idle


def _new_session(client) -> str:
    resp = client.post("/api/v1/sessions")
    assert resp.status_code == 201
    return resp.json()["session_id"]


def test_snapshot_reflects_rest_messages(stub_client, stub_svc):
    sid = _new_session(stub_client)
    post = stub_client.post(
        f"/api/v1/sessions/{sid}/messages", json={"content": "hello"}, headers=AUTH
    )
    assert post.status_code == 202
    wait_idle(stub_svc)

    resp = stub_client.get(f"/api/v1/intel/sessions/{sid}/snapshot")

    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == sid
    assert len(body["entries"]) == 2
    user, reply = body["entries"]
    assert user["role"] == "user"
    assert user["content"] == "hello"
    assert user["status"] == "completed"
    assert reply["role"] == "assistant"
    assert reply["content"] == "stub reply"
    assert reply["meta"]["reply_to"] == user["id"]
    assert all(isinstance(entry["id"], str) for entry in body["entries"])
    assert isinstance(body["snapshot_at"], float)
    assert "run_id" not in body


def test_snapshot_matches_rest_message_list(stub_client, stub_svc):
    sid = _new_session(stub_client)
    stub_client.post(f"/api/v1/sessions/{sid}/messages", json={"content": "hello"}, headers=AUTH)
    wait_idle(stub_svc)

    snapshot = stub_client.get(f"/api/v1/intel/sessions/{sid}/snapshot").json()
    listed = stub_client.get(f"/api/v1/sessions/{sid}/messages", headers=AUTH).json()

    assert [e["id"] for e in snapshot["entries"]] == [m["id"] for m in listed]


def test_snapshot_empty_session_is_200_with_no_entries(stub_client):
    sid = _new_session(stub_client)

    resp = stub_client.get(f"/api/v1/intel/sessions/{sid}/snapshot")

    assert resp.status_code == 200
    assert resp.json()["entries"] == []


def test_snapshot_unknown_session_is_404(stub_client):
    assert stub_client.get("/api/v1/intel/sessions/does-not-exist/snapshot").status_code == 404
    assert stub_client.get("/api/v1/intel/sessions/1/snapshot").status_code == 404


def test_openapi_has_no_integer_session_model(stub_client):
    schema = stub_client.get("/openapi.json").json()

    assert "/api/v1/intel/sessions/{session_id}/snapshot" in schema["paths"]
    assert "/api/v1/intel/sessions/{run_id}/snapshot" not in schema["paths"]
    assert "SessionEntry" not in schema["components"]["schemas"]
    assert "run_id" not in json.dumps(schema)
