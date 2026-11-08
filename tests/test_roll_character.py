from copy import deepcopy

import pytest

from app.intelligence.character_mods import NO_CHARACTER
from app.intelligence.tools import ToolError
from app.intelligence.tools import roll as roll_tool
from app.intelligence.tools.roll import HELP, evaluate, run

INVALID = "Invalid dice expression. Usage: /roll [NdM[kh|klK]][+/-...] (e.g. 2d6+3, adv)"

ARIA = {
    "name": "ARIA",
    "abilities": {"STR": 12, "DEX": 16, "CON": 13, "INT": 11, "WIS": 15, "CHA": 10},
}


class ScriptedRng:
    """Scripted random source: randint(1, sides) pops the next scripted value."""

    def __init__(self, values):
        self._values = list(values)
        self.calls = []

    def randint(self, a, b):
        assert a == 1
        self.calls.append((a, b))
        return self._values.pop(0)


class StubStore:
    """Read-only stand-in: get_character returns a copy and records the session ids."""

    def __init__(self, character):
        self._character = character
        self.calls = []

    def get_character(self, session_id):
        self.calls.append(session_id)
        if self._character is None:
            return None
        return deepcopy(self._character)


class ExplodingStore:
    def get_character(self, session_id):
        raise AssertionError("store must not be read")


def _ctx(rng, store=None):
    context = {"rng": rng, "session_id": "s1"}
    if store is not None:
        context["store"] = store
    return context


def _with_str(score):
    character = deepcopy(ARIA)
    character["abilities"]["STR"] = score
    return character


def test_dex_term_adds_modifier_and_meta():
    store = StubStore(ARIA)
    result = run("1d20+dex", _ctx(ScriptedRng([14]), store))

    assert result["text"] == "1d20+dex: [14] + DEX(+3) = 17"
    assert result["meta"]["total"] == 17
    assert result["meta"]["terms"][1] == {"sign": "+", "ability": "DEX", "modifier": 3, "value": 3}
    assert store.calls == ["s1"]


def test_advantage_plus_str_and_uppercase_dex():
    result = run("adv+str", _ctx(ScriptedRng([7, 15]), StubStore(ARIA)))
    assert result["meta"]["total"] == 16

    result = run("1D20+DEX", _ctx(ScriptedRng([14]), StubStore(ARIA)))
    assert result["meta"]["expression"] == "1d20+dex"
    assert result["meta"]["total"] == 17


def test_negative_modifier_and_minus_sign_inverts():
    store = StubStore(_with_str(8))

    result = run("1d20+str", _ctx(ScriptedRng([10]), store))
    assert result["meta"]["total"] == 9
    assert "+ STR(-1)" in result["text"]

    result = run("1d20-str", _ctx(ScriptedRng([10]), store))
    assert result["meta"]["total"] == 11


def test_bare_ability_word_becomes_d20_plus_ability():
    store = StubStore(ARIA)
    result = run("dex", _ctx(ScriptedRng([10]), store))
    assert result["meta"]["expression"] == "1d20+dex"
    assert result["meta"]["total"] == 13

    result = run("  DEX ", _ctx(ScriptedRng([10]), store))
    assert result["meta"]["expression"] == "1d20+dex"


def test_bare_constant_stays_constant_and_needs_no_character():
    rng = ScriptedRng([])
    result = run("5", {"rng": rng})
    assert result["meta"]["total"] == 5
    assert rng.calls == []


@pytest.mark.parametrize("expr", ["1d20+dex", "dex"])
def test_missing_character_raises_before_any_roll(expr):
    rng = ScriptedRng([10])
    with pytest.raises(ToolError) as excinfo:
        run(expr, _ctx(rng, StubStore(None)))
    assert str(excinfo.value).startswith("No character")
    assert str(excinfo.value) == NO_CHARACTER
    assert rng.calls == []

    rng = ScriptedRng([10])
    with pytest.raises(ToolError, match="^No character"):
        run(expr, {"rng": rng, "session_id": "s1"})
    assert rng.calls == []


def test_expression_without_abilities_never_reads_store():
    result = run("2d6+3", _ctx(ScriptedRng([3, 4]), ExplodingStore()))
    assert result["text"] == "2d6+3: [3, 4] + 3 = 10"

    result = run("2d6+3", {"rng": ScriptedRng([3, 4])})
    assert result["meta"]["total"] == 10


@pytest.mark.parametrize("expr", ["1d20+foo", "1d20+strx", "foo", "dexx"])
def test_invalid_ability_expressions_raise_before_store_or_rng(expr):
    rng = ScriptedRng([10])
    store = StubStore(None)
    with pytest.raises(ToolError) as excinfo:
        run(expr, _ctx(rng, store))
    assert str(excinfo.value) == INVALID
    assert rng.calls == []
    assert store.calls == []


def test_ability_terms_count_toward_max_terms():
    rng = ScriptedRng([])
    store = StubStore(ARIA)
    with pytest.raises(ToolError) as excinfo:
        run("+".join(["dex"] * 11), _ctx(rng, store))
    assert str(excinfo.value) == "At most 10 terms"
    assert rng.calls == []
    assert store.calls == []


def test_store_sees_only_session_lookup_and_character_is_unchanged():
    store = StubStore(ARIA)
    snapshot = deepcopy(ARIA)
    run("2d20kh1+dex+str", _ctx(ScriptedRng([4, 9]), store))
    assert store.calls == ["s1"]
    assert store._character == snapshot


def test_help_returns_usage_without_rng_or_store():
    rng = ScriptedRng([])
    store = StubStore(ARIA)
    for args in ("help", " HELP "):
        result = run(args, _ctx(rng, store))
        assert result == {"text": HELP, "meta": {"tool": "roll", "help": True}}

    assert "dex" in HELP
    assert "adv" in HELP
    assert rng.calls == []
    assert store.calls == []

    result = run("help", {"rng": rng, "store": ExplodingStore()})
    assert result["text"] == HELP


def test_blank_args_still_roll_d20_with_character_context():
    result = run("  ", _ctx(ScriptedRng([9]), ExplodingStore()))
    assert result["text"] == "1d20: [9] = 9"


def test_evaluate_two_argument_form_and_explicit_mods():
    assert evaluate("1d20", ScriptedRng([12]))["meta"]["total"] == 12

    result = evaluate("1d20+dex", ScriptedRng([14]), {"DEX": 3})
    assert result["text"] == "1d20+dex: [14] + DEX(+3) = 17"

    with pytest.raises(ToolError, match="^No character"):
        evaluate("1d20+dex", ScriptedRng([14]))


def test_roll_module_still_exposes_name():
    assert roll_tool.NAME == "roll"
