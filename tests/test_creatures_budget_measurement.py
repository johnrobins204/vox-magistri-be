"""SPEC-0012 WP-5: local creatures budget measurement (T-33 to T-35).

Needs the gitignored dnd_data/ snapshot, so it is skipped in CI. Writes
dnd_data/_budget_creatures.json. Nothing is committed to app/reference/.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "dnd_data"
OUTPUT = DATA_DIR / "_budget_creatures.json"
SCRIPT = ROOT / "scripts" / "ingest_open5e.py"

pytestmark = pytest.mark.skipif(
    not ((DATA_DIR / "creatures.json").exists() and (DATA_DIR / "_documents.json").exists()),
    reason="needs local dnd_data/creatures.json and _documents.json (gitignored; absent in CI)",
)

_spec = importlib.util.spec_from_file_location("ingest_open5e", SCRIPT)
ingest_open5e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingest_open5e)

SRD_2014 = "srd-2014"
SRD_2024 = "srd-2024"
SCENARIOS = {
    "both": [SRD_2014, SRD_2024],
    SRD_2014: [SRD_2014],
    SRD_2024: [SRD_2024],
}
EXCLUDED_FIELDS = {
    "speed_all",
    "saving_throws_all",
    "skill_bonuses_all",
    "modifiers",
    "crossreferences",
    "document",
}


@pytest.fixture(scope="module")
def report() -> dict:
    documents = ingest_open5e._load_documents(DATA_DIR)
    results = {
        name: ingest_open5e.measure("creatures", DATA_DIR, documents, allowlist)
        for name, allowlist in SCENARIOS.items()
    }
    OUTPUT.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return results


def test_t33_both_srds_measurement_is_recorded_with_verdict(report):
    both = report["both"]

    assert both["entries"] > 0
    assert both["within_budget"] == (
        both["bytes"] <= ingest_open5e.MAX_BYTES and both["entries"] <= ingest_open5e.MAX_ENTRIES
    )


def test_t34_single_srd_measurements_are_recorded(report):
    assert report[SRD_2014]["entries"] > 0
    assert report[SRD_2024]["entries"] > 0
    assert report[SRD_2014]["entries"] + report[SRD_2024]["entries"] == report["both"]["entries"]


def test_t35_every_candidate_is_present_or_absent(report):
    for result in report.values():
        for field in ingest_open5e.CANDIDATE_CREATURE_FIELDS:
            assert field in result["fields_present"] or field in result["fields_absent"]


def test_t35_no_excluded_field_is_projected(report):
    for result in report.values():
        assert not EXCLUDED_FIELDS & set(result["fields_present"])
    for path in ingest_open5e.CANDIDATE_CREATURE_FIELDS.values():
        assert path[0] not in EXCLUDED_FIELDS
