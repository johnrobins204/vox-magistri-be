import copy
from pathlib import Path

import pytest

from app.intelligence import character_mods as cm
from app.intelligence.character_mods import (
    ABILITIES,
    NO_CHARACTER,
    ability_modifier,
    ability_modifiers,
    require_character,
    weapon_ability,
)
from app.intelligence.tools import ToolError

ARIA = {
    "id": "c1",
    "name": "ARIA",
    "abilities": {"STR": 12, "DEX": 16, "CON": 13, "INT": 11, "WIS": 15, "CHA": 10},
}
ARIA_MODS = {"STR": 1, "DEX": 3, "CON": 1, "INT": 0, "WIS": 2, "CHA": 0}


class StubStore:
    """Read-only store stub: get_character returns a copy and records calls; no writes exist."""

    def __init__(self, character):
        self._character = character
        self.calls = []

    def get_character(self, session_id):
        self.calls.append(session_id)
        if self._character is KeyError:
            raise KeyError(session_id)
        if self._character is None:
            return None
        return copy.deepcopy(self._character)


def _context(store, session_id="s1", **extra):
    ctx = {"rng": None, "store": store, "session_id": session_id}
    ctx.update(extra)
    return ctx


# T-1.1
@pytest.mark.parametrize(
    "score, expected",
    [(1, -5), (8, -1), (9, -1), (10, 0), (11, 0), (12, 1), (20, 5), (30, 10)],
)
def test_ability_modifier_floor_formula(score, expected):
    assert ability_modifier(score) == expected


def test_abilities_tuple_order():
    assert ABILITIES == ("STR", "DEX", "CON", "INT", "WIS", "CHA")


# T-1.2
def test_ability_modifiers_for_sample_character():
    assert ability_modifiers(ARIA) == ARIA_MODS


def test_ability_modifiers_without_abilities_is_empty():
    assert ability_modifiers({"id": "c2", "name": "Nobody"}) == {}


def test_ability_modifiers_skips_non_int_and_bool_scores():
    character = {"abilities": {"STR": "12", "DEX": True, "CON": 13.0, "INT": None, "WIS": 15}}
    assert ability_modifiers(character) == {"WIS": 2}


def test_ability_modifiers_only_present_keys():
    assert ability_modifiers({"abilities": {"STR": 14}}) == {"STR": 2}


# T-1.3
def test_finesse_picks_higher_of_str_or_dex_dex_wins():
    mods = {"STR": 1, "DEX": 3}
    assert weapon_ability(["Finesse", "Light"], mods) == ("DEX", 3)


def test_finesse_picks_str_when_higher():
    mods = {"STR": 4, "DEX": 0}
    assert weapon_ability(["Finesse", "Light"], mods) == ("STR", 4)


def test_finesse_tie_goes_to_str():
    mods = {"STR": 2, "DEX": 2}
    assert weapon_ability(["Finesse"], mods) == ("STR", 2)


def test_property_match_is_case_insensitive():
    mods = {"STR": 1, "DEX": 3}
    assert weapon_ability(["finesse"], mods) == ("DEX", 3)
    assert weapon_ability(["FINESSE"], mods) == ("DEX", 3)


# T-1.4
def test_ammunition_and_loading_use_dex_even_when_str_higher():
    mods = {"STR": 4, "DEX": 1}
    assert weapon_ability(["Ammunition", "Loading"], mods) == ("DEX", 1)


def test_finesse_and_ammunition_follow_finesse_rule():
    mods = {"STR": 4, "DEX": 1}
    assert weapon_ability(["Finesse", "Ammunition"], mods) == ("STR", 4)
    mods = {"STR": 0, "DEX": 3}
    assert weapon_ability(["Finesse", "Ammunition"], mods) == ("DEX", 3)


@pytest.mark.parametrize("properties", [["Thrown"], ["Versatile"], []])
def test_other_weapons_use_str(properties):
    mods = {"STR": 1, "DEX": 3}
    assert weapon_ability(properties, mods) == ("STR", 1)


def test_missing_key_counts_as_zero():
    assert weapon_ability(["Finesse"], {"DEX": 2}) == ("DEX", 2)
    assert weapon_ability(["Finesse"], {"STR": 1}) == ("STR", 1)
    assert weapon_ability(["Finesse"], {"STR": -1}) == ("DEX", 0)
    assert weapon_ability(["Finesse"], {}) == ("STR", 0)


# T-1.5
def test_require_character_returns_dict():
    store = StubStore(ARIA)
    assert require_character(_context(store)) == ARIA
    assert store.calls == ["s1"]


@pytest.mark.parametrize(
    "context",
    [
        _context(StubStore(None)),
        _context(StubStore(KeyError)),
        {"rng": None, "session_id": "s1"},
        {"rng": None, "store": StubStore(ARIA)},
        {"rng": None, "store": None, "session_id": "s1"},
        {"rng": None, "store": StubStore(ARIA), "session_id": None},
    ],
)
def test_require_character_raises_no_character(context):
    with pytest.raises(ToolError) as exc:
        require_character(context)
    assert str(exc.value).startswith("No character")
    assert str(exc.value) == NO_CHARACTER


def test_no_character_message_text():
    assert NO_CHARACTER == "No character on this session. Create or select a character first."


def test_require_character_does_not_write_or_import_stores():
    source = Path(cm.__file__).read_text(encoding="utf-8")
    for forbidden in ("sqlite3", "repos", "build_services", "get_session_store"):
        assert forbidden not in source


# T-1.6
def test_helpers_do_not_mutate_arguments():
    character = copy.deepcopy(ARIA)
    before = copy.deepcopy(character)
    ability_modifiers(character)
    assert character == before

    mods = {"STR": 1, "DEX": 3}
    mods_before = copy.deepcopy(mods)
    props = ["Finesse", "Light"]
    props_before = copy.deepcopy(props)
    weapon_ability(props, mods)
    assert mods == mods_before
    assert props == props_before
