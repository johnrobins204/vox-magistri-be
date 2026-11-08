"""SPEC-0018 WP-3 (T-10): shape of the committed app/reference/creatures.json."""

import json
from pathlib import Path

from app.reference.creatures import CREATURES_PATH, Creature

ROOT = Path(__file__).resolve().parents[1]


def _records() -> list[dict]:
    return json.loads(CREATURES_PATH.read_text(encoding="utf-8"))


# SPEC-0018 T-10: record keys equal the Creature fields.
def test_t10_record_keys_equal_the_creature_fields():
    for record in _records():
        assert set(record) == set(Creature.model_fields)


# SPEC-0018 T-10: the dataset is both SRDs (656) or SRD 2024 only (331).
def test_t10_entry_count_and_editions_match_an_allowed_allowlist():
    records = _records()
    shape = (len(records), frozenset(r["edition"] for r in records))

    assert shape in {(656, frozenset({"5e", "5.5e"})), (331, frozenset({"5.5e"}))}


# SPEC-0018 T-10: SRD content only, so no third-party entries.
def test_t10_no_third_party_entries():
    assert all(r["third_party"] is False for r in _records())


# SPEC-0018 T-10: ids and source keys are unique; source keys name their SRD.
def test_t10_ids_are_unique():
    ids = [r["id"] for r in _records()]

    assert len(ids) == len(set(ids))


def test_t10_source_keys_are_unique_and_prefixed_by_srd():
    keys = [r["source_key"] for r in _records()]

    assert len(keys) == len(set(keys))
    assert all(k.startswith(("srd_", "srd-2024_")) for k in keys)


# SPEC-0018 T-10: nested action lists are kept; the raw upstream keys are dropped.
def test_t10_aboleth_has_legendary_actions():
    aboleth = [r for r in _records() if r["name"] == "Aboleth"]

    assert aboleth
    assert all(r["legendary_actions"] for r in aboleth)


def test_t10_dropped_upstream_keys_are_absent_from_the_file():
    text = CREATURES_PATH.read_text(encoding="utf-8")

    assert '"attacks"' not in text
    assert '"crossreferences"' not in text
