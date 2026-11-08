"""Worker runs mention detection after the reply is stored (SPEC-0019 WP-5, REQ-0028, PAT-ARCH-012).

No network and no Ollama: `client.chat` is a stub returning the text in `reply_text["v"]`.
Log assertions read `caplog.records` attributes (the JSON formatter drops extras).
"""

import asyncio
import logging

import pytest

from app.config import OllamaSettings, Settings, WorldSettings
from app.services import inference_service
from app.services.build_services import build_services
from app.services.inference_service import OllamaInferenceService
from app.services.messages import correct_message, find_reply, regenerate_reply, submit_user_message
from app.services.repos import SqliteSessionStore
from tests.session_helpers import make_stub_service, wait_idle

LOGGER = "app.services.inference_service"
F1 = (
    "You push open the door of the Rusty Anchor and the noise of the tavern washes over you. "
    'Behind the bar, Old Marta polishes a mug and nods. "Aria, you came back," she says. '
    '"Captain Harl was asking after you."\n'
    "Harl sits in the corner with two sailors from Brightwater. He raises a hand and Marta "
    'whispers, "Careful. The Captain owes money to half of Brightwater." '
    "Veyra's name is not spoken here."
)
F1_NAMES = {"Rusty Anchor", "Old Marta", "Captain Harl"}


class ToolStub:
    """Stand-in ToolService: every slash command returns the same text."""

    def __init__(self, text: str):
        self.text = text

    def invoke(self, name, args, ctx):
        return {"text": self.text, "meta": {}}


class ListEntitiesFails:
    """World store whose reads fail; every other attribute is the real store's."""

    def __init__(self, store):
        self._store = store

    def list_entities(self, *args, **kwargs):
        raise RuntimeError("store down")

    def __getattr__(self, name):
        return getattr(self._store, name)


@pytest.fixture
def reply_text():
    return {"v": F1}


@pytest.fixture
def world(session_store):
    """Session s1 with a canon Brightwater, so F1 proposes exactly the three F1 names."""
    session_store.create_session("s1")
    session_store.create_entity(name="Brightwater", status="canon")
    return session_store


@pytest.fixture
def make_svc(reply_text):
    services = []

    def _make(world_store=None, **kwargs):
        svc = make_stub_service(world_store=world_store, **kwargs)
        svc.client.chat = lambda messages, **kw: reply_text["v"]
        services.append(svc)
        return svc

    yield _make
    for svc in services:
        asyncio.run(svc.shutdown())


def _turn(svc, store, content: str) -> dict:
    message, created, queued = submit_user_message(
        store=store, inference=svc, session_id="s1", payload={"content": content}
    )
    assert created and queued
    wait_idle(svc)
    return message


def _regenerate(svc, store, reply_id: str) -> None:
    _, queued = regenerate_reply(store=store, inference=svc, session_id="s1", reply_id=reply_id)
    assert queued
    wait_idle(svc)


def _reply(store, user_id: str) -> dict:
    reply = find_reply(store, "s1", user_id)
    assert reply is not None
    return reply


def _pending(store) -> dict:
    return {e["name"]: e for e in store.list_entities("s1", status="pending")}


def _records(caplog, message: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER and r.getMessage() == message]


def test_chat_reply_creates_pending_candidates(world, make_svc, monkeypatch, caplog):
    seen_user_statuses = []
    real_mine_reply = inference_service.mine_reply

    def spy(world_store, **kwargs):
        seen_user_statuses.append(
            [m["status"] for m in world.list_messages("s1") if m["role"] == "user"]
        )
        return real_mine_reply(world_store, **kwargs)

    monkeypatch.setattr(inference_service, "mine_reply", spy)
    caplog.set_level(logging.INFO, logger=LOGGER)
    svc = make_svc(world_store=world)

    user = _turn(svc, world, "Tell me about the tavern.")

    reply = _reply(world, user["id"])
    assert seen_user_statuses == [["completed"]]
    assert world.get_message("s1", user["id"])["status"] == "completed"
    assert reply["status"] == "completed"
    rows = _pending(world)
    assert set(rows) == F1_NAMES
    assert all(row["evidence"]["message_ids"] == [reply["id"]] for row in rows.values())

    [record] = _records(caplog, "world.detected")
    assert record.levelno == logging.INFO
    for field in ("matched", "proposed", "bumped", "duration_ms"):
        assert isinstance(getattr(record, field), int)
    assert (record.matched, record.proposed, record.bumped) == (1, 3, 0)
    assert record.session_id == "s1"
    assert record.message_id == user["id"]
    assert record.reply_id == reply["id"]
    assert not hasattr(record, "snippet")
    assert not any(name in str(vars(record)) for name in F1_NAMES)

    messages = [r.getMessage() for r in caplog.records if r.name == LOGGER]
    assert messages.index("world.detected") > messages.index("job.completed")


def test_tools_other_than_narrate_not_mined(world, make_svc, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    svc = make_svc(world_store=world, tool_service=ToolStub(F1))

    _turn(svc, world, "/roll 1d20")

    assert _pending(world) == {}
    assert _records(caplog, "world.detected") == []

    user = _turn(svc, world, "/narrate the tavern")

    assert _reply(world, user["id"])["meta"]["tool"] == "narrate"
    assert set(_pending(world)) == F1_NAMES
    assert len(_records(caplog, "world.detected")) == 1


def test_skipped_cases(world, make_svc, reply_text, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)

    # No world store: nothing is written, nothing raised.
    svc = make_svc(world_store=None)
    user = _turn(svc, world, "hi")
    assert _reply(world, user["id"])["status"] == "completed"
    assert _pending(world) == {}
    assert _records(caplog, "world.detected") == []
    assert _records(caplog, "world.detect_failed") == []
    assert _records(caplog, "job.failed") == []

    # Switch off.
    svc = make_svc(world_store=world, world=WorldSettings(detect_mentions=False))
    _turn(svc, world, "hi again")
    assert set(_pending(world)) == set()
    assert _records(caplog, "world.detected") == []

    # Non-canon reply: regenerate after the operator marks it non-canon.
    reply_text["v"] = "A quiet reply."
    svc = make_svc(world_store=world)
    user = _turn(svc, world, "third")
    reply = _reply(world, user["id"])
    correct_message(store=world, session_id="s1", message_id=reply["id"], canon=False)
    detected_before = len(_records(caplog, "world.detected"))
    reply_text["v"] = F1
    _regenerate(svc, world, reply["id"])
    assert _reply(world, user["id"])["canon"] is False
    assert _pending(world) == {}
    assert len(_records(caplog, "world.detected")) == detected_before
    assert _records(caplog, "job.failed") == []


def test_detection_failure_is_fail_soft(world, make_svc, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    svc = make_svc(world_store=ListEntitiesFails(world))

    user = _turn(svc, world, "hi")

    assert world.get_message("s1", user["id"])["status"] == "completed"
    reply = _reply(world, user["id"])
    assert reply["status"] == "completed"
    assert reply["content"] == F1
    [failed] = _records(caplog, "world.detect_failed")
    assert failed.levelno == logging.WARNING
    assert failed.session_id == "s1"
    assert failed.message_id == user["id"]
    assert "store down" in failed.error
    assert _records(caplog, "job.failed") == []


def test_regenerate_in_place(world, make_svc, reply_text):
    svc = make_svc(world_store=world)
    user = _turn(svc, world, "hi")
    reply = _reply(world, user["id"])
    before = _pending(world)
    assert set(before) == F1_NAMES
    ids_before = {row["id"] for row in before.values()}

    _regenerate(svc, world, reply["id"])

    after = _pending(world)
    assert {row["id"] for row in after.values()} == ids_before
    assert all(row["evidence"]["message_ids"] == [reply["id"]] for row in after.values())

    reply_text["v"] = F1 + " She fears Mirelle."
    _regenerate(svc, world, reply["id"])

    final = _pending(world)
    assert set(final) == F1_NAMES | {"Mirelle"}
    assert final["Mirelle"]["evidence"]["message_ids"] == [reply["id"]]
    assert len(world.list_messages("s1")) == 2


def test_character_and_catalog_names_not_proposed(reply_text):
    store = SqliteSessionStore(":memory:")
    store.create_session("s1", character={"name": "Aria"})
    store.create_entity(name="Brightwater", status="canon")
    reply_text["v"] = F1 + " Marta fears Aria and the Goblin."
    # make_stub_service has no mention_stoplist parameter, so build the service directly.
    settings = Settings(
        ollama=OllamaSettings(base_url="http://127.0.0.1:1", model="stub", timeout_seconds=1.0)
    )
    svc = OllamaInferenceService(settings, world_store=store, mention_stoplist=["Goblin"])
    svc.client.chat = lambda messages, **kw: reply_text["v"]
    try:
        user = _turn(svc, store, "hi")

        assert _reply(store, user["id"])["status"] == "completed"
        pending = set(_pending(store))
        assert "Aria" not in pending
        assert "Goblin" not in pending
        assert pending == F1_NAMES
    finally:
        asyncio.run(svc.shutdown())
        store.close()


# T-20 (SPEC-0021 WP-3): the mining guard stays {"narrate"} for slash tools plus plain chat.
def test_admin_and_roll_attack_turns_are_not_mined(world, make_svc, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    svc = make_svc(world_store=world, tool_service=ToolStub(F1))

    for content in ("/roll 1d20", "/attack Goblin", "/rules grapple"):
        _turn(svc, world, content)
    assert _pending(world) == {}
    assert _records(caplog, "world.detected") == []

    _turn(svc, world, "Tell me about the tavern.")
    assert set(_pending(world)) == F1_NAMES
    assert len(_records(caplog, "world.detected")) == 1

    _turn(svc, world, "/narrate the tavern")
    assert len(_records(caplog, "world.detected")) == 2


def test_build_services_wires_catalog_stoplist(session_store):
    services = build_services(
        {"session": session_store, "world": session_store}, enable_tool_discovery=False
    )
    inference = services["inference"]
    try:
        species = {s.name for s in services["reference"]["species"]}
        assert species
        assert species <= inference._mention_stoplist
    finally:
        asyncio.run(inference.shutdown())
