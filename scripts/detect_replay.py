"""Read-only replay of the mention detector over stored canon replies (SPEC-0019 WP-7, REQ-0028).

Run from the repo root: python -m scripts.detect_replay COPY.db [--max-candidates N]
Copy the database first (cp dnd.db /tmp/dnd-copy.db). The repo-root dnd.db is refused and the
file is opened with mode=ro and PRAGMA query_only, so nothing is written. Prints the candidates
of each reply that produced one, then a summary and the manual M-1 rule.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.intelligence.world_mentions import detect_mentions
from app.reference.creatures import CREATURES_PATH, Creature
from app.reference.loader import load_entries
from app.reference.rules import RULES_PATH, Rule
from app.reference.species import load_species
from app.reference.weapons import WEAPONS_PATH, Weapon
from app.services.world_mining import catalog_stoplist

ROOT = Path(__file__).resolve().parents[1]
REPO_DB = ROOT / "dnd.db"
M1_RULE = (
    "M-1: label each candidate real or not. Default-on stays only if real >= 50% and mean <= "
    "1.5 candidates per scanned reply; otherwise tune the stoplist or cap, add a regression "
    "case to tests/test_world_mentions.py, and re-run."
)


class ReplayRefused(ValueError):
    """The path cannot be replayed; the message is the reason shown to the operator."""


def _reference_stoplist() -> frozenset[str]:
    # Same catalogs build_services loads for the worker's stop list.
    reference = {
        "species": load_species(),
        "weapons": load_entries(WEAPONS_PATH, Weapon, "weapons"),
        "rules": load_entries(RULES_PATH, Rule, "rules"),
        "creatures": load_entries(CREATURES_PATH, Creature, "creatures"),
    }
    return catalog_stoplist(reference)


def _db_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved == REPO_DB.resolve():
        raise ReplayRefused("refusing the repo-root dnd.db; replay a copy (cp dnd.db /tmp/x.db)")
    if not resolved.is_file():
        raise ReplayRefused(f"no such database file: {resolved}")
    return resolved


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _scan(conn: sqlite3.Connection, max_candidates: int, stoplist: frozenset[str]) -> list[dict]:
    tables = _tables(conn)
    if "messages" not in tables:
        raise ReplayRefused("not a session store: no messages table")
    message_cols = _columns(conn, "messages")
    canon_clause = " AND (canon IS NULL OR canon <> 0)" if "canon" in message_cols else ""
    replies = conn.execute(
        "SELECT seq, session_id, id, content, meta FROM messages "
        "WHERE role = 'assistant' AND status = 'completed'" + canon_clause + " ORDER BY seq"
    ).fetchall()

    characters: dict[str, str] = {}
    if "character" in _columns(conn, "sessions"):
        for session_id, character_text in conn.execute("SELECT id, character FROM sessions"):
            name = (json.loads(character_text) or {}).get("name") if character_text else None
            if name:
                characters[session_id] = name

    # Known entities: stored rows (global or per session), then candidates proposed in this run.
    # A proposed candidate is a global pending row in production, so later replies see it.
    known: list[dict[str, Any]] = []
    if "world_entities" in tables:
        for row in conn.execute("SELECT id, session_id, name, aliases FROM world_entities"):
            known.append(
                {
                    "id": row[0],
                    "session_id": row[1],
                    "name": row[2],
                    "aliases": json.loads(row[3] or "[]"),
                }
            )

    results: list[dict] = []
    for seq, session_id, message_id, content, meta_text in replies:
        meta = json.loads(meta_text or "{}")
        if meta.get("tool") not in (None, "narrate"):
            continue
        visible = [k for k in known if k["session_id"] in (None, session_id)]
        stop = set(stoplist)
        if session_id in characters:
            stop.add(characters[session_id])
        detection = detect_mentions(content or "", visible, stop, max_candidates)
        for candidate in detection.candidates:
            known.append(
                {
                    "id": f"proposed-{len(known)}",
                    "session_id": None,
                    "name": candidate.name,
                    "aliases": [],
                }
            )
        results.append(
            {
                "seq": seq,
                "message_id": message_id,
                "session_id": session_id,
                "matched": len(detection.matched_ids),
                "candidates": [
                    {
                        "name": c.name,
                        "kind": c.kind,
                        "snippet": c.snippet,
                        "count": c.count,
                    }
                    for c in detection.candidates
                ],
            }
        )
    return results


def replay(path: str | Path, max_candidates: int | None = None) -> list[dict[str, Any]]:
    """One dict per scanned reply (seq, message_id, session_id, matched, candidates), in seq order.

    Raises ReplayRefused for the repo-root dnd.db or a missing or non-store file. The database
    is opened read-only; nothing is written.
    """
    db = _db_path(path)
    if max_candidates is None:
        max_candidates = get_settings().world.max_candidates_per_reply
    stoplist = _reference_stoplist()
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        return _scan(conn, max_candidates, stoplist)
    finally:
        conn.close()


def _print_report(results: list[dict]) -> None:
    total = 0
    most = 0
    for reply in results:
        found = reply["candidates"]
        total += len(found)
        most = max(most, len(found))
        if not found:
            continue
        print(
            f"reply seq={reply['seq']} message={reply['message_id']} "
            f"session={reply['session_id']} candidates={len(found)} matched={reply['matched']}"
        )
        for c in found:
            print(f'  + {c["name"]} [{c["kind"]}] "{c["snippet"]}"')
    scanned = len(results)
    mean = total / scanned if scanned else 0.0
    print(f"summary: replies scanned={scanned} candidates={total} " f"mean={mean:.2f} max={most}")
    print(M1_RULE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", metavar="PATH", help="a copy of the session database")
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        metavar="N",
        help="cap per reply (default: settings world.max_candidates_per_reply)",
    )
    args = parser.parse_args(argv)
    if args.max_candidates is not None and args.max_candidates < 0:
        parser.error("--max-candidates must be >= 0")
    try:
        results = replay(args.path, args.max_candidates)
    except ReplayRefused as exc:
        print(f"detect_replay: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        print(f"detect_replay: cannot read {args.path}: {exc}", file=sys.stderr)
        return 2
    _print_report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
