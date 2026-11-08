"""World mention detection through the REST API and worker (SPEC-0019 WP-6, REQ-0028, PAT-ARCH-012).

T-40 pending queue, T-41 pending not injected until approved, T-42 rejected never re-proposed.
Chat goes through POST /api/v1/sessions/{id}/messages; assertions read the recorded system message.
No network and no Ollama: `client.chat` is a recording stub that returns `reply_text["v"]`.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.services.repos import SqliteSessionStore
from tests.session_helpers import AUTH, make_stub_service, wait_idle

F1 = (
    "You push open the door of the Rusty Anchor and the noise of the tavern washes over you. "
    'Behind the bar, Old Marta polishes a mug and nods. "Aria, you came back," she says. '
    '"Captain Harl was asking after you."\n'
    "Harl sits in the corner with two sailors from Brightwater. He raises a hand and Marta "
    'whispers, "Careful. The Captain owes money to half of Brightwater." '
    "Veyra's name is not spoken here."
)
F1_NAMES = {"Rusty Anchor", "Old Marta", "Captain Harl"}
MESSAGES = "/api/v1/sessions/s1/messages"
ENTITIES = "/api/v1/world/entities"


@pytest.fixture
def env(monkeypatch):
    store = SqliteSessionStore(":memory:")
    store.create_session("s1")
    store.create_entity(name="Brightwater", status="canon")
    reply_text = {"v": F1}
    svc = make_stub_service(world_store=store)
    chat_calls: list[list[dict]] = []

    def _chat(messages, **kw):
        chat_calls.append(messages)
        return reply_text["v"]

    monkeypatch.setattr(svc.client, "chat", _chat)
    app = create_app(services={"inference": svc, "session": store, "world": store})
    with TestClient(app) as client:
        yield SimpleNamespace(
            store=store,
            svc=svc,
            client=client,
            chat_calls=chat_calls,
            reply_text=reply_text,
        )
    asyncio.run(svc.shutdown())
    store.close()


def _chat(env, content: str) -> None:
    resp = env.client.post(MESSAGES, json={"content": content}, headers=AUTH)
    assert resp.status_code == 202, resp.text
    wait_idle(env.svc)


def _entities(env, **params) -> list[dict]:
    resp = env.client.get(ENTITIES, params=params, headers=AUTH)
    assert resp.status_code == 200, resp.text
    return resp.json()["entities"]


def _named(env, name: str, status: str = "pending") -> dict:
    [row] = [e for e in _entities(env, status=status) if e["name"] == name]
    return row


def _last_reply_id(env) -> str:
    replies = [m for m in env.store.list_messages("s1") if m["role"] == "assistant"]
    return replies[-1]["id"]


def _system(env, prompt_index: int) -> str:
    messages = env.chat_calls[prompt_index]
    assert messages[0]["role"] == "system"
    return messages[0]["content"]


def test_chat_reply_shows_in_pending_queue(env):
    _chat(env, "Tell me about the tavern.")
    reply_id = _last_reply_id(env)

    pending = _entities(env, status="pending")
    assert {e["name"] for e in pending} == F1_NAMES
    for entity in pending:
        assert entity["session_id"] is None
        assert entity["evidence"]["source_message_id"] == reply_id

    canon = _entities(env, status="canon")
    assert {e["name"] for e in canon} == {"Brightwater"}


def test_pending_not_injected_until_approved(env):
    _chat(env, "Tell me about the tavern.")
    _chat(env, "Tell me more.")
    assert "Rusty Anchor" not in _system(env, 1)

    rusty = _named(env, "Rusty Anchor")
    resp = env.client.patch(
        f"{ENTITIES}/{rusty['id']}", json={"status": "canon", "kind": "place"}, headers=AUTH
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "canon"
    assert resp.json()["kind"] == "place"

    _chat(env, "And now?")
    assert "Rusty Anchor" in _system(env, 2)


def test_rejected_never_reproposed(env):
    _chat(env, "Tell me about the tavern.")
    marta = _named(env, "Old Marta")
    resp = env.client.patch(f"{ENTITIES}/{marta['id']}", json={"status": "rejected"}, headers=AUTH)
    assert resp.status_code == 200, resp.text
    ids_before = {e["id"] for e in _entities(env)}

    _chat(env, "Tell me more.")

    assert {e["id"] for e in _entities(env)} == ids_before
    assert not [e for e in _entities(env, status="pending") if e["name"] == "Old Marta"]
    assert _named(env, "Old Marta", status="rejected")["id"] == marta["id"]

    resp = env.client.delete(f"{ENTITIES}/{marta['id']}", headers=AUTH)
    assert resp.status_code == 204, resp.text
    assert marta["id"] not in {e["id"] for e in _entities(env)}

    _chat(env, "Anything else?")
    third_reply_id = _last_reply_id(env)
    reproposed = _named(env, "Old Marta")
    assert reproposed["id"] != marta["id"]
    assert reproposed["evidence"]["source_message_id"] == third_reply_id
