"""Store-side application of mention detection (SPEC-0019 WP-4, REQ-0028, PAT-ARCH-012).

Real ":memory:" store (session_store fixture); mine_reply is called with the F1 tavern reply.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.world_mining import catalog_stoplist, mine_reply

F1 = (
    "You push open the door of the Rusty Anchor and the noise of the tavern washes over you. "
    'Behind the bar, Old Marta polishes a mug and nods. "Aria, you came back," she says. '
    '"Captain Harl was asking after you."\n'
    "Harl sits in the corner with two sailors from Brightwater. He raises a hand and Marta "
    'whispers, "Careful. The Captain owes money to half of Brightwater." '
    "Veyra's name is not spoken here."
)
F1_NAMES = {"Rusty Anchor", "Old Marta", "Captain Harl"}


@pytest.fixture
def mined(session_store):
    """Session s1 with a canon Brightwater, so F1 proposes exactly the three F1 names."""
    session_store.create_session("s1")
    session_store.create_entity(name="Brightwater", status="canon")
    return session_store


def _pending(store):
    return {e["name"]: e for e in store.list_entities("s1", status="pending")}


def test_creates_pending_rows(mined):
    result = mine_reply(mined, session_id="s1", reply_id="r1", text=F1)

    assert result == {"matched": 1, "proposed": 3, "bumped": 0}
    rows = _pending(mined)
    assert set(rows) == F1_NAMES
    for name, row in rows.items():
        assert row["status"] == "pending"
        assert row["session_id"] is None
        assert row["notes"] == ""
        assert row["evidence"].keys() == {
            "detector",
            "session_id",
            "source_message_id",
            "snippet",
            "first_seen_at",
            "message_ids",
        }
        ev = row["evidence"]
        assert ev["detector"] == "deterministic"
        assert ev["session_id"] == "s1"
        assert ev["source_message_id"] == "r1"
        assert name in ev["snippet"]
        first_seen = datetime.fromisoformat(ev["first_seen_at"])
        assert first_seen.utcoffset() is not None
        assert first_seen.utcoffset().total_seconds() == 0
        assert ev["message_ids"] == ["r1"]
    assert rows["Captain Harl"]["kind"] == "npc"
    assert rows["Old Marta"]["kind"] == "other"


def test_pending_mention_bumps_message_ids(mined):
    mine_reply(mined, session_id="s1", reply_id="r1", text=F1)

    result = mine_reply(mined, session_id="s1", reply_id="r2", text=F1)

    assert result == {"matched": 4, "proposed": 0, "bumped": 3}
    rows = _pending(mined)
    assert all(rows[n]["evidence"]["message_ids"] == ["r1", "r2"] for n in F1_NAMES)


def test_pending_message_ids_capped_at_twenty(mined):
    mined.create_entity(
        name="Old Marta",
        status="pending",
        evidence={
            "detector": "deterministic",
            "session_id": "s1",
            "source_message_id": "m0",
            "snippet": "Old Marta polishes a mug.",
            "first_seen_at": "2026-11-01T00:00:00+00:00",
            "message_ids": [f"m{i}" for i in range(20)],
        },
    )
    before = _pending(mined)["Old Marta"]

    result = mine_reply(mined, session_id="s1", reply_id="r-new", text=F1)

    assert result["bumped"] == 0
    after = _pending(mined)["Old Marta"]
    assert after["evidence"]["message_ids"] == before["evidence"]["message_ids"]
    assert after["updated_at"] == before["updated_at"]


def test_manual_pending_row_untouched(mined):
    mined.create_entity(name="Old Marta", status="pending", session_id=None, evidence=None)
    before = _pending(mined)["Old Marta"]

    mine_reply(mined, session_id="s1", reply_id="r1", text=F1)

    after = _pending(mined)["Old Marta"]
    assert after["evidence"] is None
    assert after["updated_at"] == before["updated_at"]


def test_canon_and_rejected_never_written(mined):
    seed = {"detector": "deterministic", "note": "seed"}
    mined.create_entity(name="Old Marta", status="canon", evidence=seed)
    mined.create_entity(name="Captain Harl", status="rejected", evidence=seed)
    before = {e["name"]: e for e in mined.list_entities("s1")}

    result = mine_reply(mined, session_id="s1", reply_id="r1", text=F1)

    after = {e["name"]: e for e in mined.list_entities("s1")}
    for name in ("Old Marta", "Captain Harl"):
        assert after[name]["updated_at"] == before[name]["updated_at"]
        assert after[name]["evidence"] == seed
    assert result["proposed"] == 1
    assert set(_pending(mined)) == {"Rusty Anchor"}
    assert [e["name"] for e in mined.list_entities("s1")].count("Captain Harl") == 1


def test_idempotent_on_redetection(mined):
    mine_reply(mined, session_id="s1", reply_id="r1", text=F1)
    first = {e["id"]: e for e in mined.list_entities("s1", status="pending")}

    result = mine_reply(mined, session_id="s1", reply_id="r1", text=F1)

    assert result["proposed"] == 0
    assert result["bumped"] == 0
    second = {e["id"]: e for e in mined.list_entities("s1", status="pending")}
    assert second.keys() == first.keys()
    for entity_id, row in second.items():
        assert row["updated_at"] == first[entity_id]["updated_at"]
        assert row["evidence"]["message_ids"] == ["r1"]


def test_zero_max_candidates_proposes_nothing_but_bumps(mined):
    mine_reply(mined, session_id="s1", reply_id="r1", text=F1)

    result = mine_reply(mined, session_id="s1", reply_id="r2", text=F1, max_candidates=0)

    assert result["proposed"] == 0
    assert result["bumped"] == 3


def test_zero_max_candidates_on_fresh_reply_proposes_nothing(mined):
    result = mine_reply(mined, session_id="s1", reply_id="r1", text=F1, max_candidates=0)

    assert result == {"matched": 1, "proposed": 0, "bumped": 0}
    assert _pending(mined) == {}


def test_catalog_stoplist():
    reference = {
        "species": [SimpleNamespace(name="Elf")],
        "weapons": [SimpleNamespace(name="Longsword")],
        "rules": [SimpleNamespace(name="Grapple")],
        "creatures": [SimpleNamespace(name="Owlbear")],
    }

    assert catalog_stoplist(reference) == frozenset({"Elf", "Longsword", "Grapple", "Owlbear"})


def test_catalog_stoplist_missing_keys_give_empty_set():
    assert catalog_stoplist({}) == frozenset()
    assert catalog_stoplist({"species": [SimpleNamespace(name="Elf")]}) == frozenset({"Elf"})
