"""SPEC-0018 WP-2: Creature model, CREATURES_PATH and make_creature (T-7, T-8).

Reads no dataset file. The projection key list comes from scripts/ingest_open5e.py.
"""

import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.reference.creatures import CREATURES_PATH, AbilityScores, Creature, StatEntry
from tests.creature_fixtures import make_creature

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ingest_open5e.py"

FULL_ENTRY = {
    "id": "sewer-warden-5e",
    "name": "Sewer Warden",
    "edition": "5e",
    "source": "Test Source",
    "publisher": "Test Publisher",
    "third_party": False,
    "source_key": "test-sewer-warden",
    "size": "Medium",
    "type": "construct",
    "alignment": "unaligned",
    "armor_class": 14,
    "armor_detail": "natural armor",
    "hit_points": 40,
    "hit_dice": "9d8",
    "speed": {"walk": 30, "swim": 20},
    "ability_scores": {
        "strength": 14,
        "dexterity": 9,
        "constitution": 16,
        "intelligence": 3,
        "wisdom": 11,
        "charisma": 5,
    },
    "saving_throws": {"constitution": 5},
    "skill_bonuses": {"perception": 2},
    "damage_vulnerabilities": "thunder",
    "damage_resistances": "bludgeoning",
    "damage_immunities": "poison",
    "condition_immunities": "charmed",
    "passive_perception": 12,
    "senses": {"darkvision": 60, "blindsight": 10},
    "languages": "understands Common but cannot speak",
    "cr": 2.0,
    "experience_points": 450,
    "traits": [{"name": "Sewer Sense", "desc": "Knows the way out of any drain."}],
    "actions": [{"name": "Slam", "desc": "Melee attack, one target."}],
    "bonus_actions": [{"name": "Hiss", "desc": "Frightens one listener."}],
    "reactions": [{"name": "Shrug Off", "desc": "Reduces one hit."}],
    "legendary_actions": [
        {
            "name": "Tail Sweep",
            "desc": "Sweeps the tail at adjacent foes.",
            "usage": "Recharge 5-6",
            "cost": 2,
        }
    ],
}

REQUIRED_ONLY = {
    "id": "sewer-warden",
    "name": "Sewer Warden",
    "edition": "5.5e",
    "source": "Test Source",
    "publisher": None,
    "third_party": False,
    "source_key": "test-sewer-warden",
    "cr": 0.25,
}


def _entry(**changes) -> dict:
    """FULL_ENTRY with `changes` applied; a value of None removes the key."""
    entry = {**FULL_ENTRY, **changes}
    return {k: v for k, v in entry.items() if v is not None}


# SPEC-0018 T-7: a full literal entry validates, with typed nested values.
def test_t7_full_literal_entry_validates_with_typed_nested_values():
    creature = Creature(**FULL_ENTRY)

    assert isinstance(creature.ability_scores, AbilityScores)
    assert all(isinstance(entry, StatEntry) for entry in creature.traits)
    assert all(isinstance(entry, StatEntry) for entry in creature.legendary_actions)
    assert creature.legendary_actions[0].cost == 2
    assert creature.actions[0].usage is None


# SPEC-0018 T-7: only the required keys validate; the rest take their defaults.
def test_t7_required_keys_only_validates_with_defaults():
    creature = Creature(**REQUIRED_ONLY)

    assert creature.armor_class is None
    assert creature.hit_points is None
    assert creature.passive_perception is None
    assert creature.experience_points is None
    assert creature.size == ""
    assert creature.hit_dice == ""
    assert creature.speed == {}
    assert creature.senses == {}
    assert creature.saving_throws == {}
    assert creature.skill_bonuses == {}
    assert creature.ability_scores == AbilityScores()
    assert creature.ability_scores.strength == 10
    assert creature.traits == []
    assert creature.actions == []
    assert creature.bonus_actions == []
    assert creature.reactions == []
    assert creature.legendary_actions == []


# SPEC-0018 T-7: make_creature builds the id from the name, with "-5e" only for 5e.
def test_t7_make_creature_ids_follow_edition():
    assert make_creature("Goblin", "5e").id == "goblin-5e"
    assert make_creature("Goblin").id == "goblin"


# SPEC-0018 T-8: unknown keys, bad id, bad edition, or a missing cr are rejected.
@pytest.mark.parametrize(
    "entry",
    [
        _entry(bogus_key="x"),
        _entry(id="Bad Id"),
        _entry(edition="3e"),
        _entry(cr=None),
    ],
    ids=["unknown-key", "bad-id", "bad-edition", "missing-cr"],
)
def test_t8_invalid_entries_raise_validation_error(entry):
    with pytest.raises(ValidationError):
        Creature(**entry)


# SPEC-0018 T-8: the dataset path is app/reference/creatures.json.
def test_t8_creatures_path_is_the_reference_json():
    assert CREATURES_PATH == ROOT / "app" / "reference" / "creatures.json"


# SPEC-0018 WP-2 acceptance: model field names equal the WP-1 projection keys.
def test_model_fields_equal_the_wp1_projection_keys():
    spec = importlib.util.spec_from_file_location("ingest_open5e", SCRIPT)
    ingest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ingest)

    assert list(Creature.model_fields) == list(ingest.PROJECTION["creatures"])
