"""SPEC-0011 WP-1: species ingest script and the checked-in normalized file."""

import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ingest_species.py"
CONSULTANT = ROOT / "docs" / "from_consultant" / "dnd_all_species_full_list.json"
CHECKED_IN = ROOT / "app" / "reference" / "species.json"

_spec = importlib.util.spec_from_file_location("ingest_species", SCRIPT)
ingest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingest)

EXPECTED_KEYS = {
    "id",
    "name",
    "edition",
    "source",
    "publisher",
    "third_party",
    "creature_type",
    "description",
    "character_creation_implications",
}
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@pytest.fixture(scope="module")
def raw():
    return json.loads(CONSULTANT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def entries(raw):
    return ingest.normalize(raw)


def _raw_entry(name, edition="5e"):
    return {
        "Name": name,
        "Edition": edition,
        "Source": "Player's Handbook (2014)",
        "Creature Type": "Humanoid",
        "Description": "d",
        "Character Creation Implications": "c",
    }


def test_t01_normalize_yields_68_entries_with_exact_keys(entries):
    assert len(entries) == 68
    for entry in entries:
        assert set(entry) == EXPECTED_KEYS


def test_t02_ids_are_unique_slugs_and_names_are_stripped(entries):
    ids = [e["id"] for e in entries]
    assert len(set(ids)) == len(ids)
    assert all(SLUG.match(i) for i in ids)

    by_name = {e["name"]: e for e in entries}
    assert by_name["Deep Gnome (Svirfneblin)"]["id"] == "deep-gnome-svirfneblin"
    assert by_name["Half-Elf"]["id"] == "half-elf"
    assert by_name["Half-Orc"]["id"] == "half-orc"
    assert "Half-Elf (Legacy 2014)" not in by_name


def test_t03_hollow_one_is_corrected(entries):
    hollow = next(e for e in entries if e["name"] == "Hollow One")
    assert hollow["edition"] == "5e"
    assert hollow["third_party"] is False
    assert hollow["publisher"] == "Wizards of the Coast"
    assert hollow["source"] == "Explorer's Guide to Wildemount"


def test_t04_edition_and_third_party_counts(entries):
    counts = Counter(e["edition"] for e in entries)
    assert counts["5.5e"] == 10
    assert counts["5e"] == 49
    assert counts[None] == 9
    for e in entries:
        assert (e["edition"] is None) == (e["third_party"] is True)
        assert e["edition"] != "3rd Party"


def test_t05_publisher_is_never_invented(raw, entries):
    for delivered, entry in zip(raw, entries, strict=True):
        if delivered["Name"] == "Hollow One":
            continue
        assert entry["publisher"] is None or entry["publisher"] in delivered["Source"]


def test_t06_text_fields_are_not_rewritten(raw, entries):
    for delivered, entry in zip(raw, entries, strict=True):
        assert entry["description"] == delivered["Description"]
        assert entry["character_creation_implications"] == (
            delivered["Character Creation Implications"]
        )
        assert entry["creature_type"] == delivered["Creature Type"]


def test_t07_duplicate_ids_fail_the_ingest():
    entries = [_raw_entry("Half-Elf (Legacy 2014)"), _raw_entry("Half-Elf")]
    with pytest.raises(ValueError):
        ingest.normalize(entries)


def test_t08_checked_in_file_matches_script_output(raw):
    expected = ingest.render(ingest.normalize(raw)).encode("utf-8")
    assert CHECKED_IN.read_bytes() == expected
