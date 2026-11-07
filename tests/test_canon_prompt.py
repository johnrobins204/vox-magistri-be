"""Canon filter in the worker prompt and world selection (SPEC-0016 WP-3; T-23, T-24).

A recording `client.chat` stands in for Ollama. Each test uses a real `:memory:` store.
"""

import asyncio
import copy

import pytest

from app.config import WorldSettings
from app.services.messages import submit_user_message
from tests.session_helpers import make_stub_service, wait_idle


@pytest.fixture
def svc():
    service = make_stub_service()
    yield service
    asyncio.run(service.shutdown())


def _recording_chat(svc, monkeypatch) -> list[list[dict]]:
    calls: list[list[dict]] = []

    def _chat(messages, **kw):
        calls.append(copy.deepcopy(messages))
        return f"reply-{len(calls)}"

    monkeypatch.setattr(svc.client, "chat", _chat)
    return calls


# T-23
def test_worker_prompt_omits_non_canon(svc, session_store, monkeypatch):
    session_store.create_session("s1")
    calls = _recording_chat(svc, monkeypatch)

    submit_user_message(
        store=session_store,
        inference=svc,
        session_id="s1",
        payload={"role": "user", "content": "first question"},
    )
    wait_idle(svc)
    replies = [m for m in session_store.list_messages("s1") if m["role"] == "assistant"]
    assert [m["content"] for m in replies] == ["reply-1"]
    session_store.update_message("s1", replies[0]["id"], canon=False)

    submit_user_message(
        store=session_store,
        inference=svc,
        session_id="s1",
        payload={"role": "user", "content": "second question"},
    )
    wait_idle(svc)

    assert len(calls) == 2
    assert calls[1] == [
        calls[0][0],
        {"role": "user", "content": "first question"},
        {"role": "user", "content": "second question"},
    ]
    assert all("reply-1" not in m["content"] for m in calls[1])


# T-24
def test_world_selection_ignores_non_canon(session_store, monkeypatch):
    session_store.create_session("s1")
    pad = "x" * 120
    # Zorblax is the most recently updated entity and fits only one slot with Mira: it would win
    # the tie on score 3 if the non-canon mention counted.
    session_store.create_entity(name="Mira", kind="npc", notes=pad, status="canon")
    session_store.create_entity(name="Zorblax", kind="place", notes=pad, status="canon")
    svc = make_stub_service(world_store=session_store, world=WorldSettings(entity_budget_chars=200))
    calls = _recording_chat(svc, monkeypatch)
    try:
        session_store.create_message(
            "s1", "u0", {"role": "user", "content": "tell me about Zorblax"}, status="completed"
        )
        session_store.update_message("s1", "u0", canon=False)
        session_store.create_message(
            "s1", "u1", {"role": "user", "content": "where is Mira"}, status="running"
        )

        svc.enqueue(session_id="s1", message_id="u1", prompt="where is Mira", store=session_store)
        wait_idle(svc)

        system = calls[0][0]["content"]
        assert "Mira" in system
        assert "Zorblax" not in system
    finally:
        asyncio.run(svc.shutdown())
