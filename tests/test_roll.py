import random

import pytest

from app.intelligence.tools import ToolError
from app.intelligence.tools import roll as roll_tool
from app.intelligence.tools.roll import evaluate, run
from app.services.tool_service import ToolService

INVALID = "Invalid dice expression. Usage: /roll [NdM[kh|klK]][+/-...] (e.g. 2d6+3, adv)"
TOO_LONG = "Expression too long (max 64 characters)"


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


def test_empty_args_rolls_one_d20():
    for blank in ("", "   "):
        result = run(blank, {"rng": ScriptedRng([14])})
        assert result["text"] == "1d20: [14] = 14"
        assert result["meta"]["expression"] == "1d20"
        assert result["meta"]["total"] == 14


def test_basic_dice_with_modifier():
    result = run("2d6+3", {"rng": ScriptedRng([3, 4])})
    assert result["text"] == "2d6+3: [3, 4] + 3 = 10"
    assert result["meta"]["total"] == 10

    result = run("1d8 - 2", {"rng": ScriptedRng([5])})
    assert result["text"] == "1d8-2: [5] - 2 = 3"
    assert result["meta"]["total"] == 3

    result = run("5", {"rng": ScriptedRng([])})
    assert result["text"] == "5: 5 = 5"
    assert result["meta"]["total"] == 5


def test_keep_highest_and_lowest():
    result = run("4d6kh3+2", {"rng": ScriptedRng([6, 4, 3, 1])})
    assert result["text"] == "4d6kh3+2: [6, 4, 3, (1)] + 2 = 15"

    result = run("4d6kl3", {"rng": ScriptedRng([6, 4, 3, 1])})
    assert result["text"] == "4d6kl3: [(6), 4, 3, 1] = 8"

    result = run("4d6kh3", {"rng": ScriptedRng([3, 6, 1, 4])})
    assert result["text"] == "4d6kh3: [3, 6, (1), 4] = 13"

    # Ties keep the earliest index.
    result = run("3d6kh1", {"rng": ScriptedRng([5, 5, 2])})
    assert result["text"] == "3d6kh1: [5, (5), (2)] = 5"

    term = run("4d6kh3+2", {"rng": ScriptedRng([6, 4, 3, 1])})["meta"]["terms"][0]
    assert term["rolls"] == [6, 4, 3, 1]
    assert term["kept"] == [6, 4, 3]
    assert term["keep"] == 3
    assert term["value"] == 13


def test_advantage_and_disadvantage():
    result = run("adv", {"rng": ScriptedRng([7, 15])})
    assert result["text"] == "adv: [(7), 15] = 15"
    term = result["meta"]["terms"][0]
    assert term["count"] == 2
    assert term["sides"] == 20
    assert term["keep"] == 1

    result = run("dis", {"rng": ScriptedRng([7, 15])})
    assert result["text"] == "dis: [7, (15)] = 7"

    result = run("adv+5", {"rng": ScriptedRng([7, 15])})
    assert result["text"] == "adv+5: [(7), 15] + 5 = 20"
    assert result["meta"]["total"] == 20


def test_case_insensitive_and_whitespace():
    result = run("  2D6 + 1d4 - 1 ", {"rng": ScriptedRng([3, 4, 2])})
    assert result["meta"]["expression"] == "2d6+1d4-1"
    assert result["text"].startswith("2d6+1d4-1: ")
    assert result["meta"]["total"] == 3 + 4 + 2 - 1 == 8

    result = run("4D6KH3", {"rng": ScriptedRng([6, 4, 3, 1])})
    assert result["meta"]["expression"] == "4d6kh3"

    with pytest.raises(ToolError):
        run("2 d6", {"rng": ScriptedRng([])})


@pytest.mark.parametrize(
    "expr, message",
    [
        ("0d6", "Dice count must be 1-100"),
        ("101d6", "Dice count must be 1-100"),
        ("1d1", "Dice sides must be 2-1000"),
        ("1d1001", "Dice sides must be 2-1000"),
        ("2d6kh3", "Keep must be between 1 and the dice count"),
        ("2d6kh0", "Keep must be between 1 and the dice count"),
        ("2d6kl3", "Keep must be between 1 and the dice count"),
        ("1d20+1001", "Constants must be 0-1000"),
        ("60d6+60d6", "Total dice must be at most 100"),
        ("1+1+1+1+1+1+1+1+1+1+1", "At most 10 terms"),
        ("1" + "+1" * 32, TOO_LONG),
        ("h" * 65, TOO_LONG),
        ("hello", INVALID),
        ("2d", INVALID),
        ("1d20++3", INVALID),
        ("2d6kx1", INVALID),
        ("-1d6", INVALID),
        ("2adv", INVALID),
        ("12345d6", INVALID),
    ],
)
def test_bounds_rejected(expr, message):
    rng = ScriptedRng([1] * 500)
    with pytest.raises(ToolError) as excinfo:
        run(expr, {"rng": rng})
    assert str(excinfo.value) == message
    assert rng.calls == []


def test_bounds_boundary_values_are_accepted():
    result = run("100d2", {"rng": ScriptedRng([1] * 100)})
    assert result["meta"]["terms"][0]["count"] == 100

    result = run("1d1000", {"rng": ScriptedRng([1000])})
    assert result["meta"]["terms"][0]["sides"] == 1000

    result = run("1+1+1+1+1+1+1+1+1+1", {"rng": ScriptedRng([])})
    assert len(result["meta"]["terms"]) == 10
    assert result["meta"]["total"] == 10

    result = run("1d20+1000", {"rng": ScriptedRng([20])})
    assert result["meta"]["total"] == 1020

    expr = "1d20" + " " * 55 + "+ 1d4"
    assert len(expr) == 64
    result = run(expr, {"rng": ScriptedRng([10, 2])})
    assert result["meta"]["total"] == 12


def test_seeded_rng_is_deterministic_and_default_rng_works():
    first = evaluate("4d6kh3+2", random.Random(1234))
    second = evaluate("4d6kh3+2", random.Random(1234))
    assert first == second

    result = run("2d6", {})
    assert 2 <= result["meta"]["total"] <= 12


def test_run_returns_structured_text_and_meta():
    assert roll_tool.NAME == "roll"

    result = run("2d6kh1+4-d4", {"rng": ScriptedRng([2, 6, 3])})

    assert set(result) == {"text", "meta"}
    meta = result["meta"]
    assert meta["tool"] == "roll"
    assert meta["expression"] == "2d6kh1+4-d4"
    assert meta["total"] == 7

    terms = meta["terms"]
    assert isinstance(terms, list)
    assert len(terms) == 3

    dice = terms[0]
    assert set(dice) == {"sign", "count", "sides", "keep", "rolls", "kept", "value"}
    assert dice["sign"] == "+"
    assert dice["rolls"] == [2, 6]
    assert dice["kept"] == [6]
    assert dice["keep"] == 1
    assert dice["value"] == 6

    constant = terms[1]
    assert set(constant) == {"sign", "constant", "value"}
    assert constant == {"sign": "+", "constant": 4, "value": 4}

    dice_minus = terms[2]
    assert set(dice_minus) == {"sign", "count", "sides", "keep", "rolls", "kept", "value"}
    assert dice_minus["sign"] == "-"
    assert dice_minus["keep"] is None
    assert dice_minus["value"] == 3


def test_roll_is_discoverable_and_invokable_without_network():
    svc = ToolService(discover_on_init=True)
    assert svc.list_tools()["roll"] == "app.intelligence.tools.roll"

    result = svc.invoke("roll", "2d6", {"rng": ScriptedRng([3, 4])})

    assert result["text"] == "2d6: [3, 4] = 7"
    assert result["meta"]["tool"] == "roll"
    assert result["meta"]["total"] == 7
