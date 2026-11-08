"""Narrator prompt injection of canon world entities (SPEC-0015 WP-6; T-35..T-40, T-42).

A recording `client.chat` stands in for Ollama. Each test uses a real `:memory:` store.
"""

import asyncio
import copy
import logging

import pytest

from app.config import Settings, WorldSettings
from app.intelligence.prompt_builders import (
    build_character_section,
    build_sidechat_system_prompt,
    build_world_section,
    load_voice_configs,
)
from app.services.build_services import build_services
from app.services.repos import SqliteSessionStore, make_default_repos
from app.services.tool_service import ToolService
from tests.session_helpers import make_stub_service, wait_idle

ARIA = {
    "id": "hero-1",
    "name": "Aria",
    "lineage": "Wood Elf",
    "species_id": "elf",
    "char_class": "Ranger",
    "level": 3,
    "hp_current": 24,
    "hp_max": 28,
    "ac": 14,
    "abilities": {"STR": 12, "DEX": 16, "CON": 13, "INT": 11, "WIS": 15, "CHA": 10},
    "conditions": ["Blessed"],
}


def _baseline_system() -> str:
    return build_sidechat_system_prompt(load_voice_configs())


def _character_section() -> str:
    return build_character_section(ARIA, None, None, max_field_len=Settings().app.max_field_len)


def _line(entity) -> str:
    # The single entity line inside a one-entity world section (header and footer excluded).
    return build_world_section([entity]).splitlines()[1]


def _recording_chat(svc, monkeypatch) -> list[list[dict]]:
    calls: list[list[dict]] = []

    def _chat(messages, **kw):
        calls.append(copy.deepcopy(messages))
        return f"reply-{len(calls)}"

    monkeypatch.setattr(svc.client, "chat", _chat)
    return calls


class _SpyWorldStore(SqliteSessionStore):
    def __init__(self, path):
        super().__init__(path)
        self.list_calls = 0

    def list_entities(self, *args, **kwargs):
        self.list_calls += 1
        return super().list_entities(*args, **kwargs)


class _RaisingWorldStore(SqliteSessionStore):
    def list_entities(self, *args, **kwargs):
        raise RuntimeError("world store unavailable")


@pytest.fixture
def make_svc():
    services = []

    def _make(**settings_kwargs):
        svc = make_stub_service(**settings_kwargs)
        services.append(svc)
        return svc

    yield _make
    for svc in services:
        asyncio.run(svc.shutdown())


# T-35
def test_canon_injected_after_character(make_svc, session_store, monkeypatch):
    session_store.create_session("s1", character=ARIA)
    session_store.create_message("s1", "u1", {"role": "user", "content": "hello"})
    canon = session_store.create_entity(
        name="Brightwater", kind="place", notes="A canal city", status="canon"
    )
    session_store.create_entity(name="Ashfall", kind="place", notes="x", status="pending")
    session_store.create_entity(name="Veyra", kind="person", notes="y", status="rejected")
    svc = make_svc(world_store=session_store, world=WorldSettings(entity_budget_chars=1500))
    calls = _recording_chat(svc, monkeypatch)

    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=session_store)
    wait_idle(svc)

    system = calls[0][0]["content"]
    world = build_world_section([canon])
    assert system == _baseline_system() + "\n\n" + _character_section() + "\n\n" + world
    assert system.endswith(world)
    assert "Ashfall" not in system
    assert "Veyra" not in system


# T-36
def test_scope(make_svc, session_store, monkeypatch):
    session_store.create_session("s1")
    session_store.create_session("s2")
    session_store.create_message("s1", "u1", {"role": "user", "content": "hello"})
    session_store.create_entity(name="GlobalKeep", notes="shared")
    session_store.create_entity(name="MineHall", notes="here", session_id="s1")
    session_store.create_entity(name="TheirTower", notes="there", session_id="s2")
    svc = make_svc(world_store=session_store, world=WorldSettings(entity_budget_chars=1500))
    calls = _recording_chat(svc, monkeypatch)

    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=session_store)
    wait_idle(svc)

    system = calls[0][0]["content"]
    assert "GlobalKeep" in system
    assert "MineHall" in system
    assert "TheirTower" not in system


# T-37
def test_budget_zero_skips(make_svc, monkeypatch):
    store = _SpyWorldStore(":memory:")
    ts = ToolService(discover_on_init=True, default_context={})
    svc = make_svc(
        tool_service=ts,
        world_store=store,
        world=WorldSettings(entity_budget_chars=0, detect_mentions=False),
    )
    ts.default_context["inference"] = svc
    calls = _recording_chat(svc, monkeypatch)
    try:
        store.create_session("s1")
        store.create_entity(name="Brightwater", notes="A canal city")
        store.create_message("s1", "chat", {"role": "user", "content": "hello"})
        store.create_message("s1", "slash", {"role": "user", "content": "/roll 1d4"})

        svc.enqueue(session_id="s1", message_id="chat", prompt="hello", store=store)
        wait_idle(svc)
        assert calls[0][0]["content"] == _baseline_system()
        assert store.list_calls == 0

        svc.enqueue(session_id="s1", message_id="slash", prompt="/roll 1d4", store=store)
        wait_idle(svc)
        assert store.list_calls == 0
        assert len(calls) == 1
    finally:
        store.close()


# T-38
def test_recent_turns_drive_selection(make_svc, session_store, monkeypatch):
    # Equal-length lines so the budget that fits exactly one entity fits either one.
    session_store.create_session("s1")
    session_store.create_message(
        "s1", "old-user", {"role": "user", "content": "Tell me about Corvin"}, status="completed"
    )
    session_store.create_message(
        "s1", "old-asst", {"role": "assistant", "content": "Corvin is ready."}, status="completed"
    )
    corvin = session_store.create_entity(name="Corvin", kind="person", notes="Keeper of the ash")
    dorian = session_store.create_entity(name="Dorian", kind="person", notes="Keeper of the ash")
    assert len(_line(corvin)) == len(_line(dorian))
    session_store.create_message("s1", "now", {"role": "user", "content": "What happens next?"})
    budget = len(_line(corvin)) + 1
    svc = make_svc(world_store=session_store, world=WorldSettings(entity_budget_chars=budget))
    calls = _recording_chat(svc, monkeypatch)

    svc.enqueue(session_id="s1", message_id="now", prompt="What happens next?", store=session_store)
    wait_idle(svc)

    system = calls[0][0]["content"]
    assert system == _baseline_system() + "\n\n" + build_world_section([corvin])
    assert "Dorian" not in system


# T-39
def test_fail_soft_and_none(make_svc, monkeypatch, caplog):
    store = _RaisingWorldStore(":memory:")
    try:
        store.create_session("s1")
        store.create_message("s1", "u1", {"role": "user", "content": "hello"})
        svc = make_svc(world_store=None, world=WorldSettings(entity_budget_chars=1500))
        calls = _recording_chat(svc, monkeypatch)
        svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
        wait_idle(svc)
        assert calls[0][0]["content"] == _baseline_system()
        assert store.get_message("s1", "u1")["status"] == "completed"

        svc_raising = make_svc(world_store=store, world=WorldSettings(entity_budget_chars=1500))
        calls_raising = _recording_chat(svc_raising, monkeypatch)
        with caplog.at_level(logging.WARNING):
            svc_raising.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)
            wait_idle(svc_raising)
        assert calls_raising[0][0]["content"] == _baseline_system()
        assert store.get_message("s1", "u1")["status"] == "completed"
        warned = [r for r in caplog.records if r.getMessage() == "world.unavailable"]
        assert len(warned) == 1
        assert warned[0].levelno == logging.WARNING
    finally:
        store.close()


# T-40
def test_log_counts_only(make_svc, session_store, monkeypatch, caplog):
    sentinel = "SENTINEL-w0rld"
    session_store.create_session("s1")
    session_store.create_message("s1", "u1", {"role": "user", "content": "hello"})
    session_store.create_entity(name=sentinel, notes=sentinel, status="canon")
    session_store.create_entity(name="Ashfall", notes=sentinel, status="pending")
    svc = make_svc(world_store=session_store, world=WorldSettings(entity_budget_chars=1500))
    calls = _recording_chat(svc, monkeypatch)

    with caplog.at_level(logging.INFO):
        svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=session_store)
        wait_idle(svc)

    assert sentinel in calls[0][0]["content"]
    injected = [r for r in caplog.records if r.getMessage() == "world.injected"]
    assert len(injected) == 1
    assert isinstance(injected[0].candidates, int)
    assert isinstance(injected[0].selected, int)
    assert injected[0].candidates == 2
    assert injected[0].selected == 1
    for record in caplog.records:
        assert sentinel not in record.getMessage()
        assert "Ashfall" not in record.getMessage()
        assert sentinel not in str(record.__dict__)
        assert "Ashfall" not in str(record.__dict__)


# T-42
def test_build_services_wires_world():
    services = build_services(make_default_repos(), enable_tool_discovery=False)
    inference = services["inference"]
    try:
        assert inference._world_store is services["world"]
    finally:
        asyncio.run(inference.shutdown())
