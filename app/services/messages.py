# services/messages.py

"""Shared session write and snapshot helpers used by REST and WebSocket (PAT-ARCH-001)."""

import copy
import time
from typing import Any
from uuid import uuid4

from app.intelligence.tool_handler import detect_tool, message_kind
from app.services.logger import get_logger

logger = get_logger(__name__)

# Shared by REST and WebSocket so both transports enforce the same rules.
MAX_INPUT_CHARS = 4096
# `kind` is computed at save time from the slash parse (PAT-ARCH-013); clients cannot set it.
RESERVED_META_KEYS = frozenset(
    {"reply_to", "tool", "updated_by", "error", "revisions", "kind", "narrative_only"}
)


def _clean_user_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Client text is always a user message; clients cannot set server-owned meta keys."""
    meta = {k: v for k, v in (payload.get("meta") or {}).items() if k not in RESERVED_META_KEYS}
    return {**payload, "role": "user", "meta": meta}


def submit_user_message(
    *, store, inference, session_id: str, payload: dict[str, Any]
) -> tuple[dict[str, Any], bool, bool]:
    """
    Create a user message and enqueue it for inference.

    Returns (message, created, queued). `created` is False for an idempotent hit on
    client_message_id; nothing is created or enqueued then and `queued` is False.
    `queued` is False when the inference queue rejected the job; the message stays stored.
    """
    payload = _clean_user_payload(payload)
    payload["meta"]["kind"] = message_kind(detect_tool(payload["content"])[0])
    if payload.get("narrative_only") is True:
        payload["meta"]["narrative_only"] = True

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


def find_reply(store, session_id: str, user_message_id: str) -> dict[str, Any] | None:
    for m in store.list_messages(session_id):
        reply_to = (m.get("meta") or {}).get("reply_to")
        if m.get("role") == "assistant" and reply_to == user_message_id:
            return copy.deepcopy(m)
    return None


class CorrectionError(Exception):
    """A rejected correction; the transport maps status_code and detail to an HTTP error."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# A user message whose reply is still being produced (PAT-ARCH-010 rule 4).
_IN_FLIGHT = frozenset({"queued", "running"})


def _require_message(store, session_id: str, message_id: str) -> dict[str, Any]:
    if store.get_session(session_id) is None:
        raise CorrectionError(404, "Session not found")
    message = store.get_message(session_id, message_id)
    if message is None:
        raise CorrectionError(404, "Message not found")
    return message


def _source_of(store, session_id: str, reply: dict[str, Any]) -> dict[str, Any] | None:
    reply_to = (reply.get("meta") or {}).get("reply_to")
    if not reply_to:
        return None
    return store.get_message(session_id, reply_to)


def correct_message(
    *,
    store,
    session_id: str,
    message_id: str,
    content: str | None = None,
    canon: bool | None = None,
) -> dict[str, Any]:
    """Edit an assistant reply's content and/or set canon on any message (ADR-0011)."""
    message = _require_message(store, session_id, message_id)
    if content is None and canon is None:
        raise CorrectionError(400, "Nothing to update")
    if content is not None:
        if message["role"] != "assistant":
            raise CorrectionError(400, "Only assistant replies can be edited")
        if not content.strip():
            raise CorrectionError(400, "content is required")
        if len(content) > MAX_INPUT_CHARS:
            raise CorrectionError(400, f"content too long (max {MAX_INPUT_CHARS} characters)")
        source = _source_of(store, session_id, message)
        if source is not None and source["status"] in _IN_FLIGHT:
            raise CorrectionError(409, "Reply is being regenerated")
    updated = store.update_message(
        session_id, message_id, content=content, canon=canon, reason="edit"
    )
    logger.info(
        "message.corrected",
        extra={
            "session_id": session_id,
            "message_id": message_id,
            "edited": content is not None,
            "canon": canon,
        },
    )
    return updated


def regenerate_reply(
    *, store, inference, session_id: str, reply_id: str
) -> tuple[dict[str, Any], bool]:
    """Re-enqueue the source user message; the worker revises its reply in place (PAT-ARCH-010)."""
    reply = _require_message(store, session_id, reply_id)
    if reply["role"] != "assistant":
        raise CorrectionError(400, "Only assistant replies can be regenerated")
    user = _source_of(store, session_id, reply)
    if user is None:
        raise CorrectionError(400, "Reply has no source message")
    if user["status"] in _IN_FLIGHT:
        raise CorrectionError(409, "Reply is being regenerated")
    queued = bool(
        inference.enqueue(
            session_id=session_id,
            message_id=user["id"],
            prompt=user["content"],
            store=store,
        )
    )
    if not queued:
        # enqueue marked the source queued and then error (queue full); nothing ran, so put back
        # the status and error it had before. Writing the prior error (None if none) clears the text.
        store.update_message_status(
            session_id,
            user["id"],
            user["status"],
            meta={"error": (user.get("meta") or {}).get("error")},
        )
    logger.info(
        "message.regenerate_requested",
        extra={
            "session_id": session_id,
            "message_id": reply_id,
            "user_message_id": user["id"],
            "queued": queued,
        },
    )
    return user, queued
