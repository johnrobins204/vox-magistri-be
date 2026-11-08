"""Apply post-reply mention detection to the world store (SPEC-0019 WP-4, REQ-0028, PAT-ARCH-012).

The worker owns the try/except and logging. This module does the store reads and writes:
bump pending rows that were named again, and create pending rows for new candidates.
Canon and rejected rows are never written; nothing is deleted.
"""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from app.intelligence.world_mentions import detect_mentions
from app.type_defs import WorldStore

_MAX_MESSAGE_IDS = 20
_STOPLIST_KEYS = ("species", "weapons", "rules", "creatures")


def catalog_stoplist(reference: Mapping[str, Any]) -> frozenset[str]:
    """Names of reference catalog entries; a missing catalog key contributes nothing."""
    return frozenset(entry.name for key in _STOPLIST_KEYS for entry in reference.get(key, ()))


def mine_reply(
    world_store: WorldStore,
    *,
    session_id: str,
    reply_id: str,
    text: str,
    stoplist: Iterable[str] = (),
    max_candidates: int = 3,
) -> dict[str, int]:
    """Detect mentions in one reply and apply them; returns matched, proposed and bumped counts."""
    known = world_store.list_entities(session_id)
    detection = detect_mentions(text, known, stoplist, max_candidates)
    matched_ids = set(detection.matched_ids)

    bumped = 0
    for entity in known:
        evidence = entity["evidence"]
        if entity["id"] not in matched_ids or entity["status"] != "pending" or evidence is None:
            continue
        message_ids = list(evidence.get("message_ids", []))
        if reply_id in message_ids or len(message_ids) >= _MAX_MESSAGE_IDS:
            continue
        message_ids.append(reply_id)
        world_store.update_entity(
            entity["id"], {"evidence": {**evidence, "message_ids": message_ids}}
        )
        bumped += 1

    first_seen_at = datetime.now(UTC).isoformat()
    for candidate in detection.candidates:
        world_store.create_entity(
            name=candidate.name,
            kind=candidate.kind,
            status="pending",
            session_id=None,
            evidence={
                "detector": "deterministic",
                "session_id": session_id,
                "source_message_id": reply_id,
                "snippet": candidate.snippet,
                "first_seen_at": first_seen_at,
                "message_ids": [reply_id],
            },
        )

    return {"matched": len(matched_ids), "proposed": len(detection.candidates), "bumped": bumped}
