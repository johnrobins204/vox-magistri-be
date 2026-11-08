"""SPEC-0018 WP-5: pure stat-block renderer (T-13 to T-16) and a real-data sweep."""

import json

import pytest

from app.intelligence.monster_blocks import render_stat_block
from app.reference.creatures import CREATURES_PATH, Creature
from tests.creature_fixtures import make_creature

_HEADINGS = {"Traits", "Actions", "Bonus Actions", "Reactions", "Legendary Actions"}


def test_t13_golden_2014_goblin_like():
    creature = make_creature(
        "Goblin",
        "5e",
        size="Small",
        type="humanoid (goblinoid)",
        alignment="neutral evil",
        armor_class=15,
        armor_detail="leather armor, shield",
        hit_points=7,
        hit_dice="2d6",
        speed={"walk": 30},
        ability_scores={
            "strength": 8,
            "dexterity": 14,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 8,
            "charisma": 8,
        },
        skill_bonuses={"stealth": 6},
        senses={"darkvision": 60},
        passive_perception=9,
        languages="Common, Goblin",
        cr=0.25,
        experience_points=50,
        traits=[
            {
                "name": "Nimble Escape",
                "desc": "The goblin can take the Disengage or Hide action as a bonus action on each of its turns.",
            }
        ],
        actions=[
            {
                "name": "Scimitar",
                "desc": "Melee Weapon Attack: +4 to hit, reach 5 ft., one target. Hit: 5 (1d6 + 2) slashing damage.",
            }
        ],
    )
    expected = "\n".join(
        [
            "Goblin (2014)",
            "Small humanoid (goblinoid), neutral evil",
            "AC 15 (leather armor, shield)",
            "HP 7 (2d6)",
            "Speed walk 30 ft.",
            "STR 8 (-1) DEX 14 (+2) CON 10 (+0) INT 10 (+0) WIS 8 (-1) CHA 8 (-1)",
            "Skills Stealth +6",
            "Senses darkvision 60 ft., passive Perception 9",
            "Languages Common, Goblin",
            "CR 1/4 (XP 50)",
            "",
            "Traits",
            "Nimble Escape. The goblin can take the Disengage or Hide action as a bonus action on each of its turns.",
            "",
            "Actions",
            "Scimitar. Melee Weapon Attack: +4 to hit, reach 5 ft., one target. Hit: 5 (1d6 + 2) slashing damage.",
        ]
    )
    assert render_stat_block(creature) == expected


def test_t14_golden_2024_legendary_monster():
    creature = make_creature(
        "Drake Wyrm",
        "5.5e",
        size="Huge",
        type="dragon",
        alignment="chaotic evil",
        armor_class=19,
        armor_detail="natural armor",
        hit_points=256,
        hit_dice="19d12 + 133",
        speed={"walk": 40, "fly": 80, "climb": 40},
        ability_scores={
            "strength": 27,
            "dexterity": 10,
            "constitution": 25,
            "intelligence": 16,
            "wisdom": 13,
            "charisma": 21,
        },
        saving_throws={"dexterity": 7, "constitution": 13, "wisdom": 7, "charisma": 11},
        skill_bonuses={"perception": 13, "stealth": 7},
        damage_immunities="fire",
        senses={"blindsight": 60, "darkvision": 120},
        passive_perception=23,
        languages="Common, Draconic",
        cr=17,
        experience_points=18000,
        traits=[
            {
                "name": "Legendary Resistance",
                "desc": "If the wyrm fails a saving throw, it can choose to succeed instead.",
            }
        ],
        actions=[
            {
                "name": "Claw",
                "desc": "Melee Weapon Attack: +13 to hit, reach 10 ft., one target. Hit: 19 (2d10 + 8) slashing damage.",
            },
            {
                "name": "Dread Glare",
                "usage": "3/Day",
                "desc": "Each creature within 120 ft. must make a DC 19 Wisdom saving throw or be frightened.",
            },
        ],
        bonus_actions=[
            {
                "name": "Cunning Retreat",
                "desc": "The wyrm takes the Disengage or Hide action.",
            }
        ],
        reactions=[
            {
                "name": "Parry",
                "desc": "The wyrm adds 5 to its AC against one melee attack that would hit it.",
            }
        ],
        legendary_actions=[
            {"name": "Detect", "cost": 1, "desc": "The wyrm makes a Wisdom (Perception) check."},
            {
                "name": "Wing Attack",
                "cost": 2,
                "desc": "The wyrm beats its wings. Each creature within 10 ft. must succeed on a DC 21 Dexterity saving throw or take 15 (2d6 + 8) bludgeoning damage.",
            },
        ],
    )
    expected = "\n".join(
        [
            "Drake Wyrm (2024)",
            "Huge dragon, chaotic evil",
            "AC 19 (natural armor)",
            "HP 256 (19d12 + 133)",
            "Speed walk 40 ft., climb 40 ft., fly 80 ft.",
            "STR 27 (+8) DEX 10 (+0) CON 25 (+7) INT 16 (+3) WIS 13 (+1) CHA 21 (+5)",
            "Saving Throws Dex +7, Con +13, Wis +7, Cha +11",
            "Skills Perception +13, Stealth +7",
            "Damage Immunities fire",
            "Senses blindsight 60 ft., darkvision 120 ft., passive Perception 23",
            "Languages Common, Draconic",
            "CR 17 (XP 18,000)",
            "",
            "Traits",
            "Legendary Resistance. If the wyrm fails a saving throw, it can choose to succeed instead.",
            "",
            "Actions",
            "Claw. Melee Weapon Attack: +13 to hit, reach 10 ft., one target. Hit: 19 (2d10 + 8) slashing damage.",
            "Dread Glare (3/Day). Each creature within 120 ft. must make a DC 19 Wisdom saving throw or be frightened.",
            "",
            "Bonus Actions",
            "Cunning Retreat. The wyrm takes the Disengage or Hide action.",
            "",
            "Reactions",
            "Parry. The wyrm adds 5 to its AC against one melee attack that would hit it.",
            "",
            "Legendary Actions",
            "Detect. The wyrm makes a Wisdom (Perception) check.",
            "Wing Attack (Costs 2 Actions). The wyrm beats its wings. Each creature within 10 ft. must succeed on a DC 21 Dexterity saving throw or take 15 (2d6 + 8) bludgeoning damage.",
        ]
    )
    block = render_stat_block(creature)
    assert block == expected
    headings = [line for line in block.split("\n") if line in _HEADINGS]
    assert headings == ["Traits", "Actions", "Bonus Actions", "Reactions", "Legendary Actions"]


@pytest.mark.parametrize(
    ("score", "modifier"),
    [(1, "-5"), (10, "+0"), (11, "+0"), (20, "+5"), (30, "+10")],
)
def test_t15_ability_modifiers(score, modifier):
    creature = make_creature(
        "Mod Test",
        "5.5e",
        ability_scores={
            "strength": score,
            "dexterity": 10,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 10,
            "charisma": 10,
        },
    )
    expected = (
        f"STR {score} ({modifier}) DEX 10 (+0) CON 10 (+0) INT 10 (+0) WIS 10 (+0) CHA 10 (+0)"
    )
    assert expected in render_stat_block(creature).split("\n")


@pytest.mark.parametrize(
    ("cr", "text"),
    [(0, "0"), (0.125, "1/8"), (0.25, "1/4"), (0.5, "1/2"), (11, "11")],
)
def test_t15_challenge_rating_text(cr, text):
    creature = make_creature("CR Test", "5.5e", cr=cr)
    assert f"CR {text}" in render_stat_block(creature).split("\n")


def test_t15_xp_thousands_separator_and_omission():
    with_xp = make_creature("XP Test", "5.5e", cr=11, experience_points=155000)
    assert render_stat_block(with_xp).split("\n")[-1] == "CR 11 (XP 155,000)"
    without_xp = make_creature("XP Test", "5.5e", cr=11, experience_points=None)
    assert render_stat_block(without_xp).split("\n")[-1] == "CR 11"


def test_t16_empty_sections_and_zero_senses_are_absent():
    creature = make_creature(
        "Empty Thing",
        "5.5e",
        senses={"darkvision": 0},
        passive_perception=None,
        cr=0.25,
    )
    expected = "\n".join(
        [
            "Empty Thing (2024)",
            "STR 10 (+0) DEX 10 (+0) CON 10 (+0) INT 10 (+0) WIS 10 (+0) CHA 10 (+0)",
            "Languages —",
            "CR 1/4",
        ]
    )
    assert render_stat_block(creature) == expected


def test_t16_long_desc_is_verbatim_and_input_not_mutated():
    desc = "lorem ipsum dolor sit amet " * 200
    assert len(desc) >= 5000
    creature = make_creature(
        "Long Desc",
        "5e",
        traits=[{"name": "Long", "desc": desc}],
    )
    before = creature.model_dump()
    block = render_stat_block(creature)
    assert f"Long. {desc}" in block
    assert creature.model_dump() == before


def test_real_creatures_render_without_error():
    raw = json.loads(CREATURES_PATH.read_text(encoding="utf-8"))
    creatures = [Creature.model_validate(entry) for entry in raw]
    assert creatures
    for creature in creatures:
        block = render_stat_block(creature)
        assert block, creature.id
        assert block.startswith(creature.name), creature.id
