import json
from enum import StrEnum
from pathlib import Path

import pydantic
import pytest

from app.config import Settings, WorldSettings
from app.type_defs import EntityKind, EntityStatus, WorldStore

ROOT = Path(__file__).resolve().parents[1]


# T-01
def test_entity_vocab():
    assert {m.value for m in EntityKind} == {"npc", "place", "faction", "quest", "item", "other"}
    assert {m.value for m in EntityStatus} == {"canon", "pending", "rejected"}
    assert issubclass(EntityKind, StrEnum)
    assert issubclass(EntityStatus, StrEnum)


# T-02
def test_world_settings_budget():
    assert WorldSettings().entity_budget_chars == 1500
    assert WorldSettings(entity_budget_chars=0).entity_budget_chars == 0
    with pytest.raises(pydantic.ValidationError):
        WorldSettings(entity_budget_chars=-1)
    defaults = WorldSettings()
    assert defaults.enable_world_guidance is True
    assert defaults.default_modes == ["Clarify", "Expand", "Connect", "Challenge"]


# T-03
def test_settings_json_world_budget():
    data = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
    assert data["world"]["entity_budget_chars"] == 1500
    assert Settings(**data).world.entity_budget_chars == 1500
    for name in ("create_entity", "get_entity", "list_entities", "update_entity", "delete_entity"):
        assert hasattr(WorldStore, name)
