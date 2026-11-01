"""Normalize the consultant species delivery into app/reference/species.json (SPEC-0011 WP-1).

Run from the repo root: python scripts/ingest_species.py
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "docs" / "from_consultant" / "dnd_all_species_full_list.json"
OUTPUT_PATH = ROOT / "app" / "reference" / "species.json"

EDITIONS = {"5e": "5e", "5.5e": "5.5e", "3rd Party": None}

# Curator decisions keyed by delivered name (human sign-off, 2026-10-18).
OVERRIDES = {
    "Hollow One": {
        "edition": "5e",
        "third_party": False,
        "source": "Explorer's Guide to Wildemount",
        "publisher": "Wizards of the Coast",
    },
}

_LEGACY_QUALIFIER = re.compile(r"\s*\(Legacy \d{4}\)$")
_PARENTHETICAL = re.compile(r"\(([^()]+)\)\s*$")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _publisher(source: str) -> str | None:
    match = _PARENTHETICAL.search(source)
    if match and not match.group(1).isdigit():
        return match.group(1)
    return None


def normalize(entries: list[dict]) -> list[dict]:
    records: list[dict] = []
    seen_ids: set[str] = set()
    for raw in entries:
        delivered_edition = raw["Edition"]
        if delivered_edition not in EDITIONS:
            raise ValueError(f"unknown edition {delivered_edition!r} for {raw['Name']!r}")

        name = _LEGACY_QUALIFIER.sub("", raw["Name"])
        species_id = _slug(name)
        if species_id in seen_ids:
            raise ValueError(f"duplicate species id {species_id!r}")
        seen_ids.add(species_id)

        record = {
            "id": species_id,
            "name": name,
            "edition": EDITIONS[delivered_edition],
            "source": raw["Source"],
            "publisher": _publisher(raw["Source"]),
            "third_party": delivered_edition == "3rd Party",
            "creature_type": raw["Creature Type"],
            "description": raw["Description"],
            "character_creation_implications": raw["Character Creation Implications"],
        }
        record.update(OVERRIDES.get(raw["Name"], {}))
        records.append(record)
    return records


def render(records: list[dict]) -> str:
    return json.dumps(records, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    raw = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    records = normalize(raw)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render(records), encoding="utf-8", newline="\n")
    print(f"wrote {len(records)} species to {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
