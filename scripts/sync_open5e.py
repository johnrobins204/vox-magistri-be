"""Sync open5e bulk snapshots into gitignored dnd_data/ and write _manifest.json (SPEC-0012 WP-1).

Run from the repo root on demand: python -m scripts.sync_open5e
The app never calls open5e at runtime; this script is the only network user.
"""

import json
import os
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx

from app.services.logger import get_logger

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://api.open5e.com"
ENDPOINTS = frozenset(
    {
        "armor",
        "backgrounds",
        "classes",
        "conditions",
        "creatures",
        "feats",
        "magicitems",
        "rules",
        "sections",
        "species",
        "spells",
        "weapons",
    }
)
API_VERSIONS = {"sections": "v1"}  # v2 has no sections endpoint; v1 uses the same envelope
DEFAULT_API_VERSION = "v2"
DOCUMENTS_PATH = "/v2/documents/"
DOCUMENTS_FILE = "_documents.json"
MANIFEST_FILE = "_manifest.json"
MANIFEST_VERSION = "1.0"
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0
TIMEOUT_SECONDS = 60.0
DATASET_DEADLINE_SECONDS = 15 * 60  # creatures takes ~4 min; trickling stalls must fail loud
PAGE_SIZE = 50  # bare URLs without query params return HTML; limit=100 returns HTML for documents

log = get_logger(__name__)


class SyncError(RuntimeError):
    """open5e could not be read after bounded retries."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _get(client: httpx.Client, url: str) -> dict:
    problem = "no attempts"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        resp = client.get(url)
        if resp.status_code == 429 or resp.status_code >= 500:
            problem = f"status {resp.status_code}"
            log.warning(
                "open5e %s returned %s (attempt %d of %d)", url, problem, attempt, MAX_ATTEMPTS
            )
        elif resp.status_code >= 400:
            raise SyncError(f"{url} returned {resp.status_code}")
        else:
            try:
                return resp.json()
            except ValueError:
                problem = f"content-type {resp.headers.get('content-type', 'none')}"
                log.warning(
                    "open5e %s returned non-JSON %s (attempt %d of %d)",
                    url,
                    problem,
                    attempt,
                    MAX_ATTEMPTS,
                )
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise SyncError(f"{url} failed after {MAX_ATTEMPTS} attempts (last: {problem})")


def _dataset_path(name: str) -> str:
    return f"/{API_VERSIONS.get(name, DEFAULT_API_VERSION)}/{name}/"


def _fetch_all(
    client: httpx.Client, path: str, dataset: str, clock: Callable[[], float]
) -> list[dict]:
    """Collect every result across pages, following the `next` URL until it is null."""
    started = clock()
    url: str | None = f"{BASE_URL}{path}?limit={PAGE_SIZE}"
    results: list[dict] = []
    while url:
        payload = _get(client, url)
        if clock() - started > DATASET_DEADLINE_SECONDS:
            raise SyncError(f"{dataset} exceeded {DATASET_DEADLINE_SECONDS}s deadline")
        results.extend(payload["results"])
        url = urljoin(url, payload["next"]) if payload.get("next") else None
    return results


def _write_json_atomic(path: Path, data: object) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _load_previous_records(output_dir: Path) -> dict[str, dict]:
    """Keep manifest records for files still on disk, so files not re-synced stay accounted for."""
    path = output_dir / MANIFEST_FILE
    if not path.exists():
        return {}
    try:
        files = json.loads(path.read_text(encoding="utf-8"))["files"]
        return {r["file"]: r for r in files if (output_dir / r["file"]).exists()}
    except Exception:
        log.exception("ignoring unreadable %s", path)
        return {}


def _write_manifest(output_dir: Path, synced_at: str, records: dict[str, dict]) -> dict:
    manifest = {
        "version": MANIFEST_VERSION,
        "synced_at": synced_at,
        "files": sorted(records.values(), key=lambda r: r["file"]),
    }
    _write_json_atomic(output_dir / MANIFEST_FILE, manifest)
    return manifest


def sync(
    output_dir: Path,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Fetch documents and every dataset in ENDPOINTS into output_dir; return the manifest."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    synced_at = _now()
    records = _load_previous_records(output_dir)

    with httpx.Client(
        transport=transport, timeout=TIMEOUT_SECONDS, follow_redirects=True
    ) as client:
        documents = _fetch_all(client, DOCUMENTS_PATH, "documents", clock)
        _write_json_atomic(output_dir / DOCUMENTS_FILE, documents)
        records[DOCUMENTS_FILE] = _record("documents", DOCUMENTS_PATH, DOCUMENTS_FILE, documents)
        _write_manifest(output_dir, synced_at, records)
        log.info("synced documents: %d entries", len(documents))

        for name in sorted(ENDPOINTS):
            path = _dataset_path(name)
            entries = _fetch_all(client, path, name, clock)
            file_name = f"{name}.json"
            _write_json_atomic(output_dir / file_name, entries)
            records[file_name] = _record(name, path, file_name, entries)
            _write_manifest(output_dir, synced_at, records)
            log.info("synced %s: %d entries", name, len(entries))

    return _write_manifest(output_dir, synced_at, records)


def _record(dataset: str, path: str, file_name: str, entries: list[dict]) -> dict:
    return {
        "dataset": dataset,
        "endpoint": f"{BASE_URL}{path}",
        "file": file_name,
        "count": len(entries),
        "fetched_at": _now(),
    }


def main() -> None:
    out_dir = ROOT / "dnd_data"
    manifest = sync(out_dir)
    total = sum(record["count"] for record in manifest["files"])
    print(f"synced {len(manifest['files'])} files, {total} entries into dnd_data/")


if __name__ == "__main__":
    main()
