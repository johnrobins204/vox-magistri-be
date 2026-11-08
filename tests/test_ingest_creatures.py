"""SPEC-0018 WP-1: creatures projection, measurement and size rule (script only).

T-1..T-5: projection keys, scalar mapping, action split, allowlist and ids, measurement.
Fixtures are small and built inline under tmp_path. No network, no dnd_data/.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ingest_open5e.py"

_spec = importlib.util.spec_from_file_location("ingest_open5e", SCRIPT)
ingest_open5e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingest_open5e)

SRD_2014 = "srd-2014"
SRD_2024 = "srd-2024"
CC_BY = [{"name": "Creative Commons Attribution 4.0", "key": "cc-by-40"}]
DROPPED_UPSTREAM_KEYS = ["attacks", "crossreferences", "modifiers", "speed_all", "document"]


def _documents() -> dict[str, dict]:
    """Shaped like the records in dnd_data/_documents.json."""

    def doc(key: str, display: str, publisher: str) -> dict:
        return {
            "key": key,
            "name": display,
            "display_name": display,
            "publisher": {"name": publisher, "key": publisher.lower().replace(" ", "-")},
            "permalink": f"https://example.invalid/{key}",
            "licenses": CC_BY,
        }

    return {
        SRD_2014: doc(SRD_2014, "SRD 5.1 (2014)", "Wizards of the Coast"),
        SRD_2024: doc(SRD_2024, "SRD 5.2 (2024)", "Wizards of the Coast"),
        "a5e-mm": doc("a5e-mm", "Monstrous Menagerie", "EN Publishing"),
    }


def _action(name, action_type, order, usage=None, cost=None):
    """A raw open5e action item; `legendary_action_cost` is set independently of action_type."""
    return {
        "name": name,
        "desc": f"{name} desc.",
        "crossreferences": {"to": []},
        "attacks": [],
        "action_type": action_type,
        "order_in_statblock": order,
        "legendary_action_cost": cost,
        "limited_to_form": None,
        "usage_limits": usage,
    }


def _raw_creature(name, document_key, **over):
    """An upstream-shaped creature. Includes the droppable keys speed_all and proficiency_bonus."""
    slug = name.lower().replace(" ", "-")
    raw = {
        "key": f"{document_key}_{slug}",
        "name": name,
        "document": _documents()[document_key],
        "type": {"name": "Humanoid", "key": "humanoid"},
        "size": {"name": "Small", "key": "small"},
        "challenge_rating": 0.25,
        "proficiency_bonus": None,
        "alignment": "neutral evil",
        "armor_class": 15,
        "armor_detail": "leather armor, shield",
        "hit_points": 7,
        "hit_dice": "2d6",
        "speed": {"walk": 30, "unit": "feet", "hover": False},
        "speed_all": {"unit": "feet", "walk": 30, "hover": False},
        "ability_scores": {
            "strength": 8,
            "dexterity": 14,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 8,
            "charisma": 8,
        },
        "modifiers": {"strength": -1, "dexterity": 2},
        "saving_throws": {"dexterity": 4},
        "skill_bonuses": {"stealth": 4},
        "resistances_and_immunities": {
            "damage_vulnerabilities_display": "",
            "damage_vulnerabilities": [],
            "damage_resistances_display": "",
            "damage_resistances": [],
            "damage_immunities_display": "",
            "damage_immunities": [],
            "condition_immunities_display": "",
            "condition_immunities": [],
        },
        "blindsight_range": None,
        "darkvision_range": 60,
        "tremorsense_range": None,
        "truesight_range": None,
        "passive_perception": 9,
        "languages": {"as_string": "Common, Goblin", "data": []},
        "experience_points": 50,
        "traits": [{"name": "Nimble Escape", "desc": "Can Disengage or Hide as a bonus action."}],
        "actions": [_action("Scimitar", "ACTION", 1)],
        "crossreferences": {"to": []},
    }
    raw.update(over)
    return raw


def _goblin(document_key):
    return _raw_creature("Goblin", document_key)


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest_open5e, "OVERLAY_DIR", tmp_path / "no-overlays")
    monkeypatch.setattr(ingest_open5e, "OGL_LICENSE_SOURCE", tmp_path / "licenses" / "OGL.txt")


def _project_one(raw):
    records = ingest_open5e.build_records("creatures", [raw])
    assert len(records) == 1
    return records[0]


# T-1
def test_t1_records_have_exactly_the_projection_keys():
    records = ingest_open5e.build_records(
        "creatures", [_goblin(SRD_2024), _goblin(SRD_2014), _raw_creature("Ogre", SRD_2024)]
    )

    assert len(records) == 3
    for record in records:
        assert set(record) == set(ingest_open5e.PROJECTION["creatures"])


# T-1
def test_t1_dropped_upstream_keys_appear_nowhere():
    raw = _goblin(SRD_2024)
    assert all(key in raw for key in ["speed_all", "proficiency_bonus", "modifiers"])

    records = ingest_open5e.build_records("creatures", [raw])
    dumped = json.dumps(records)

    for key in DROPPED_UPSTREAM_KEYS:
        assert f'"{key}"' not in dumped
    assert "proficiency_bonus" not in dumped


# T-2
def test_t2_size_type_edition_and_names():
    srd24 = _project_one(_goblin(SRD_2024))
    srd14 = _project_one(_goblin(SRD_2014))

    assert srd24["size"] == "Small"
    assert srd24["type"] == "Humanoid"
    assert srd24["edition"] == "5.5e"
    assert srd14["edition"] == "5e"


# T-2
def test_t2_languages_cr_and_string_fields_default_to_empty():
    record = _project_one(
        _raw_creature("Ghost", SRD_2024, alignment=None, armor_detail=None, hit_dice=None)
    )

    assert record["languages"] == "Common, Goblin"
    assert isinstance(record["cr"], float)
    assert record["cr"] == 0.25
    assert record["alignment"] == ""
    assert record["armor_detail"] == ""
    assert record["hit_dice"] == ""


# T-2
def test_t2_immunity_strings_are_the_display_values():
    resist = {
        "damage_vulnerabilities_display": "fire",
        "damage_vulnerabilities": ["fire"],
        "damage_resistances_display": "cold; bludgeoning from nonmagical attacks",
        "damage_resistances": ["cold"],
        "damage_immunities_display": "poison",
        "damage_immunities": ["poison"],
        "condition_immunities_display": "charmed, frightened",
        "condition_immunities": ["charmed", "frightened"],
    }
    record = _project_one(_raw_creature("Imp", SRD_2024, resistances_and_immunities=resist))

    assert record["damage_vulnerabilities"] == "fire"
    assert record["damage_resistances"] == "cold; bludgeoning from nonmagical attacks"
    assert record["damage_immunities"] == "poison"
    assert record["condition_immunities"] == "charmed, frightened"


# T-2
def test_t2_senses_keep_only_non_null_ranges():
    record = _project_one(
        _raw_creature(
            "Bat", SRD_2024, blindsight_range=None, darkvision_range=60, truesight_range=10
        )
    )

    assert record["senses"] == {"darkvision": 60, "truesight": 10}


# T-2
def test_t2_saving_throws_and_skill_bonuses_drop_nulls():
    record = _project_one(
        _raw_creature(
            "Hound",
            SRD_2024,
            saving_throws={"dexterity": 4, "wisdom": None},
            skill_bonuses={"stealth": None, "perception": 3},
        )
    )

    assert record["saving_throws"] == {"dexterity": 4}
    assert record["skill_bonuses"] == {"perception": 3}


# T-2
def test_t2_speed_keeps_positive_int_movement_only():
    speed = {"walk": 30, "burrow": 0, "climb": 15, "fly": None, "swim": 20, "hover": True}
    record = _project_one(_raw_creature("Eel", SRD_2024, speed=speed))

    assert record["speed"] == {"walk": 30, "climb": 15, "swim": 20}


# T-3
def test_t3_actions_split_by_type_and_sorted_by_statblock_order():
    actions = [
        _action("Bite", "ACTION", 2),
        _action("Claw", "ACTION", 1, usage={"type": "PER_DAY", "param": 3}),
        _action("Breath", "ACTION", 3, usage={"type": "RECHARGE_ON_ROLL", "param": 5}),
        _action("Spit", "ACTION", 4, usage={"type": "RECHARGE", "param": 4}, cost=2),
        _action("Roar", "ACTION", 5, usage={"type": "RECHARGE_ON_ROLL", "param": 6}),
        _action("Hook", "BONUS_ACTION", 1),
        _action("Parry", "REACTION", 1),
        _action("Tail", "LEGENDARY_ACTION", 2, cost=1),
        _action("Wing", "LEGENDARY_ACTION", 1, cost=None),
    ]
    record = _project_one(_raw_creature("Wyrm", SRD_2024, actions=actions))

    def item(name, **extra):
        return {"name": name, "desc": f"{name} desc.", **extra}

    assert record["actions"] == [
        item("Claw", usage="3/Day"),
        item("Bite"),
        item("Breath", usage="Recharge 5-6"),
        item("Spit", usage="Recharge 4"),
        item("Roar", usage="Recharge 6"),
    ]
    assert record["bonus_actions"] == [item("Hook")]
    assert record["reactions"] == [item("Parry")]
    assert record["legendary_actions"] == [item("Wing"), item("Tail", cost=1)]


# T-3
def test_t3_missing_statblock_order_sorts_last():
    actions = [
        _action("Late", "ACTION", None),
        _action("Early", "ACTION", 1),
    ]
    record = _project_one(_raw_creature("Mimic", SRD_2024, actions=actions))

    assert [a["name"] for a in record["actions"]] == ["Early", "Late"]


# T-3
def test_t3_empty_lists_are_emitted_and_traits_keep_raw_order():
    traits = [
        {"name": "Second", "desc": "2"},
        {"name": "First", "desc": "1"},
    ]
    record = _project_one(_raw_creature("Stub", SRD_2024, actions=[], traits=traits))

    assert record["actions"] == []
    assert record["bonus_actions"] == []
    assert record["reactions"] == []
    assert record["legendary_actions"] == []
    assert record["traits"] == [{"name": "Second", "desc": "2"}, {"name": "First", "desc": "1"}]


# T-3
def test_t3_unknown_action_type_raises_naming_it():
    raw = _raw_creature("Odd", SRD_2024, actions=[_action("Weird", "MYSTERY", 1)])

    with pytest.raises(ValueError) as excinfo:
        ingest_open5e.build_records("creatures", [raw])

    assert "MYSTERY" in str(excinfo.value)


# T-4
def test_t4_allowlist_is_srd_only_and_consumer_is_named():
    allowed = ingest_open5e.DOCUMENT_ALLOWLIST["creatures"]

    assert set(allowed) <= {SRD_2014, SRD_2024}
    assert SRD_2024 in allowed
    assert "/monster" in ingest_open5e.CONSUMERS["creatures"]


# T-4
def test_t4_third_party_entries_are_dropped():
    raw = _raw_creature("Aboleth", "a5e-mm")

    assert ingest_open5e.build_records("creatures", [raw]) == []


# T-4
def test_t4_same_name_in_both_srds_gets_bare_and_5e_ids():
    records = ingest_open5e.build_records("creatures", [_goblin(SRD_2014), _goblin(SRD_2024)])
    by_edition = {r["edition"]: r["id"] for r in records}

    assert by_edition == {"5.5e": "goblin", "5e": "goblin-5e"}


# T-5
def test_t5_measure_projection_reports_both_and_single_srd_sizes():
    entries = [_goblin(SRD_2014), _goblin(SRD_2024), _raw_creature("Aboleth", "a5e-mm")]

    result = ingest_open5e.measure_projection("creatures", entries)

    assert set(result) == {"both", SRD_2014, SRD_2024, "fits_both", "allowlist"}
    for key in ("both", SRD_2014, SRD_2024):
        assert set(result[key]) == {"entries", "bytes"}
    assert result["both"]["entries"] == 2
    assert result[SRD_2014]["entries"] == 1
    assert result[SRD_2024]["entries"] == 1

    both_records = ingest_open5e.build_records(
        "creatures", entries, allowlist=ingest_open5e.DEFAULT_DOCUMENTS
    )
    assert result["both"]["bytes"] == len(ingest_open5e.render(both_records).encode())


# T-5
def test_t5_both_srds_allowlist_when_both_fit(monkeypatch):
    entries = [_goblin(SRD_2014), _goblin(SRD_2024)]
    monkeypatch.setattr(ingest_open5e, "MAX_BYTES", 10_000_000)

    result = ingest_open5e.measure_projection("creatures", entries)

    assert result["fits_both"] is True
    assert result["allowlist"] == [SRD_2014, SRD_2024]


# T-5
def test_t5_falls_back_to_srd_2024_between_single_and_both(monkeypatch):
    entries = [_goblin(SRD_2014), _goblin(SRD_2024)]
    unbounded = ingest_open5e.measure_projection("creatures", entries)
    assert unbounded["srd-2024"]["bytes"] < unbounded["both"]["bytes"]
    monkeypatch.setattr(ingest_open5e, "MAX_BYTES", unbounded[SRD_2024]["bytes"])

    result = ingest_open5e.measure_projection("creatures", entries)

    assert result["fits_both"] is False
    assert result["allowlist"] == [SRD_2024]


# T-5
def test_t5_ingest_rerun_is_byte_identical(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    entries = [_goblin(SRD_2014), _goblin(SRD_2024), _raw_creature("Aboleth", "a5e-mm")]
    (snapshot / "creatures.json").write_text(json.dumps(entries), encoding="utf-8")
    (snapshot / "_documents.json").write_text(
        json.dumps(list(_documents().values())), encoding="utf-8"
    )
    out = tmp_path / "reference" / "creatures.json"
    out.parent.mkdir()

    ingest_open5e.ingest("creatures", snapshot, out)
    first = out.read_bytes()
    ingest_open5e.ingest("creatures", snapshot, out)

    assert len(json.loads(first)) == 2
    assert out.read_bytes() == first
