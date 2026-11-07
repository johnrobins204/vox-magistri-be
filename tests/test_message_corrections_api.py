"""REST message corrections: PATCH message and POST regenerate (SPEC-0016 WP-5, REQ-0027; T-40..T-45)."""

from queue import Full

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.services.messages import MAX_INPUT_CHARS
from tests.session_helpers import AUTH, FakeInference, wait_idle


def _seed(store, *, user_status: str = "completed", reply_status: str = "completed") -> None:
    store.create_session("s1")
    store.create_message(
        "s1", "u1", {"role": "user", "content": "hi", "meta": None}, status=user_status
    )
    store.create_message(
        "s1",
        "a1",
        {"role": "assistant", "content": "A", "meta": {"reply_to": "u1"}},
        status=reply_status,
    )


def _client(store, inference=None) -> tuple[TestClient, FakeInference]:
    fake = inference if inference is not None else FakeInference()
    app = create_app(services={"inference": fake, "session": store})
    return TestClient(app), fake


@pytest.fixture
def api(session_store):
    _seed(session_store)
    client, fake = _client(session_store)
    with client as c:
        yield c, fake


MSG = "/api/v1/sessions/s1/messages"


# T-40
def test_patch_and_regenerate_require_token(api):
    client, _ = api

    assert client.patch(f"{MSG}/a1", json={"canon": False}).status_code == 401
    assert client.post(f"{MSG}/a1/regenerate").status_code == 401


# T-41
def test_patch_content_on_reply_sets_revision_and_canon(api):
    client, _ = api

    resp = client.patch(f"{MSG}/a1", json={"content": "B"}, headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "B"
    assert body["canon"] is True
    assert body["meta"]["revisions"][0]["content"] == "A"


def test_patch_canon_false_on_user_message_is_visible_in_get_and_list(api):
    client, _ = api

    resp = client.patch(f"{MSG}/u1", json={"canon": False}, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["canon"] is False
    one = client.get(f"{MSG}/u1", headers=AUTH).json()
    listed = {m["id"]: m for m in client.get(MSG, headers=AUTH).json()}
    assert one["canon"] is False
    assert listed["u1"]["canon"] is False
    assert listed["a1"]["canon"] is True


# T-42
def test_patch_unknown_session_is_404(api):
    client, _ = api

    resp = client.patch("/api/v1/sessions/nope/messages/a1", json={"canon": False}, headers=AUTH)

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Session not found"}


def test_patch_unknown_message_is_404(api):
    client, _ = api

    resp = client.patch(f"{MSG}/nope", json={"canon": False}, headers=AUTH)

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Message not found"}


def test_patch_content_on_user_message_is_400(api):
    client, _ = api

    resp = client.patch(f"{MSG}/u1", json={"content": "B"}, headers=AUTH)

    assert resp.status_code == 400


def test_patch_empty_body_is_400(api):
    client, _ = api

    resp = client.patch(f"{MSG}/a1", json={}, headers=AUTH)

    assert resp.status_code == 400


def test_patch_empty_content_is_422(api):
    client, _ = api

    resp = client.patch(f"{MSG}/a1", json={"content": ""}, headers=AUTH)

    assert resp.status_code == 422


def test_patch_extra_field_is_422(api):
    client, _ = api

    resp = client.patch(f"{MSG}/a1", json={"canon": False, "role": "user"}, headers=AUTH)

    assert resp.status_code == 422


def test_patch_content_over_max_input_chars_is_400(api):
    client, _ = api

    resp = client.patch(f"{MSG}/a1", json={"content": "x" * (MAX_INPUT_CHARS + 1)}, headers=AUTH)

    assert resp.status_code == 400


def test_patch_content_while_user_message_queued_is_409(session_store):
    _seed(session_store, user_status="queued", reply_status="completed")
    client, _ = _client(session_store)

    with client as c:
        resp = c.patch(f"{MSG}/a1", json={"content": "B"}, headers=AUTH)

    assert resp.status_code == 409


# T-43
def test_regenerate_queues_source_user_message(api):
    client, fake = api

    resp = client.post(f"{MSG}/a1/regenerate", headers=AUTH)

    assert resp.status_code == 202
    assert resp.json() == {"message_id": "u1", "status": "queued", "queue_position": 0}
    assert resp.headers["Location"] == f"{MSG}/u1"
    assert len(fake.calls) == 1
    assert fake.calls[0]["message_id"] == "u1"
    assert fake.calls[0]["prompt"] == "hi"


# T-44
def test_regenerate_unknown_reply_is_404(api):
    client, fake = api

    resp = client.post(f"{MSG}/nope/regenerate", headers=AUTH)

    assert resp.status_code == 404
    assert fake.calls == []


def test_regenerate_user_message_is_400(api):
    client, fake = api

    resp = client.post(f"{MSG}/u1/regenerate", headers=AUTH)

    assert resp.status_code == 400
    assert fake.calls == []


def test_regenerate_while_running_is_409(session_store):
    _seed(session_store, user_status="running", reply_status="completed")
    client, fake = _client(session_store)

    with client as c:
        resp = c.post(f"{MSG}/a1/regenerate", headers=AUTH)

    assert resp.status_code == 409
    assert fake.calls == []


def test_regenerate_queue_full_is_429_with_retry_after(session_store):
    _seed(session_store)
    client, fake = _client(session_store, FakeInference(accept=False))

    with client as c:
        resp = c.post(f"{MSG}/a1/regenerate", headers=AUTH)

    assert resp.status_code == 429
    assert resp.json() == {"status": "queued_full", "retry_after": 5, "message_id": "u1"}
    assert resp.headers["Retry-After"] == "5"
    assert len(fake.calls) == 1


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


def test_regenerate_queue_full_keeps_user_turn_in_next_prompt(session_store, stub_svc, monkeypatch):
    _seed(session_store)
    full = _queue_full_until_released(stub_svc, monkeypatch)
    prompts = _capture_prompts(stub_svc, monkeypatch)
    client, _ = _client(session_store, stub_svc)

    with client as c:
        resp = c.post(f"{MSG}/a1/regenerate", headers=AUTH)
        assert resp.status_code == 429
        assert session_store.get_message("s1", "u1")["status"] == "completed"

        full["full"] = False
        resp = c.post(MSG, json={"content": "again"}, headers=AUTH)
        assert resp.status_code == 202
        wait_idle(stub_svc)

    assert prompts
    assert ("user", "hi") in prompts[-1]
    assert ("assistant", "A") in prompts[-1]


# T-45
def test_openapi_lists_correction_routes_and_boolean_canon(session_store):
    client, _ = _client(session_store)

    schema = client.get("/openapi.json").json()

    paths = schema["paths"]
    assert "patch" in paths["/api/v1/sessions/{session_id}/messages/{message_id}"]
    assert "post" in paths["/api/v1/sessions/{session_id}/messages/{message_id}/regenerate"]
    assert (
        schema["components"]["schemas"]["MessageResp"]["properties"]["canon"]["type"] == "boolean"
    )
