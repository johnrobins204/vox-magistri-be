"""Ingest open5e snapshots into app/reference/<dataset>.json (SPEC-0012 WP-2; ADR-0007).

Reads dnd_data/<dataset>.json written by sync_open5e.py. Keeps allowlisted documents only,
projects the fields a consumer uses, assigns app-owned slug ids and applies the curated overlay.
Nothing under app/ imports this module, and it never touches the network.
Run from the repo root: python -m scripts.ingest_open5e [dataset ...]
"""

import json
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from app.services.logger import get_logger

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / "dnd_data"
REFERENCE_DIR = ROOT / "app" / "reference"
OVERLAY_DIR = ROOT / "scripts" / "overlays"
OGL_LICENSE_SOURCE = ROOT / "scripts" / "licenses" / "OGL-1.0a.txt"
DOCUMENTS_FILE = "_documents.json"
ATTRIBUTION_FILE = "ATTRIBUTION.md"
OGL_COPY_FILE = "LICENSE-OGL.txt"

MAX_BYTES = 2_000_000
MAX_ENTRIES = 2_000

SRD_2014 = "srd-2014"
SRD_2024 = "srd-2024"
EDITION_BY_DOCUMENT = {SRD_2014: "5e", SRD_2024: "5.5e"}
DEFAULT_DOCUMENTS = [SRD_2014, SRD_2024]

DOCUMENT_ALLOWLIST: dict[str, list[str]] = {
    "conditions": DEFAULT_DOCUMENTS,
    "weapons": DEFAULT_DOCUMENTS,
}
PROJECTION: dict[str, tuple[str, ...]] = {
    "conditions": (
        "id",
        "name",
        "edition",
        "source",
        "publisher",
        "third_party",
        "source_key",
        "description",
    ),
    "weapons": (
        "id",
        "name",
        "edition",
        "source",
        "publisher",
        "third_party",
        "source_key",
        "damage_dice",
        "damage_type",
        "properties",
        "range",
        "long_range",
        "distance_unit",
        "is_simple",
        "is_improvised",
    ),
}
CONSUMERS: dict[str, str] = {"weapons": "GET /api/v1/reference/weapons"}

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SECTION_MARKER = re.compile(r"^<!-- document: (\S+) -->$", re.MULTILINE)
_OGL_PATTERN = re.compile(
    r"OGL[\s-]*1\.0a|Open Game License,?\s*(?:Version\s+)?1\.0a", re.IGNORECASE
)

log = get_logger(__name__)


def _slug(text: str) -> str:
    return _NON_SLUG.sub("-", text.lower()).strip("-")


def _description(raw: dict, document_key: str) -> str:
    for block in raw.get("descriptions", []):
        if block["document"]["key"] == document_key:
            return block["desc"]
    raise ValueError(f"no description for {raw['key']!r} in document {document_key!r}")


def _weapon_fields(raw: dict) -> dict:
    return {
        "damage_dice": raw["damage_dice"],
        "damage_type": (raw.get("damage_type") or {}).get("name"),
        "properties": [p["property"]["name"] for p in raw.get("properties") or []],
        "range": raw["range"],
        "long_range": raw["long_range"],
        "distance_unit": raw["distance_unit"],
        "is_simple": raw["is_simple"],
        "is_improvised": raw["is_improvised"],
    }


_DATASET_FIELDS: dict[str, Callable[[dict], dict]] = {"weapons": _weapon_fields}


def _flatten(raw: dict, dataset: str) -> dict:
    """Every source field, including internal ones that projection drops."""
    doc = raw["document"]
    key = doc["key"]
    slug = _slug(raw["name"])
    if not slug:
        raise ValueError(f"name {raw['name']!r} yields an empty id")
    flat = {
        "id": None,
        "slug": slug,
        "name": raw["name"],
        "edition": EDITION_BY_DOCUMENT.get(key),
        "source": doc["display_name"],
        "publisher": doc["publisher"]["name"],
        "third_party": key not in EDITION_BY_DOCUMENT,
        "source_key": raw["key"],
        "document_key": key,
    }
    if "description" in PROJECTION[dataset]:
        flat["description"] = _description(raw, key)
    if dataset in _DATASET_FIELDS:
        flat.update(_DATASET_FIELDS[dataset](raw))
    return flat


def filter_allowlisted(entries: list[dict], allowed: list[str]) -> tuple[list[dict], int]:
    kept = [e for e in entries if e["document"]["key"] in allowed]
    return kept, len(entries) - len(kept)


def _id_candidates(record: dict) -> list[str]:
    """Bare slug first, then the suffix for the record's edition or third-party document."""
    slug = record["slug"]
    key = record["document_key"]
    if key == SRD_2024:
        return [slug]
    if key == SRD_2014:
        return [slug, f"{slug}-5e"]
    return [slug, f"{slug}-{_slug(key)}"]


def _rank(record: dict) -> int:
    """Claim precedence among bulk records: 5.5e, then 5e, then third-party."""
    key = record["document_key"]
    if key == SRD_2024:
        return 0
    if key == SRD_2014:
        return 1
    return 2


def _assign_ids(records: list[dict], reserved: dict[str, str], overlay_ids: set[str]) -> None:
    for record in records:
        if record["source_key"] in reserved:
            record["id"] = reserved[record["source_key"]]
    claimed = {r["id"] for r in records if r["id"] is not None}
    pending = sorted((r for r in records if r["id"] is None), key=_rank)

    for record in pending:
        if record["slug"] in overlay_ids and record["slug"] not in claimed:
            record["id"] = record["slug"]
            claimed.add(record["slug"])

    for record in pending:
        if record["id"] is not None:
            continue
        free = [c for c in _id_candidates(record) if c not in claimed]
        if not free:
            raise ValueError(f"no free id for {record['source_key']!r}")
        record["id"] = free[0]
        claimed.add(free[0])


def build_records(
    dataset: str,
    entries: list[dict],
    reserved: dict[str, str] | None = None,
    overlays: list[dict] | None = None,
    allowlist: list[str] | None = None,
) -> list[dict]:
    allowed = DOCUMENT_ALLOWLIST[dataset] if allowlist is None else allowlist
    kept, dropped = filter_allowlisted(entries, allowed)
    if dropped:
        log.info("ingest.allowlist_dropped", extra={"dataset": dataset, "dropped": dropped})

    flat = [_flatten(e, dataset) for e in kept]
    overlay_by_id: dict[str, dict] = {}
    for overlay in overlays or []:
        if overlay["id"] in overlay_by_id:
            raise ValueError(f"duplicate overlay id {overlay['id']!r}")
        overlay_by_id[overlay["id"]] = overlay

    _assign_ids(flat, reserved or {}, set(overlay_by_id))

    records: list[dict] = []
    matched: set[str] = set()
    for rec in flat:
        projected = {key: rec[key] for key in PROJECTION[dataset]}
        if rec["id"] in overlay_by_id:
            projected.update(overlay_by_id[rec["id"]])
            matched.add(rec["id"])
        records.append(projected)
    records.extend(o for oid, o in overlay_by_id.items() if oid not in matched)

    seen: set[str] = set()
    for record in records:
        if not _ID_PATTERN.match(record["id"]):
            raise ValueError(f"invalid id {record['id']!r}")
        if record["id"] in seen:
            raise ValueError(f"duplicate id {record['id']!r}")
        seen.add(record["id"])
    return records


def render(records: list[dict]) -> str:
    return json.dumps(records, indent=2, ensure_ascii=False) + "\n"


def check_budget(records: list[dict]) -> str:
    if len(records) > MAX_ENTRIES:
        raise ValueError(f"{len(records)} entries exceed the {MAX_ENTRIES} budget")
    text = render(records)
    size = len(text.encode("utf-8"))
    if size > MAX_BYTES:
        raise ValueError(f"{size} bytes exceed the {MAX_BYTES} budget")
    return text


# Output field -> path in an open5e creature entry. Paths missing from the snapshot are reported.
CANDIDATE_CREATURE_FIELDS: dict[str, tuple[str, ...]] = {
    "name": ("name",),
    "size": ("size",),
    "type": ("type",),
    "alignment": ("alignment",),
    "armor_class": ("armor_class",),
    "hit_points": ("hit_points",),
    "hit_dice": ("hit_dice",),
    "speed": ("speed",),
    "ability_scores": ("ability_scores",),
    "saving_throws": ("saving_throws",),
    "skill_bonuses": ("skill_bonuses",),
    "damage_vulnerabilities": ("resistances_and_immunities", "damage_vulnerabilities"),
    "damage_resistances": ("resistances_and_immunities", "damage_resistances"),
    "damage_immunities": ("resistances_and_immunities", "damage_immunities"),
    "condition_immunities": ("resistances_and_immunities", "condition_immunities"),
    "senses": ("senses",),
    "languages": ("languages",),
    "challenge_rating_text": ("challenge_rating_text",),
    "cr": ("challenge_rating",),
    "actions": ("actions",),
    "reactions": ("reactions",),
    "legendary_actions": ("legendary_actions",),
    "traits": ("traits",),
}
_MISSING = object()


def _creature_value(raw: dict, path: tuple[str, ...]) -> object:
    node: object = raw
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return _MISSING
        node = node[key]
    return node


def measure(
    dataset: str, snapshot_dir: Path, documents: dict[str, dict], allowlist: list[str]
) -> dict:
    """Size the slim projection without writing it; reports instead of enforcing the budget."""
    entries = json.loads((Path(snapshot_dir) / f"{dataset}.json").read_text(encoding="utf-8"))
    kept, dropped = filter_allowlisted(entries, allowlist)
    flat = [
        {
            "id": None,
            "slug": _slug(raw["name"]),
            "document_key": raw["document"]["key"],
            "source_key": raw["key"],
        }
        for raw in kept
    ]
    _assign_ids(flat, {}, set())

    records: list[dict] = []
    for raw, rec in zip(kept, flat, strict=True):
        doc = raw["document"]
        projected: dict = {
            "id": rec["id"],
            "edition": EDITION_BY_DOCUMENT.get(doc["key"]),
            "source": doc["display_name"],
            "publisher": doc["publisher"]["name"],
            "third_party": doc["key"] not in EDITION_BY_DOCUMENT,
            "source_key": raw["key"],
        }
        for field, path in CANDIDATE_CREATURE_FIELDS.items():
            value = _creature_value(raw, path)
            if value is not _MISSING:
                projected[field] = value
        records.append(projected)

    present = [f for f in CANDIDATE_CREATURE_FIELDS if any(f in r for r in records)]
    absent = [f for f in CANDIDATE_CREATURE_FIELDS if f not in present]
    field_bytes = {
        f: sum(len(json.dumps(r[f], ensure_ascii=False).encode("utf-8")) for r in records if f in r)
        for f in present
    }
    size = len(render(records).encode("utf-8"))
    return {
        "dataset": dataset,
        "allowlist": list(allowlist),
        "entries": len(records),
        "dropped": dropped,
        "bytes": size,
        "within_budget": len(records) <= MAX_ENTRIES and size <= MAX_BYTES,
        "fields_present": present,
        "fields_absent": absent,
        "field_bytes": field_bytes,
        "licenses": {key: _license_text(key, documents) for key in allowlist},
    }


def _load_reserved(out_path: Path) -> dict[str, str]:
    """source_key -> id from the previously committed file, so those ids never move."""
    if not out_path.exists():
        return {}
    previous = json.loads(out_path.read_text(encoding="utf-8"))
    return {r["source_key"]: r["id"] for r in previous if "source_key" in r}


def _load_overlays(dataset: str, overlay_path: Path | None) -> list[dict]:
    if overlay_path is None:
        path = OVERLAY_DIR / f"{dataset}.json"
        if not path.exists():
            return []
    else:
        path = overlay_path
    return json.loads(path.read_text(encoding="utf-8"))


def _load_documents(snapshot_dir: Path) -> dict[str, dict] | None:
    path = Path(snapshot_dir) / DOCUMENTS_FILE
    if not path.exists():
        return None
    return {doc["key"]: doc for doc in json.loads(path.read_text(encoding="utf-8"))}


def _license_text(key: str, documents: dict[str, dict]) -> str:
    licenses = (documents.get(key) or {}).get("licenses") or []
    names = [lic["name"] for lic in licenses if lic.get("name")]
    if not names:
        raise ValueError(f"allowlisted document {key!r} has no licenses in {DOCUMENTS_FILE}")
    return "; ".join(names)


def _ogl_documents(keys: list[str], documents: dict[str, dict]) -> list[str]:
    """Every allowlisted document needs a license; returns the keys licensed under OGL 1.0a."""
    return [key for key in keys if _OGL_PATTERN.search(_license_text(key, documents))]


def _read_sections(path: Path) -> dict[str, str]:
    """document key -> section body, from a previously written attribution file."""
    if not path.exists():
        return {}
    parts = _SECTION_MARKER.split(path.read_text(encoding="utf-8"))
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def _render_section(key: str, doc: dict, documents: dict[str, dict]) -> str:
    return "\n".join(
        [
            f"## {doc['display_name']}",
            "",
            f"- Publisher: {doc['publisher']['name']}",
            f"- License: {_license_text(key, documents)}",
            f"- Permalink: {doc['permalink']}",
            f"- Third-party: {'no' if key in EDITION_BY_DOCUMENT else 'yes'}",
        ]
    )


def write_attribution(documents: dict[str, dict], used_keys: list[str], out_path: Path) -> str:
    """Render sections for used_keys; keep sections of other documents as previously written."""
    out_path = Path(out_path)
    sections = _read_sections(out_path)
    for key in set(used_keys):
        sections[key] = _render_section(key, documents[key], documents)
    body = "\n\n".join(f"<!-- document: {key} -->\n{sections[key]}" for key in sorted(sections))
    text = (
        f"# Attribution\n\nGenerated by scripts/ingest_open5e.py. Do not edit by hand.\n\n{body}\n"
    )
    out_path.write_text(text, encoding="utf-8", newline="\n")
    return text


def ingest(
    dataset: str,
    snapshot_dir: Path,
    out_path: Path,
    overlay_path: Path | None = None,
) -> int:
    if dataset not in CONSUMERS:
        raise ValueError(f"{dataset!r} has no consumer in CONSUMERS; not ingesting")
    snapshot_dir = Path(snapshot_dir)
    out_path = Path(out_path)
    entries = json.loads((snapshot_dir / f"{dataset}.json").read_text(encoding="utf-8"))
    allowed = DOCUMENT_ALLOWLIST[dataset]
    records = build_records(
        dataset,
        entries,
        reserved=_load_reserved(out_path),
        overlays=_load_overlays(dataset, overlay_path),
    )
    text = check_budget(records)

    documents = _load_documents(snapshot_dir)
    ogl_keys: list[str] = []
    if documents is None:
        log.warning("ingest.documents_missing", extra={"dataset": dataset, "file": DOCUMENTS_FILE})
    else:
        ogl_keys = _ogl_documents(allowed, documents)
        if ogl_keys and not OGL_LICENSE_SOURCE.exists():
            raise FileNotFoundError(
                f"{', '.join(ogl_keys)} allowlisted under OGL 1.0a but {OGL_LICENSE_SOURCE} is missing"
            )

    out_path.write_text(text, encoding="utf-8", newline="\n")
    if documents is not None:
        kept, _ = filter_allowlisted(entries, allowed)
        used = [e["document"]["key"] for e in kept]
        write_attribution(documents, used, out_path.parent / ATTRIBUTION_FILE)
        if ogl_keys:
            shutil.copyfile(OGL_LICENSE_SOURCE, out_path.parent / OGL_COPY_FILE)
    return len(records)


def main() -> None:
    if not (SNAPSHOT_DIR / DOCUMENTS_FILE).exists():
        raise SystemExit(f"missing dnd_data/{DOCUMENTS_FILE}; run python -m scripts.sync_open5e")
    datasets = sys.argv[1:] or sorted(CONSUMERS)
    for dataset in datasets:
        count = ingest(dataset, SNAPSHOT_DIR, REFERENCE_DIR / f"{dataset}.json")
        print(f"wrote {count} {dataset} entries to app/reference/{dataset}.json")


if __name__ == "__main__":
    main()
