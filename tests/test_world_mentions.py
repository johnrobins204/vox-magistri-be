"""Pure mention detector (SPEC-0019 WP-3, REQ-0028, PAT-ARCH-012). No I/O, no store, no model."""

import copy
import dataclasses

import pytest

from app.intelligence.world_mentions import (
    BUILTIN_STOP_PHRASES,
    BUILTIN_STOP_WORDS,
    TITLE_WORDS,
    detect_mentions,
)

F1 = (
    "You push open the door of the Rusty Anchor and the noise of the tavern washes over you. "
    'Behind the bar, Old Marta polishes a mug and nods. "Aria, you came back," she says. '
    '"Captain Harl was asking after you."\n'
    "Harl sits in the corner with two sailors from Brightwater. He raises a hand and Marta "
    'whispers, "Careful. The Captain owes money to half of Brightwater." '
    "Veyra's name is not spoken here."
)
F1_KNOWN = [
    {"id": "e-bw", "name": "Brightwater", "aliases": []},
    {"id": "e-vey", "name": "Veyra", "aliases": []},
]

F2 = (
    "The passage slopes down into the Hollow Crypt. Torchlight catches carved letters above "
    'the arch: "Sir Aldren of Vale, who kept the gate, rests here." Dust coats everything.\n'
    "Make a Wisdom check, Aria. A DC 14 Perception check reveals a loose flagstone. "
    "Beneath it lies a silver key stamped with the sigil of the Ashen Order. "
    "The Order's guards never came this deep."
)

F3 = (
    "Grappling uses an Athletics check against the target's Strength (Athletics) or Dexterity "
    "(Acrobatics) check. On a success the target has the Grappled condition and its speed "
    "drops to 0.\n"
    "You can end the grapple on your turn. See the Player's Handbook."
)

F4 = (
    "Morning light spills over the Canal City. Old Marta is already at her stall, counting "
    "coins, while Mother Greaves watches from across the square."
)
F4_KNOWN = [
    {"id": "e-bw", "name": "Brightwater", "aliases": ["Canal City"]},
    {"id": "e-marta", "name": "Marta Voss", "aliases": ["Old Marta"]},
]


def _names(detection):
    return [c.name for c in detection.candidates]


def _assert_snippets(detection):
    for c in detection.candidates:
        assert c.name in c.snippet
        assert len(c.snippet) <= 160


def test_fixture_f1():
    d = detect_mentions(F1, F1_KNOWN, stoplist=["Aria"])
    assert d.matched_ids == ("e-bw", "e-vey")
    assert _names(d) == ["Rusty Anchor", "Old Marta", "Captain Harl"]
    assert [c.kind for c in d.candidates] == ["other", "other", "npc"]
    _assert_snippets(d)
    bare = detect_mentions(F1, [], stoplist=["Aria"])
    assert bare.candidates[0].name == "Brightwater"
    assert bare.candidates[0].count == 2


def test_fixture_f2():
    d = detect_mentions(F2, [], stoplist=["Aria"])
    assert d.matched_ids == ()
    assert _names(d) == ["Hollow Crypt", "Sir Aldren of Vale", "Ashen Order"]
    assert [c.kind for c in d.candidates] == ["other", "npc", "other"]
    _assert_snippets(d)
    capped = detect_mentions(F2, [], stoplist=["Aria"], max_candidates=2)
    assert _names(capped) == ["Hollow Crypt", "Sir Aldren of Vale"]


def test_fixture_f3():
    d = detect_mentions(F3, [])
    assert d.matched_ids == ()
    assert d.candidates == ()


def test_fixture_f4():
    d = detect_mentions(F4, F4_KNOWN)
    assert d.matched_ids == ("e-bw", "e-marta")
    assert _names(d) == ["Mother Greaves"]
    assert d.candidates[0].kind == "other"
    _assert_snippets(d)


def test_known_matching():
    known = [{"id": "e-mira", "name": "Mira", "aliases": []}]
    assert detect_mentions("Mira smiled at Miranda.", known).matched_ids == ("e-mira",)
    assert detect_mentions("Miranda smiled.", known).matched_ids == ()
    assert detect_mentions("MIRA smiled.", known).matched_ids == ("e-mira",)
    two = [
        {"id": "e-ann", "name": "Ann", "aliases": []},
        {"id": "e-zed", "name": "Zed", "aliases": ["Zedd"]},
    ]
    d = detect_mentions("Zed waved. Ann met Zed and Zed greeted Ann.", two)
    assert d.matched_ids == ("e-zed", "e-ann")
    alias = [{"id": "e-m", "name": "Marta Voss", "aliases": ["Old Marta"]}]
    assert detect_mentions("Old Marta waved.", alias).matched_ids == ("e-m",)


def test_candidate_shapes():
    assert _names(detect_mentions("They climbed Tower of the Moon at dusk.", [])) == [
        "Tower of the Moon"
    ]
    five = "Alpha Beta Gamma Delta Epsilon guard the gate."
    assert detect_mentions(five, []).candidates == ()
    assert detect_mentions("Roll a DC 15 check at the gate.", []).candidates == ()
    comma = "We walked past Silver Tower, Moon Gate."
    assert _names(detect_mentions(comma, [])) == ["Silver Tower", "Moon Gate"]
    assert _names(detect_mentions("We met Veyra's cousin at the gate.", [])) == ["Veyra"]


def test_single_word_rules():
    assert detect_mentions("Gorm waved. Gorm left.", []).candidates == ()
    d = detect_mentions("Gorm waved. Then we saw Gorm leave.", [])
    assert _names(d) == ["Gorm"]
    assert d.candidates[0].count == 2
    assert detect_mentions("We met Ox at the gate.", []).candidates == ()
    # A plural possessive keeps a multi-word name together instead of splitting it.
    d = detect_mentions("We reached Harpers' Haven, a guildhall.", [])
    assert _names(d) == ["Harpers' Haven"]
    # A closing single quote is not a possessive, and a bare comma does not start a sentence.
    names = _names(detect_mentions("They called him 'Harl' The Captain said.", []))
    assert "Harl" in names and all("'" not in n for n in names)
    d = detect_mentions("We left the inn, Marta said.", [])
    assert _names(d) == ["Marta"]
    # Opening a quotation after a comma starts a sentence; mid-sentence quotes do not.
    assert detect_mentions('She whispers, "Careful. Gorm sees."', []).candidates == ()
    assert _names(detect_mentions('She said "Careful" to Brim.', [])) == ["Careful", "Brim"]
    d = detect_mentions("Old Marta waved at the door. We saw Marta again.", [])
    assert _names(d) == ["Old Marta"]
    known = [{"id": "e-m", "name": "Marta Voss", "aliases": []}]
    assert detect_mentions("We spoke with Voss and Marta at the dock.", known).candidates == ()


@pytest.mark.parametrize("term", [*BUILTIN_STOP_WORDS, *BUILTIN_STOP_PHRASES])
def test_builtin_stop_terms_never_proposed(term):
    assert detect_mentions(f"We talked about {term} today.", []).candidates == ()


def test_stoplist():
    d = detect_mentions("We drank at The Rusty Anchor twice.", [])
    assert _names(d) == ["Rusty Anchor"]
    text = "We met Aria Windfoot at the inn, and Windfoot tipped us."
    assert detect_mentions(text, [], stoplist=["Aria Windfoot"]).candidates == ()
    text = "We met a Wood Elf and an Elf at the inn."
    assert detect_mentions(text, [], stoplist=["Wood Elf"]).candidates == ()
    d = detect_mentions("We saw Fire Peak and Fire Giant.", [], stoplist=["Fire Giant"])
    assert _names(d) == ["Fire Peak"]


def test_cap_rank_and_kind():
    text = "We rode past Ash Keep. We rode past Mire Fen. We rode past Mire Fen again."
    d = detect_mentions(text, [])
    assert _names(d) == ["Mire Fen", "Ash Keep"]
    assert [c.count for c in d.candidates] == [2, 1]
    known = [{"id": "e-vey", "name": "Veyra", "aliases": []}]
    d = detect_mentions("We rode past Ash Keep with Veyra.", known, max_candidates=0)
    assert d.matched_ids == ("e-vey",)
    assert d.candidates == ()
    d = detect_mentions("We met McDonald at the gate. Later we met Mcdonald again.", [])
    assert _names(d) == ["McDonald"]
    assert d.candidates[0].count == 2
    for title in TITLE_WORDS:
        d = detect_mentions(f"We met {title} Harl at the gate.", [])
        assert d.candidates[0].kind == "npc"
        assert d.candidates[0].name == f"{title} Harl"
    d = detect_mentions("We met Mother Greaves at the gate.", [])
    assert d.candidates[0].kind == "other"


def test_snippet_and_purity():
    text = "The gate creaked. We met Ash Keep at dusk, and the guard wept. Done."
    d = detect_mentions(text, [])
    assert d.candidates[0].snippet == "We met Ash Keep at dusk, and the guard wept."
    d = detect_mentions("Intro line\nWe met Ash Keep at dusk.", [])
    assert d.candidates[0].snippet == "We met Ash Keep at dusk."
    d = detect_mentions("We met Ash Keep at dusk,\tand left.", [])
    assert d.candidates[0].snippet == "We met Ash Keep at dusk, and left."
    d = detect_mentions('She said "We met Ash Keep at dusk." Then she left.', [])
    assert d.candidates[0].snippet == 'She said "We met Ash Keep at dusk."'
    long_text = "We met Ash Keep " + "very " * 60 + "gate."
    snippet = detect_mentions(long_text, []).candidates[0].snippet
    assert len(snippet) <= 160
    assert snippet.endswith("…")
    assert snippet.startswith("We met Ash Keep")
    assert detect_mentions(F1, F1_KNOWN, ["Aria"]) == detect_mentions(F1, F1_KNOWN, ["Aria"])
    known = [{"id": "e-vey", "name": "Veyra", "aliases": ["Vey"]}]
    before = copy.deepcopy(known)
    detect_mentions(F1, known)
    assert known == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        detect_mentions(F1, []).candidates[0].name = "x"
