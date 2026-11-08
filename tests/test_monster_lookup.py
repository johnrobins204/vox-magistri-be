"""SPEC-0018 WP-6: /monster name matching (T-17 to T-20) and real-catalog checks."""

import json

import pytest

from app.intelligence.monster_blocks import find_creature
from app.intelligence.tools import ToolError
from app.reference.creatures import CREATURES_PATH, Creature
from tests.creature_fixtures import make_creature


@pytest.fixture(scope="module")
def shipped():
    raw = json.loads(CREATURES_PATH.read_text(encoding="utf-8"))
    return [Creature.model_validate(entry) for entry in raw]


# SPEC-0018 T-17: exact, then substring.
def test_t17_exact_then_substring():
    catalog = [make_creature("Goblin", "5e"), make_creature("Goblin Boss")]
    assert find_creature("goblin", catalog).name == "Goblin"
    assert find_creature("  GOBLIN-boss! ", catalog).name == "Goblin Boss"
    assert find_creature("boss", catalog).name == "Goblin Boss"


# SPEC-0018 T-18: several distinct names raise, listing the first 5 sorted names.
def test_t18_several_distinct_names_raise_with_five_sorted():
    colours = ["Red", "Blue", "Green", "Black", "White", "Gold", "Silver"]
    catalog = [make_creature(f"{colour} Dragon") for colour in colours]
    with pytest.raises(ToolError, match="matches several monsters") as info:
        find_creature("dragon", catalog)
    assert str(info.value).endswith(
        "Black Dragon, Blue Dragon, Gold Dragon, Green Dragon, Red Dragon. Use a more exact name."
    )


# SPEC-0018 T-19: edition tie-break and the 2014/2024 token.
def test_t19_editions_prefer_5_5e_and_honour_year_token():
    catalog = [make_creature("Goblin", "5e"), make_creature("Goblin", "5.5e")]
    assert find_creature("goblin", catalog).edition == "5.5e"
    assert find_creature("goblin 2014", catalog).edition == "5e"
    assert find_creature("goblin 2024", catalog).edition == "5.5e"
    assert find_creature("goblin 2014", [make_creature("Goblin", "5.5e")]) is None


def test_t19_tie_break_then_non_third_party_then_lowest_id():
    catalog = [
        make_creature("Ogre", "5.5e", id="ogre-b"),
        make_creature("Ogre", "5.5e", id="ogre-a", third_party=True),
        make_creature("Ogre", "5.5e", id="ogre-c"),
    ]
    assert find_creature("ogre", catalog).id == "ogre-b"


# SPEC-0018 T-20: near-typo suggestions (at most 3) and true misses.
def test_t20_near_typo_suggests_at_most_three_names():
    catalog = [
        make_creature("Goblin"),
        make_creature("Goblins"),
        make_creature("Goblim"),
        make_creature("Goblan"),
    ]
    with pytest.raises(ToolError) as info:
        find_creature("gobln", catalog)
    message = str(info.value)
    assert message.startswith('No SRD monster named "gobln". Did you mean: Goblin')
    suggested = message.split("Did you mean: ", 1)[1].rstrip("?").split(", ")
    assert 1 <= len(suggested) <= 3


def test_t20_true_miss_and_empty_inputs_return_none():
    catalog = [make_creature("Goblin")]
    assert find_creature("Zorbax the Unknowable", catalog) is None
    assert find_creature("goblin", []) is None
    assert find_creature("gobln", []) is None
    assert find_creature("   ", catalog) is None


# Real shipped catalog (app/reference/creatures.json): name quirks the fixtures miss.
def test_real_exact_name_and_edition_duplicates(shipped):
    assert find_creature("aboleth", shipped).id == "aboleth"
    assert find_creature("aboleth 2014", shipped).id == "aboleth-5e"
    assert find_creature("aboleth 2024", shipped).id == "aboleth"
    assert find_creature("ancient red dragon", shipped).id == "ancient-red-dragon"
    assert find_creature("ancient red dragon 2014", shipped).id == "ancient-red-dragon-5e"


def test_real_goblin_only_exists_as_5e(shipped):
    # No 5.5e "Goblin" in the shipped data: the 5e entry is the only exact match.
    assert find_creature("goblin", shipped).id == "goblin"
    assert find_creature("goblin 2014", shipped).id == "goblin"
    with pytest.raises(ToolError, match="matches several monsters") as info:
        find_creature("goblin 2024", shipped)
    assert str(info.value).startswith(
        '"goblin 2024" matches several monsters: Goblin Boss, Goblin Minion, Goblin Warrior, '
        "Hobgoblin Captain, Hobgoblin Warrior."
    )


def test_real_near_typo_and_miss(shipped):
    with pytest.raises(ToolError) as info:
        find_creature("abolth", shipped)
    assert str(info.value) == 'No SRD monster named "abolth". Did you mean: Aboleth?'
    assert find_creature("zorblaxian", shipped) is None


def test_real_parentheses_and_commas_normalize(shipped):
    assert find_creature("elf, drow", shipped).id == "elf-drow"
    assert find_creature("Elf Drow", shipped).id == "elf-drow"
    assert find_creature("giant rat (diseased)", shipped).id == "giant-rat-diseased"
    assert find_creature("giant rat", shipped).id == "giant-rat"
    assert find_creature("giant rat 2014", shipped).id == "giant-rat-5e"


def test_real_same_creature_under_two_spellings_is_ambiguous(shipped):
    # "Deep Gnome (Svirfneblin)" and "Gnome, Deep (Svirfneblin)" normalize to distinct names.
    with pytest.raises(ToolError, match="matches several monsters") as info:
        find_creature("svirfneblin", shipped)
    assert "Deep Gnome (Svirfneblin), Gnome, Deep (Svirfneblin)" in str(info.value)
