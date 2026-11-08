"""SPEC-0012 WP-2: open5e ingest core (allowlist, projection, ids, overlay, budget).

Every input is built inline under tmp_path. No test touches the network.
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ingest_open5e.py"

_spec = importlib.util.spec_from_file_location("ingest_open5e", SCRIPT)
ingest_open5e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingest_open5e)

ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _doc(key: str, display: str | None = None) -> dict:
    return {
        "key": key,
        "name": f"Document {key}",
        "display_name": display or f"Display {key}",
        "publisher": {"name": "Publisher of " + key, "key": "pub"},
        "gamesystem": {"name": "5e", "key": "5e"},
        "permalink": f"https://example.invalid/{key}",
        "license": "CC-BY-4.0",
    }


def _weapon(name: str, doc_key: str, source_key: str | None = None) -> dict:
    return {
        "key": source_key or f"{doc_key}_{name.lower().replace(' ', '-')}",
        "name": name,
        "document": _doc(doc_key),
        "properties": [{"property": {"name": "Light", "type": None, "desc": "d"}, "detail": None}],
        "damage_type": {"name": "Piercing", "key": "piercing"},
        "damage_dice": "1d6",
        "distance_unit": "feet",
        "range": 0,
        "long_range": 0,
        "is_simple": True,
        "is_improvised": False,
    }


@pytest.fixture(autouse=True)
def isolated_overlays(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest_open5e, "OVERLAY_DIR", tmp_path / "no-overlays")


def _write_snapshot(directory: Path, dataset: str, entries: list[dict]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{dataset}.json").write_text(json.dumps(entries), encoding="utf-8")
    return directory


def test_t09_allowlist_drops_unlisted_documents():
    entries = [
        _weapon("Longsword", "srd-2024"),
        _weapon("Longsword", "srd-2014"),
        _weapon("Shortbow", "a5e-ag"),
    ]

    kept, dropped = ingest_open5e.filter_allowlisted(entries, ["srd-2014", "srd-2024"])

    assert [e["document"]["key"] for e in kept] == ["srd-2024", "srd-2014"]
    assert dropped == 1


def test_t10_projection_keeps_only_projected_fields():
    records = ingest_open5e.build_records("weapons", [_weapon("Longsword", "srd-2024")])

    assert len(records) == 1
    assert set(records[0]) == set(ingest_open5e.PROJECTION["weapons"])
    for absent in ("document", "descriptions", "icon", "description", "slug", "document_key"):
        assert absent not in records[0]
    assert records[0]["properties"] == ["Light"]
    assert records[0]["damage_type"] == "Piercing"


def test_t11_edition_and_third_party_mapping():
    entries = [
        _weapon("Dagger", "srd-2014"),
        _weapon("Club", "srd-2024"),
        _weapon("Shortbow", "a5e-ag"),
    ]
    by_name = {
        r["name"]: r
        for r in ingest_open5e.build_records(
            "weapons", entries, allowlist=["srd-2014", "srd-2024", "a5e-ag"]
        )
    }

    assert (by_name["Dagger"]["edition"], by_name["Dagger"]["third_party"]) == ("5e", False)
    assert (by_name["Club"]["edition"], by_name["Club"]["third_party"]) == ("5.5e", False)
    assert (by_name["Shortbow"]["edition"], by_name["Shortbow"]["third_party"]) == (None, True)


def test_t12_publisher_and_source_come_from_document():
    record = ingest_open5e.build_records("weapons", [_weapon("Longsword", "srd-2024")])[0]

    assert record["publisher"] == "Publisher of srd-2024"
    assert record["source"] == "Display srd-2024"


def test_t13_source_key_is_open5e_key_verbatim():
    entry = _weapon("Longsword", "srd-2024", source_key="srd-2024_longsword")

    record = ingest_open5e.build_records("weapons", [entry])[0]

    assert record["source_key"] == "srd-2024_longsword"


def test_t14_same_name_in_both_srds_gets_bare_and_5e_suffix():
    entries = [_weapon("Longsword", "srd-2014"), _weapon("Longsword", "srd-2024")]

    records = ingest_open5e.build_records("weapons", entries)
    ids = {r["edition"]: r["id"] for r in records}

    assert ids == {"5.5e": "longsword", "5e": "longsword-5e"}


def test_t15_reserved_id_from_previous_file_is_kept():
    entries = [_weapon("Longsword", "srd-2024"), _weapon("Longsword", "srd-2014")]
    reserved = {"srd-2014_longsword": "longsword-legacy"}

    records = ingest_open5e.build_records("weapons", entries, reserved=reserved)
    ids = {r["source_key"]: r["id"] for r in records}

    assert ids == {"srd-2024_longsword": "longsword", "srd-2014_longsword": "longsword-legacy"}


def test_t16_overlay_replaces_only_provided_fields():
    entries = [_weapon("Longsword", "srd-2024")]
    overlays = [
        {"id": "longsword", "damage_dice": "1d10"},
        {"id": "consultant-only", "name": "Consultant Only", "edition": "5.5e"},
    ]

    records = ingest_open5e.build_records("weapons", entries, overlays=overlays)

    longsword = next(r for r in records if r["id"] == "longsword")
    assert longsword["damage_dice"] == "1d10"
    assert longsword["source"] == "Display srd-2024"
    assert longsword["source_key"] == "srd-2024_longsword"
    assert overlays[1] in records


def test_t17_ids_match_format_and_duplicates_raise():
    entries = [_weapon("Longsword!", "srd-2024"), _weapon("Longsword!", "srd-2024")]
    with pytest.raises(ValueError):
        ingest_open5e.build_records("weapons", entries)

    names = ["Crossbow, hand", "War Pick", "  Quarterstaff  ", "Club (Light)"]
    records = ingest_open5e.build_records("weapons", [_weapon(n, "srd-2024") for n in names])
    for record in records:
        assert ID_PATTERN.match(record["id"]), record["id"]


def test_t18_render_is_deterministic(tmp_path):
    snapshot = _write_snapshot(tmp_path / "snap", "weapons", [_weapon("Longsword", "srd-2024")])
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    ingest_open5e.ingest("weapons", snapshot, first)
    ingest_open5e.ingest("weapons", snapshot, second)

    assert first.read_bytes() == second.read_bytes()
    records = json.loads(first.read_text(encoding="utf-8"))
    assert first.read_text(encoding="utf-8") == (
        json.dumps(records, indent=2, ensure_ascii=False) + "\n"
    )


def test_t19_entry_limit_is_inclusive():
    def record(i: int) -> dict:
        return {"id": f"entry-{i}"}

    at_limit = [record(i) for i in range(2000)]
    assert ingest_open5e.check_budget(at_limit)

    with pytest.raises(ValueError):
        ingest_open5e.check_budget(at_limit + [record(2000)])


def test_t19_byte_limit_is_inclusive(monkeypatch):
    records = [{"id": "a"}]
    size = len(ingest_open5e.render(records).encode("utf-8"))

    monkeypatch.setattr(ingest_open5e, "MAX_BYTES", size)
    assert ingest_open5e.check_budget(records)

    monkeypatch.setattr(ingest_open5e, "MAX_BYTES", size - 1)
    with pytest.raises(ValueError):
        ingest_open5e.check_budget(records)


def test_t19_failed_budget_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_open5e, "MAX_ENTRIES", 1)
    snapshot = _write_snapshot(
        tmp_path / "snap",
        "weapons",
        [_weapon("Longsword", "srd-2024"), _weapon("Dagger", "srd-2024")],
    )
    out = tmp_path / "weapons.json"

    with pytest.raises(ValueError):
        ingest_open5e.ingest("weapons", snapshot, out)

    assert not out.exists()


def test_t20_dataset_without_consumer_is_rejected(tmp_path):
    snapshot = _write_snapshot(tmp_path / "snap", "no_such_dataset", [])

    with pytest.raises(ValueError):
        ingest_open5e.ingest("no_such_dataset", snapshot, tmp_path / "out.json")
