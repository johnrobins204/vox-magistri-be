"""SPEC-0014 WP-5: shape of the committed app/reference/rules.json (reads only that file)."""

import json
from pathlib import Path

from app.reference.rules import Rule

ROOT = Path(__file__).resolve().parents[1]
RULES_FILE = ROOT / "app" / "reference" / "rules.json"
ATTRIBUTION_FILE = ROOT / "app" / "reference" / "ATTRIBUTION.md"
# Upstream keys: srd_* for SRD 5.1 (2014), srd-2024_* for SRD 5.2.
SOURCE_KEY_PREFIXES = ("srd_", "srd-2024_")


def _records() -> list[dict]:
    return json.loads(RULES_FILE.read_text(encoding="utf-8"))


def _attribution_display_names() -> set[str]:
    return {
        line[3:].strip()
        for line in ATTRIBUTION_FILE.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    }


# SPEC-0014 T-26: every record has exactly the Rule fields.
def test_t26_rules_records_have_exactly_the_rule_fields():
    fields = set(Rule.model_fields)

    assert _records()
    assert all(set(record) == fields for record in _records())


# SPEC-0014 T-26: both editions occur and no other edition value does.
def test_t26_rules_editions_are_5e_and_5_5e_and_both_occur():
    editions = {record["edition"] for record in _records()}

    assert editions == {"5e", "5.5e"}


# SPEC-0014 T-26: the catalog holds SRD text only, so no entry is third-party.
def test_t26_rules_entries_are_never_third_party():
    assert all(record["third_party"] is False for record in _records())


# SPEC-0014 T-26: ids and source keys are unique; source keys name an SRD document.
def test_t26_rules_ids_and_source_keys_are_unique_and_srd_scoped():
    records = _records()
    ids = [record["id"] for record in records]
    source_keys = [record["source_key"] for record in records]

    assert len(set(ids)) == len(ids)
    assert len(set(source_keys)) == len(source_keys)
    assert all(key.startswith(SOURCE_KEY_PREFIXES) for key in source_keys)


# SPEC-0014 T-26: descriptions are strings.
def test_t26_rules_descriptions_are_strings():
    assert all(isinstance(record["description"], str) for record in _records())


# SPEC-0014 T-26: source values are the SRD display names listed in ATTRIBUTION.md.
def test_t26_rules_sources_match_attribution_display_names():
    sources = {record["source"] for record in _records()}

    assert sources == {"5e 2014 Rules", "5e 2024 Rules"}
    assert sources <= _attribution_display_names()


# SPEC-0014 WP-5 acceptance: the first raw entry's description is verbatim upstream text.
def test_wp5_first_entry_description_is_verbatim_upstream_text():
    record = next(
        r for r in _records() if r["source_key"] == "srd-2024_the-six-abilities_ability-scores"
    )

    assert record["description"].startswith("Each ability has a score from 1 to 20")
    assert "|10–11| This represents the human average.|" in record["description"]
