"""Worker wiring of the player character (SPEC-0013, WP-5; T-29..T-34).

A recording `client.chat` stands in for Ollama. Each test uses a real `SqliteSessionStore(":memory:")`.
"""

import asyncio
import copy
import logging

import pytest

from app.config import Settings
from app.intelligence.prompt_builders import (
    build_character_section,
    build_system_prompt,
    load_voice_configs,
)
from app.reference.species import load_species
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


def _expected_system() -> str:
    return build_system_prompt(Settings().prompts, load_voice_configs())


def _catalog() -> dict:
    return {s.id: s for s in load_species()}


def _recording_chat(svc, monkeypatch) -> list[list[dict]]:
    calls: list[list[dict]] = []

    def _chat(messages, **kw):
        calls.append(copy.deepcopy(messages))
        return f"reply-{len(calls)}"

    monkeypatch.setattr(svc.client, "chat", _chat)
    return calls


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


# T-29
def test_build_services_loads_reference_before_inference():
    services = build_services(make_default_repos(), enable_tool_discovery=False)
    try:
        inference = services["inference"]
        assert isinstance(inference._species_by_id, dict)
        assert len(inference._species_by_id) == len(services["reference"]["species"]) == 68
        assert "elf" in inference._species_by_id
        assert services["tool"].default_context["reference"] is services["reference"]
        assert set(services) == {"session", "tool", "inference", "reference", "world"}
    finally:
        asyncio.run(inference.shutdown())


# T-30
def test_character_with_known_species_appends_section(make_svc, session_store, monkeypatch):
    svc = make_svc(species=load_species())
    calls = _recording_chat(svc, monkeypatch)
    session_store.create_session("s1", character=ARIA)
    session_store.create_message("s1", "u1", {"role": "user", "content": "hello"})

    svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=session_store)
    wait_idle(svc)

    elf = _catalog()["elf"]
    section = build_character_section(
        ARIA, elf.name, elf.character_creation_implications, max_field_len=240
    )
    assert len(calls) == 1
    assert [m["role"] for m in calls[0]] == ["system", "user"]
    assert calls[0][0]["content"] == _expected_system() + "\n\n" + section


# T-31
def test_unknown_species_degrades_to_name_only(make_svc, session_store, monkeypatch, caplog):
    svc = make_svc(species=load_species())
    calls = _recording_chat(svc, monkeypatch)
    session_store.create_session("s1", character={**ARIA, "species_id": "no-such-species"})
    session_store.create_message("s1", "u1", {"role": "user", "content": "hello"})

    with caplog.at_level(logging.INFO):
        svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=session_store)
        wait_idle(svc)

    section = build_character_section(ARIA, None, None, max_field_len=240)
    system = calls[0][0]["content"]
    assert system == _expected_system() + "\n\n" + section
    assert "Species: Wood Elf" in system
    assert "Species traits:" not in system
    assert session_store.get_message("s1", "u1")["status"] == "completed"
    built = [r for r in caplog.records if r.getMessage() == "prompt.built"]
    assert len(built) == 1
    assert built[0].character is True
    assert built[0].species_resolved is False


# T-32
def test_no_character_keeps_system_message_identical(make_svc, session_store, monkeypatch, caplog):
    svc = make_svc(species=load_species())
    calls = _recording_chat(svc, monkeypatch)
    session_store.create_session("bare")
    session_store.create_message("bare", "u1", {"role": "user", "content": "hello"})
    session_store.create_session("hero", character=ARIA)
    session_store.create_message("hero", "u2", {"role": "user", "content": "hello"})

    with caplog.at_level(logging.INFO):
        svc.enqueue(session_id="bare", message_id="u1", prompt="hello", store=session_store)
        wait_idle(svc)
        svc.enqueue(session_id="hero", message_id="u2", prompt="hello", store=session_store)
        wait_idle(svc)

    assert calls[0][0]["content"] == _expected_system()
    assert calls[1][0]["content"] != _expected_system()
    built = [r for r in caplog.records if r.getMessage() == "prompt.built"]
    assert [(r.character, r.species_resolved) for r in built] == [(False, False), (True, True)]


# T-33
class _SpyStore(SqliteSessionStore):
    def __init__(self, path):
        super().__init__(path)
        self.character_reads = 0

    def get_character(self, session_id):
        self.character_reads += 1
        return super().get_character(session_id)


def test_chat_reads_character_once_and_slash_never(monkeypatch):
    ts = ToolService(discover_on_init=True, default_context={})
    svc = make_stub_service(tool_service=ts, species=load_species())
    ts.default_context["inference"] = svc
    chat_calls = _recording_chat(svc, monkeypatch)
    store = _SpyStore(":memory:")
    try:
        store.create_session("s1", character=ARIA)
        store.create_message("s1", "chat", {"role": "user", "content": "hello"})
        store.create_message("s1", "slash", {"role": "user", "content": "/roll 1d4"})

        svc.enqueue(session_id="s1", message_id="chat", prompt="hello", store=store)
        wait_idle(svc)
        assert store.character_reads == 1

        svc.enqueue(session_id="s1", message_id="slash", prompt="/roll 1d4", store=store)
        wait_idle(svc)
        assert store.character_reads == 1
        assert len(chat_calls) == 1
    finally:
        asyncio.run(svc.shutdown())
        store.close()


# T-34
def test_character_text_never_reaches_logs(make_svc, session_store, monkeypatch, caplog):
    sentinel = "SENTINEL-c0de"
    svc = make_svc(species=load_species())
    calls = _recording_chat(svc, monkeypatch)
    session_store.create_session(
        "s1", character={**ARIA, "name": sentinel, "conditions": [sentinel]}
    )
    session_store.create_message("s1", "u1", {"role": "user", "content": "hello"})

    with caplog.at_level(logging.INFO):
        svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=session_store)
        wait_idle(svc)

    assert sentinel in calls[0][0]["content"]
    for record in caplog.records:
        assert sentinel not in record.getMessage()
        assert sentinel not in str(record.__dict__)
