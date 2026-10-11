# services/messages.py

"""Shared session write and snapshot helpers used by REST and WebSocket (PAT-ARCH-001)."""

import copy
import time
from typing import Any
from uuid import uuid4

from app.services.logger import get_logger

logger = get_logger(__name__)


def submit_user_message(
    *, store, inference, session_id: str, payload: dict[str, Any]
) -> tuple[dict[str, Any], bool, bool]:
    """
    Create a user message and enqueue it for inference.

    Returns (message, created, queued). `created` is False for an idempotent hit on
    client_message_id; nothing is created or enqueued then and `queued` is False.
    `queued` is False when the inference queue rejected the job; the message stays stored.
    """
    cid = payload.get("client_message_id")
    if cid:
        existing = store.get_by_client_id(session_id, cid)
        if existing is not None:
            return existing, False, False

    message_id = str(uuid4())
    message = store.create_message(session_id, message_id, payload)
    queued = bool(
        inference.enqueue(
            session_id=session_id,
            message_id=message_id,
            prompt=payload["content"],
            store=store,
        )
    )
    logger.info(
        "message.submitted",
        extra={"session_id": session_id, "message_id": message_id, "queued": queued},
    )
    return message, True, queued


def build_snapshot(store, session_id: str) -> dict[str, Any] | None:
    """
    Return a deep copy of the session's messages, or None if the session is unknown.
    Never creates a session and never exposes the store's live list or dicts.
    """
    messages = store.get_session(session_id)
    if messages is None:
        return None
    return {
        "session_id": session_id,
        "entries": copy.deepcopy(list(messages)),
        "snapshot_at": time.time(),
    }
