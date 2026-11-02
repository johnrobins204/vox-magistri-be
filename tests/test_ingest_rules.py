"""SPEC-0014 WP-4: ingest support for the open5e `rules` dataset (script only).

T-18..T-23: document resolution, projection and verbatim text, allowlist and consumer,
duplicate names within one document, end-to-end ingest into tmp_path, and guards.
Every input is built inline under tmp_path. No test touches the network or dnd_data/.
"""

import copy
import importlib.util
import json
import logging
import re
from pathlib import Path

import pytest

from app.reference.loader import load_entries
from app.reference.rules import Rule

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ingest_open5e.py"

_spec = importlib.util.spec_from_file_location("ingest_open5e", SCRIPT)
ingest_open5e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingest_open5e)

ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CC_BY = [{"name": "Creative Commons Attribution 4.0", "key": "cc-by-40"}]
VERBATIM = "Intro line.\n\n## H\n\n|a|b|\n|---|---|\nEn dash \u2013 kept."


def _documents() -> dict[str, dict]:
    """Shaped like the records in dnd_data/_documents.json."""

    def doc(key: str, display: str, publisher: str) -> dict:
        return {
            "key": key,
            "name": f"Document {key}",
            "display_name": display,
            "publisher": {"name": publisher, "key": publisher.lower().replace(" ", "-")},
            "permalink": f"https://example.invalid/{key}",
            "licenses": CC_BY,
        }

    return {
        "srd-2014": doc("srd-2014", "SRD 5.1 (2014)", "Wizards of the Coast"),
        "srd-2024": doc("srd-2024", "SRD 5.2 (2024)", "Wizards of the Coast"),
        "a5e-ag": doc("a5e-ag", "Adventurer's Guide", "Kobold Press"),
    }


def _raw_rule(name, document_key, key=None, desc="desc"):
    """A raw open5e `rules` entry: `document` is a plain string, `desc` replaces descriptions[]."""
    slug = name.lower().replace(" ", "-")
    return {
        "key": key or f"{document_key}_{slug}",
        "name": name,
        "desc": desc,
        "index": 1,
        "initialHeaderLevel": 2,
        "document": document_key,
        "ruleset": f"{document_key}_x",
        "crossreferences": {"to": []},
    }


def _weapon(name, doc_key, source_key):
    """A raw open5e `weapons` entry with a nested document record (for the weapons guard)."""
    doc = _documents()[doc_key]
    return {
        "key": source_key,
        "name": name,
        "document": doc,
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
def isolated_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest_open5e, "OVERLAY_DIR", tmp_path / "no-overlays")
    monkeypatch.setattr(ingest_open5e, "OGL_LICENSE_SOURCE", tmp_path / "licenses" / "OGL.txt")


@pytest.fixture
def documents():
    return _documents()


# T-18
def test_resolve_documents_replaces_string_document_with_record(documents):
    entries = [_raw_rule("Cover", "srd-2024")]
    before = copy.deepcopy(entries)

    resolved = ingest_open5e.resolve_documents(entries, documents)

    assert resolved is not entries
    assert resolved[0] is not entries[0]
    assert resolved[0]["document"] == documents["srd-2024"]
    assert resolved[0]["key"] == entries[0]["key"]
    assert resolved[0]["desc"] == entries[0]["desc"]
    assert entries == before


# T-18
def test_resolve_documents_passes_dict_documents_through(documents):
    entry = _raw_rule("Cover", "srd-2024")
    entry["document"] = documents["srd-2024"]

    resolved = ingest_open5e.resolve_documents([entry], documents)

    assert resolved == [entry]
    assert resolved[0] is entry


# T-18
def test_resolve_documents_unknown_key_raises_naming_both_keys(documents):
    entry = _raw_rule("Shortbow", "a5e-missing", key="a5e-missing_shortbow")

    with pytest.raises(ValueError) as excinfo:
        ingest_open5e.resolve_documents([entry], documents)

    assert "a5e-missing" in str(excinfo.value)
    assert "a5e-missing_shortbow" in str(excinfo.value)


# T-19
def test_build_records_rules_projection_verbatim_text_and_mappings(documents):
    entries = ingest_open5e.resolve_documents(
        [
            _raw_rule("Cover", "srd-2024", desc=VERBATIM),
            _raw_rule("Hiding", "srd-2014", desc=VERBATIM),
        ],
        documents,
    )

    records = ingest_open5e.build_records("rules", entries)
    by_source = {r["source_key"]: r for r in records}

    expected_keys = {
        "id",
        "name",
        "edition",
        "source",
        "publisher",
        "third_party",
        "source_key",
        "description",
    }
    assert set(ingest_open5e.PROJECTION["rules"]) == expected_keys
    for record in records:
        assert set(record) == expected_keys
        for absent in (
            "desc",
            "index",
            "initialHeaderLevel",
            "ruleset",
            "crossreferences",
            "document",
            "key",
            "slug",
            "document_key",
            "id_fallbacks",
        ):
            assert absent not in record

    cover = by_source["srd-2024_cover"]
    assert cover["description"] == VERBATIM
    assert cover["source"] == documents["srd-2024"]["display_name"]
    assert cover["publisher"] == documents["srd-2024"]["publisher"]["name"]
    assert cover["edition"] == "5.5e"
    assert cover["third_party"] is False
    assert cover["source_key"] == "srd-2024_cover"

    hiding = by_source["srd-2014_hiding"]
    assert hiding["description"] == VERBATIM
    assert hiding["edition"] == "5e"
    assert hiding["third_party"] is False


# T-20
def test_rules_allowlist_is_srd_only_and_consumer_is_the_tool(documents):
    assert ingest_open5e.DOCUMENT_ALLOWLIST["rules"] == ["srd-2014", "srd-2024"]
    assert "rules" in ingest_open5e.CONSUMERS
    assert "/rules" in ingest_open5e.CONSUMERS["rules"]

    entries = ingest_open5e.resolve_documents(
        [
            _raw_rule("Cover", "srd-2024"),
            _raw_rule("Hiding", "srd-2014"),
            _raw_rule("Shortbow", "a5e-ag"),
        ],
        documents,
    )

    records = ingest_open5e.build_records("rules", entries)

    assert sorted(r["source_key"] for r in records) == ["srd-2014_hiding", "srd-2024_cover"]


# T-21
def test_duplicate_names_in_one_document_do_not_raise(documents):
    entries = ingest_open5e.resolve_documents(
        [
            _raw_rule("Cover", "srd-2024", key="srd-2024_a_cover"),
            _raw_rule("Cover", "srd-2014", key="srd-2014_a_cover"),
            _raw_rule("Cover", "srd-2014", key="srd-2014_b_cover"),
        ],
        documents,
    )

    records = ingest_open5e.build_records("rules", entries)

    ids = {r["source_key"]: r["id"] for r in records}
    assert ids == {
        "srd-2024_a_cover": "cover",
        "srd-2014_a_cover": "cover-5e",
        "srd-2014_b_cover": "srd-2014-b-cover",
    }
    assert all(ID_PATTERN.match(i) for i in ids.values())
    assert len(set(ids.values())) == len(ids)


# T-22
def test_ingest_rules_end_to_end_is_deterministic_and_attributed(tmp_path, documents, caplog):
    snapshot = tmp_path / "snap"
    snapshot.mkdir()
    (snapshot / "_documents.json").write_text(
        json.dumps([documents["srd-2014"], documents["srd-2024"]]), encoding="utf-8"
    )
    rules = [
        _raw_rule("Cover", "srd-2024", desc=VERBATIM),
        _raw_rule("Cover", "srd-2014"),
        _raw_rule("Hiding", "srd-2014"),
    ]
    (snapshot / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    out = tmp_path / "reference" / "rules.json"
    out.parent.mkdir()

    count = ingest_open5e.ingest("rules", snapshot, out)

    assert count == 3
    with caplog.at_level(logging.WARNING):
        loaded = load_entries(out, Rule, "rules")
    assert len(loaded) == count
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    first = out.read_bytes()
    ingest_open5e.ingest("rules", snapshot, out)
    assert out.read_bytes() == first

    attribution = (out.parent / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "<!-- document: srd-2014 -->" in attribution
    assert "<!-- document: srd-2024 -->" in attribution


# T-23
def test_ingest_rules_without_documents_file_raises_and_writes_nothing(tmp_path):
    snapshot = tmp_path / "snap"
    snapshot.mkdir()
    (snapshot / "rules.json").write_text(
        json.dumps([_raw_rule("Cover", "srd-2024")]), encoding="utf-8"
    )
    out = tmp_path / "reference" / "rules.json"
    out.parent.mkdir()

    with pytest.raises(ValueError, match=r"_documents\.json"):
        ingest_open5e.ingest("rules", snapshot, out)

    assert not out.exists()
    assert not (out.parent / "ATTRIBUTION.md").exists()


# T-23
def test_weapons_duplicate_names_in_one_srd_document_still_raise():
    # Three same-name srd-2014 entries exhaust [slug, slug-5e]; two would not raise (see report).
    entries = [
        _weapon("Longsword", "srd-2014", "srd-2014_longsword_a"),
        _weapon("Longsword", "srd-2014", "srd-2014_longsword_b"),
        _weapon("Longsword", "srd-2014", "srd-2014_longsword_c"),
    ]

    with pytest.raises(ValueError, match="no free id"):
        ingest_open5e.build_records("weapons", entries)
