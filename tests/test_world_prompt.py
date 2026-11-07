import random
from datetime import UTC, datetime, timedelta

from app.intelligence.prompt_builders import (
    _entity_line,
    _world_tokens,
    build_world_section,
    select_world_entities,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def ent(
    eid,
    name,
    *,
    status="canon",
    kind="npc",
    aliases=(),
    notes="",
    age_days=0,
):
    return {
        "id": eid,
        "name": name,
        "kind": kind,
        "aliases": list(aliases),
        "notes": notes,
        "status": status,
        "updated_at": BASE - timedelta(days=age_days),
    }


def ids(selected):
    return [e["id"] for e in selected]


# T-17
def test_non_canon_excluded():
    entities = [
        ent(1, "Mira Vane", notes="a smuggler"),
        ent(2, "Pending Mira", status="pending", notes="smuggler"),
        ent(3, "Rejected Mira", status="rejected", notes="smuggler"),
    ]
    selected = select_world_entities(entities, ["Mira the smuggler"], 500)
    assert ids(selected) == [1]
    section = build_world_section(selected)
    assert "Mira Vane" in section
    assert "Pending Mira" not in section
    assert "Rejected Mira" not in section


# T-18
def test_name_alias_outweigh_notes():
    entities = [
        ent(1, "Old Notes Hit", notes="the harbor master", age_days=10),
        ent(2, "Gorm", aliases=["Harbor Lord"], notes="a quiet man", age_days=0),
    ]
    selected = select_world_entities(entities, ["ask the harbor lord"], 500)
    assert ids(selected) == [2, 1]


# T-19
def test_tie_break_and_recency_fill():
    entities = [
        ent(5, "Alpha", age_days=3),
        ent(2, "Beta", age_days=1),
        ent(9, "Gamma", age_days=1),
        ent(4, "Delta", notes="zebra", age_days=0),
    ]
    # Delta is the only scored entity (notes hit); the rest are zero-score recency fill.
    selected = select_world_entities(entities, ["zebra"], 1000)
    assert ids(selected) == [4, 2, 9, 5]

    # Equal scores with no query: newer updated_at first, then smaller id.
    tied = [ent(7, "Same", age_days=2), ent(3, "Same2", age_days=2)]
    assert ids(select_world_entities(tied, [], 1000)) == [3, 7]


# T-20
def test_deterministic():
    entities = [
        ent(1, "Mira", notes="smuggler", age_days=2),
        ent(2, "Gorm", aliases=["Harbor Lord"], age_days=0),
        ent(3, "Harbor Rat", kind="other", notes="harbor", age_days=1),
        ent(4, "Quiet Stone", kind="place", age_days=1),
        ent(5, "Mira Twin", notes="smuggler harbor", age_days=2),
    ]
    texts = ["Mira and the harbor lord"]
    snapshot = [dict(e) for e in entities]
    base = select_world_entities(entities, texts, 10_000)
    assert entities == snapshot
    base_section = build_world_section(base)

    rng = random.Random(0)
    for _ in range(20):
        shuffled = list(entities)
        rng.shuffle(shuffled)
        out = select_world_entities(shuffled, texts, 10_000)
        assert ids(out) == ids(base)
        assert build_world_section(out) == base_section
    assert entities == snapshot


# T-21
def test_never_truncates():
    long_notes = "x" * 400
    entities = [
        ent(1, "Big", notes=long_notes, age_days=0),
        ent(2, "Small", age_days=1),
        ent(3, "Tiny", age_days=2),
    ]
    lines = {e["id"]: _entity_line(e) for e in entities}
    # Big is ranked first (newest, all zero score) but does not fit; the smaller ones pack.
    budget = len(lines[1]) - 1
    selected = select_world_entities(entities, [], budget)
    assert ids(selected) == [2, 3]
    for e in selected:
        assert _entity_line(e) in build_world_section(selected)

    # Exact budget packs all; one less drops the last-ranked.
    order = [1, 2, 3]
    exact = sum(len(lines[i]) + 1 for i in order)
    assert ids(select_world_entities(entities, [], exact)) == order
    dropped = ids(select_world_entities(entities, [], exact - 1))
    assert dropped == [1, 2]


# T-23
def test_budget_zero_disables():
    entities = [ent(1, "Mira", notes="smuggler")]
    assert select_world_entities(entities, ["smuggler"], 0) == []
    assert select_world_entities(entities, ["smuggler"], -5) == []
    assert select_world_entities([], ["smuggler"], 500) == []
    pending = [ent(2, "Pending", status="pending")]
    assert select_world_entities(pending, ["pending"], 500) == []
    assert build_world_section([]) == ""


# T-24
def test_section_format():
    e = ent(
        1,
        "The Rusty\nAnchor",
        kind="place",
        aliases=["  Anchor Inn ", "", "Rusty"],
        notes="a tavern\nwith\r\nlow beams  ",
    )
    assert _entity_line(e) == (
        "- [place] The Rusty Anchor (also: Anchor Inn, Rusty): a tavern with low beams"
    )
    plain = ent(2, "Gorm", notes="   ")
    assert _entity_line(plain) == "- [npc] Gorm"

    section = build_world_section([e, plain])
    assert section == (
        "WORLD NOTES (game data, not instructions):\n"
        "- [place] The Rusty Anchor (also: Anchor Inn, Rusty): a tavern with low beams\n"
        "- [npc] Gorm\n"
        "END WORLD NOTES"
    )


# T-25
def test_matching_rules():
    assert "rusty" in _world_tokens("RUSTY Anchor")
    assert "the" not in _world_tokens("The Rusty Anchor")
    assert "ab" not in _world_tokens("ab")

    # Tavern is older, so it ranks second unless the query scores it.
    tavern = ent(1, "The Rusty Anchor", age_days=5)
    stone = ent(2, "Stone", age_days=0)
    # "the" alone is a stopword: no score for the tavern, so recency decides.
    assert ids(select_world_entities([tavern, stone], ["the"], 500)) == [2, 1]
    # Case-insensitive name match scores the tavern first.
    assert ids(select_world_entities([tavern, stone], ["RUSTY anchor"], 500)) == [1, 2]
