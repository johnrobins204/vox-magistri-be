import copy

import pytest

from app.intelligence.tools import ToolError
from app.intelligence.tools import attack as attack_tool
from app.intelligence.tools.attack import HELP, damage_expression, run
from app.intelligence.tools.roll import evaluate
from app.reference.loader import load_entries
from app.reference.weapons import WEAPONS_PATH, Weapon

ARIA = {
    "name": "ARIA",
    "abilities": {"STR": 12, "DEX": 16, "CON": 13, "INT": 11, "WIS": 15, "CHA": 10},
}


class ScriptedRng:
    """Scripted random source: randint(1, sides) pops the next scripted value.

    Records every call so tests can prove that invalid input never reaches the rng.
    """

    def __init__(self, values):
        self._values = list(values)
        self.calls = []

    def randint(self, a, b):
        assert a == 1
        self.calls.append((a, b))
        return self._values.pop(0)


class StubStore:
    """Only get_character exists, so any write fails with AttributeError."""

    def __init__(self, character):
        self._character = character
        self.calls = []

    def get_character(self, session_id):
        self.calls.append(("get_character", session_id))
        if self._character is None:
            return None
        return copy.deepcopy(self._character)


def weapon(name, **overrides):
    fields = {
        "id": name.lower().replace(" ", "-"),
        "name": name,
        "edition": "5e",
        "source": "SRD",
        "publisher": None,
        "third_party": False,
        "source_key": "srd",
        "damage_dice": "1d8",
        "damage_type": "slashing",
        "properties": [],
        "range": 0,
        "long_range": 0,
        "distance_unit": None,
        "is_simple": False,
        "is_improvised": False,
    }
    fields.update(overrides)
    return Weapon(**fields)


LONGSWORD = weapon("Longsword", properties=["Versatile"])


def context(rng, weapons=(LONGSWORD,), character=ARIA):
    return {
        "rng": rng,
        "store": StubStore(character),
        "session_id": "s1",
        "reference": {"weapons": list(weapons)},
    }


def test_longsword_hit_rolls_attack_then_damage():
    rng = ScriptedRng([14, 5])
    result = run("Longsword vs 12", context(rng))
    meta = result["meta"]
    assert meta["tool"] == "attack"
    assert meta["weapon"] == "Longsword"
    assert meta["weapon_id"] == "longsword"
    assert meta["ability"] == "STR"
    assert meta["modifier"] == 1
    assert meta["ac"] == 12
    assert meta["attack_roll"] == 14
    assert meta["attack_total"] == 15
    assert meta["hit"] is True
    assert meta["critical"] is False
    assert meta["damage"] == 6
    assert rng.calls == [(1, 20), (1, 8)]
    assert "Hit!" in result["text"]
    assert "Damage: 1d8+1: [5] + 1 = 6." in result["text"]


def test_miss_rolls_only_the_attack():
    rng = ScriptedRng([3])
    result = run("Longsword vs 15", context(rng))
    assert result["meta"]["hit"] is False
    assert result["meta"]["damage"] is None
    assert rng.calls == [(1, 20)]
    assert "Miss" in result["text"]


def test_total_equal_to_ac_hits():
    rng = ScriptedRng([10, 4])
    result = run("Longsword vs 11", context(rng))
    assert result["meta"]["attack_total"] == 11
    assert result["meta"]["hit"] is True
    assert result["meta"]["damage"] == 5


def test_no_ac_rolls_attack_only_and_says_so():
    rng = ScriptedRng([10])
    result = run("Longsword", context(rng))
    meta = result["meta"]
    assert meta["ac"] is None
    assert meta["hit"] is None
    assert meta["damage"] is None
    assert meta["attack_total"] == 11
    assert rng.calls == [(1, 20)]
    assert "11" in result["text"]
    assert "No AC given" in result["text"]


def test_nat_20_is_critical_hit_and_doubles_dice():
    rng = ScriptedRng([20, 3, 4])
    result = run("Longsword vs 30", context(rng))
    meta = result["meta"]
    assert meta["hit"] is True
    assert meta["critical"] is True
    assert meta["damage"] == 8
    assert meta["attack_total"] == 21
    assert rng.calls == [(1, 20), (1, 8), (1, 8)]
    assert "Critical hit" in result["text"]
    assert "2d8+1" in result["text"]


def test_nat_20_without_ac_still_hits_and_rolls_damage():
    rng = ScriptedRng([20, 3, 4])
    result = run("Longsword", context(rng))
    assert result["meta"]["hit"] is True
    assert result["meta"]["critical"] is True
    assert result["meta"]["damage"] == 8


def test_flat_damage_is_not_doubled_on_crit():
    club = weapon("Sling Stone", damage_dice="1", properties=[])
    rng = ScriptedRng([20])
    result = run("Sling Stone vs 30", context(rng, weapons=[club]))
    assert result["meta"]["critical"] is True
    assert result["meta"]["damage"] == 2
    assert rng.calls == [(1, 20)]


def test_nat_1_always_misses_even_when_total_meets_ac():
    rng = ScriptedRng([1])
    result = run("Longsword vs 2", context(rng))
    assert result["meta"]["attack_total"] == 2
    assert result["meta"]["hit"] is False
    assert result["meta"]["damage"] is None
    assert rng.calls == [(1, 20)]
    assert "Natural 1" in result["text"]


def test_nat_1_without_ac_is_a_miss():
    rng = ScriptedRng([1])
    result = run("Longsword", context(rng))
    assert result["meta"]["hit"] is False
    assert result["meta"]["damage"] is None
    assert rng.calls == [(1, 20)]


def test_ability_heuristic_for_finesse_ammunition_and_strength():
    dagger = weapon("Dagger", properties=["Finesse", "Light", "Thrown"], damage_dice="1d4")
    rng = ScriptedRng([10])
    meta = run("Dagger", context(rng, weapons=[dagger]))["meta"]
    assert (meta["ability"], meta["modifier"]) == ("DEX", 3)

    strong = {**ARIA, "abilities": {**ARIA["abilities"], "STR": 18, "DEX": 10}}
    rng = ScriptedRng([10])
    meta = run("Dagger", context(rng, weapons=[dagger], character=strong))["meta"]
    assert (meta["ability"], meta["modifier"]) == ("STR", 4)

    shortbow = weapon("Shortbow", properties=["Ammunition"], damage_dice="1d6")
    rng = ScriptedRng([10])
    meta = run("Shortbow", context(rng, weapons=[shortbow]))["meta"]
    assert (meta["ability"], meta["modifier"]) == ("DEX", 3)

    warhammer = weapon("Warhammer", properties=["Versatile"], damage_dice="1d8")
    rng = ScriptedRng([10])
    meta = run("Warhammer", context(rng, weapons=[warhammer]))["meta"]
    assert (meta["ability"], meta["modifier"]) == ("STR", 1)


def test_damage_is_floored_at_zero():
    club = weapon("Club", damage_dice="1d4", properties=["Light"])
    weak = {**ARIA, "abilities": {**ARIA["abilities"], "STR": 1}}
    rng = ScriptedRng([15, 1])
    result = run("Club vs 10", context(rng, weapons=[club], character=weak))
    assert result["meta"]["modifier"] == -5
    assert result["meta"]["hit"] is True
    assert result["meta"]["damage"] == 0
    assert rng.calls == [(1, 20), (1, 4)]


def test_parsing_is_forgiving_about_case_and_spacing():
    rng = ScriptedRng([14, 5])
    result = run("  LongSword  VS  15 ", context(rng))
    assert result["meta"]["ac"] == 15
    assert result["meta"]["weapon"] == "Longsword"


@pytest.mark.parametrize("args", ["Longsword vs abc", "Longsword vs 0", "Longsword vs 41"])
def test_bad_ac_is_usage_error_before_any_roll(args):
    rng = ScriptedRng([])
    with pytest.raises(ToolError) as info:
        run(args, context(rng))
    assert HELP in str(info.value)
    assert rng.calls == []


def test_missing_weapon_before_vs_is_usage_error():
    rng = ScriptedRng([])
    with pytest.raises(ToolError) as info:
        run("vs 15", context(rng))
    assert HELP in str(info.value)
    assert rng.calls == []


@pytest.mark.parametrize("args", ["", "   "])
def test_blank_args_raise_help(args):
    rng = ScriptedRng([])
    with pytest.raises(ToolError) as info:
        run(args, context(rng))
    assert str(info.value) == HELP
    assert rng.calls == []


def test_unknown_weapon():
    rng = ScriptedRng([])
    with pytest.raises(ToolError, match="Unknown weapon"):
        run("Blunderbuss vs 10", context(rng))
    assert rng.calls == []


def test_ambiguous_substring_lists_sorted_candidates():
    weapons = [weapon("Shortsword"), weapon("Longsword"), weapon("Greatsword")]
    rng = ScriptedRng([])
    with pytest.raises(ToolError) as info:
        run("sword", context(rng, weapons=weapons))
    message = str(info.value)
    assert message.index("Greatsword") < message.index("Longsword") < message.index("Shortsword")
    assert rng.calls == []


def test_ambiguous_substring_lists_at_most_five_names():
    names = [f"Blade {letter}" for letter in "FEDCBA"]
    weapons = [weapon(name) for name in names]
    rng = ScriptedRng([])
    with pytest.raises(ToolError) as info:
        run("blade", context(rng, weapons=weapons))
    message = str(info.value)
    assert "Blade A" in message and "Blade E" in message
    assert "Blade F" not in message
    assert rng.calls == []


def test_exact_name_beats_substring():
    club = weapon("Club", damage_dice="1d4", properties=["Light"])
    greatclub = weapon("Greatclub", damage_dice="1d8", properties=["Two-Handed"])
    rng = ScriptedRng([10])
    result = run("club", context(rng, weapons=[greatclub, club]))
    assert result["meta"]["weapon"] == "Club"


def test_unique_substring_resolves():
    halberd = weapon("Halberd", damage_dice="1d10", properties=["Heavy"])
    rng = ScriptedRng([10])
    result = run("halber", context(rng, weapons=[halberd, LONGSWORD]))
    assert result["meta"]["weapon"] == "Halberd"


def test_duplicate_name_prefers_5_5e_whatever_the_order():
    old = weapon("Dagger", id="dagger-5e", edition="5e", properties=["Finesse"], damage_dice="1d4")
    new = weapon("Dagger", id="dagger", edition="5.5e", properties=["Finesse"], damage_dice="1d4")
    for order in ([old, new], [new, old]):
        rng = ScriptedRng([10])
        result = run("Dagger", context(rng, weapons=order))
        assert result["meta"]["weapon_id"] == "dagger"


def test_no_character_is_an_error_before_any_roll():
    rng = ScriptedRng([])
    with pytest.raises(ToolError, match="No character"):
        run("Longsword vs 10", context(rng, character=None))
    assert rng.calls == []


@pytest.mark.parametrize("weapons", [[], None])
def test_missing_or_empty_catalog_is_an_error(weapons):
    rng = ScriptedRng([])
    ctx = context(rng)
    ctx["reference"] = {} if weapons is None else {"weapons": weapons}
    with pytest.raises(ToolError, match="catalog"):
        run("Longsword vs 10", ctx)
    assert rng.calls == []


@pytest.mark.parametrize("dice", [None, "d", "1d", "1d8+2", "two", "1d0x"])
def test_bad_damage_dice_is_an_error_before_any_roll(dice):
    broken = weapon("Broken", damage_dice=dice)
    rng = ScriptedRng([])
    with pytest.raises(ToolError):
        run("Broken vs 10", context(rng, weapons=[broken]))
    assert rng.calls == []


def test_no_mutation_and_only_get_character_is_used():
    character = copy.deepcopy(ARIA)
    weapon_before = LONGSWORD.model_dump()
    ctx = context(ScriptedRng([14, 5]), character=character)
    run("Longsword vs 12", ctx)
    assert ctx["store"]._character == ARIA
    assert LONGSWORD.model_dump() == weapon_before
    assert ctx["store"].calls == [("get_character", "s1")]


def test_help_reply_and_tool_name():
    result = run("help", {})
    assert result["text"] == HELP
    for phrase in ("proficiency", "spell", "out of scope", "/attack <weapon> [vs <AC>]"):
        assert phrase in result["text"]
    assert attack_tool.NAME == "attack"


def test_damage_expression_builder():
    assert damage_expression("1d8", 1, False) == "1d8+1"
    assert damage_expression("1d8", 1, True) == "2d8+1"
    assert damage_expression("1d8", 0, True) == "2d8"
    assert damage_expression("d6", -2, False) == "1d6-2"
    assert damage_expression("1", 1, True) == "1+1"
    assert damage_expression("0", -5, False) == "0-5"


def test_real_catalog_damage_expressions_evaluate():
    weapons = load_entries(WEAPONS_PATH, Weapon, "weapons")
    rolled = [w for w in weapons if w.damage_dice is not None]
    assert rolled, "catalog should have weapons with damage dice"

    class MaxRng:
        def randint(self, a, b):
            return b

    for w in rolled:
        for modifier in (-5, 0, 3):
            for critical in (False, True):
                expr = damage_expression(w.damage_dice, modifier, critical)
                result = evaluate(expr, MaxRng())
                assert result["meta"]["expression"] == expr, w.id


def test_real_catalog_attack_runs_end_to_end():
    weapons = load_entries(WEAPONS_PATH, Weapon, "weapons")
    rng = ScriptedRng([10, 3])
    result = run("Longsword vs 5", context(rng, weapons=weapons))
    assert result["meta"]["weapon"] == "Longsword"
    assert result["meta"]["hit"] is True
