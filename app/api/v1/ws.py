# api/v1/ws.py
"""The single session WebSocket (SPEC-0004 WP-4; PAT-ARCH-001: a thin adapter).

Messages go through the shared store and helper (`app.services.messages`); the inference
worker writes the reply, and this module only reads it back from the store.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import time
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from app.config import get_settings
from app.deps import get_inference_service, get_session_store
from app.services.logger import get_logger
from app.services.messages import (
    MAX_INPUT_CHARS,
    CorrectionError,
    build_snapshot,
    find_reply,
    regenerate_reply,
    submit_user_message,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/ws", tags=["websocket"])

TERMINAL_STATUSES = {"completed", "error", "cancelled"}
WS_POLL_INTERVAL_SECONDS = 0.05
WS_REPLY_MARGIN_SECONDS = 10.0


def _reply_timeout_seconds(inference) -> float:
    per_job = float(get_settings().ollama.timeout_seconds) + WS_REPLY_MARGIN_SECONDS
    waiting = inference.queue_position(None) or 0
    # waiting jobs (including ours) plus one that may already be running
    return per_job * (waiting + 1)


async def ws_send(ws: WebSocket, payload: dict[str, Any]) -> None:
    # Stored messages hold datetimes; jsonable_encoder makes them JSON-safe.
    # Errors are not swallowed: a disconnect reaches the handler's outer except, anything
    # else is a bug and propagates.
    await ws.send_json(jsonable_encoder(copy.deepcopy(payload)))


async def _send_error(ws: WebSocket, message: str, message_id: str | None = None) -> None:
    event: dict[str, Any] = {"type": "error", "message": message}
    if message_id is not None:
        event["message_id"] = message_id
    await ws_send(ws, event)


async def _wait_for_terminal(
    store, session_id: str, message_id: str, timeout: float
) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while True:
        m = store.get_message(session_id, message_id)
        if m is not None and m.get("status") in TERMINAL_STATUSES:
            return m
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(WS_POLL_INTERVAL_SECONDS)


async def _handle_user_message(
    ws: WebSocket, store, inference, session_id: str, data: dict[str, Any]
) -> None:
    """
    Handle a `user_message` action.

    Optional `narrative_only` (bool, default false) asks for a narrative-only reply; it is
    stored server-side as `meta.narrative_only` on the user row. Any non-bool value is
    rejected with an error before anything is stored.
    """
    # Validate before anything is stored; each failure reports an error and keeps the socket.
    if inference is None:
        await _send_error(ws, "Inference service unavailable")
        return
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        await _send_error(ws, "text is required")
        return
    if len(text) > MAX_INPUT_CHARS:
        await _send_error(ws, f"text too long (max {MAX_INPUT_CHARS} characters)")
        return
    client_message_id = data.get("client_message_id")
    if client_message_id is not None and not isinstance(client_message_id, str):
        await _send_error(ws, "client_message_id must be a string")
        return
    narrative_only = data.get("narrative_only", False)
    if not isinstance(narrative_only, bool):
        await _send_error(ws, "narrative_only must be a boolean")
        return

    message, created, queued = submit_user_message(
        store=store,
        inference=inference,
        session_id=session_id,
        payload={
            "client_message_id": client_message_id,
            "role": "user",
            "content": text,
            "meta": None,
            "narrative_only": narrative_only,
        },
    )
    await ws_send(ws, {"type": "entry", "entry": message})

    if created and not queued:
        await _send_error(ws, "Inference queue full; try again later", message_id=message["id"])
        return

    await _await_reply(ws, store, inference, session_id, message)


async def _handle_regenerate(
    ws: WebSocket, store, inference, session_id: str, data: dict[str, Any]
) -> None:
    # Same validation-first shape as user_message; the worker revises the reply in place.
    if inference is None:
        await _send_error(ws, "Inference service unavailable")
        return
    message_id = data.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        await _send_error(ws, "message_id is required")
        return

    try:
        user, queued = regenerate_reply(
            store=store, inference=inference, session_id=session_id, reply_id=message_id
        )
    except CorrectionError as exc:
        await _send_error(ws, exc.detail)
        return

    if not queued:
        await _send_error(ws, "Inference queue full; try again later", message_id=user["id"])
        return

    await ws_send(ws, {"type": "entry", "entry": user})
    await _await_reply(ws, store, inference, session_id, user)


async def _await_reply(
    ws: WebSocket, store, inference, session_id: str, user_message: dict[str, Any]
) -> None:
    """Wait for the worker to finish `user_message`; then send its reply and `done`, or `error`."""
    user_id = user_message["id"]
    final = await _wait_for_terminal(store, session_id, user_id, _reply_timeout_seconds(inference))
    if final is None:
        await _send_error(ws, "Timed out waiting for reply", message_id=user_id)
        return

    status = final["status"]
    if status == "completed":
        reply = find_reply(store, session_id, user_id)
        if reply is None:
            logger.error(
                "ws.reply.missing",
                extra={"session_id": session_id, "message_id": user_id},
            )
            await _send_error(ws, "Reply not found", message_id=user_id)
            return
        await ws_send(ws, {"type": "entry", "entry": reply})
        await ws_send(
            ws,
            {"type": "done", "message_id": user_id, "reply_id": reply["id"]},
        )
    elif status == "error":
        error_text = (final.get("meta") or {}).get("error") or "Inference failed"
        await _send_error(ws, error_text, message_id=user_id)
    elif status == "cancelled":
        await _send_error(ws, "cancelled", message_id=user_id)


@router.websocket("/sessions/{session_id}")
async def ws_session(
    ws: WebSocket,
    session_id: str,
    session_store=Depends(get_session_store),
    inference=Depends(get_inference_service),
):
    # Unknown sessions are rejected before accept(); nothing is auto-created.
    if session_store.get_session(session_id) is None:
        await ws.close(code=1008)
        return

    try:
        await ws.accept()
        await ws_send(ws, {"type": "snapshot", **build_snapshot(session_store, session_id)})

        while True:
            try:
                data = await ws.receive_json()
            except ValueError:
                # Malformed frame (JSONDecodeError is a ValueError): report it, keep the socket.
                await _send_error(ws, "Expected a JSON object")
                continue
            if not isinstance(data, dict):
                await _send_error(ws, "Expected a JSON object")
                continue

            action = data.get("action")
            if action == "user_message":
                await _handle_user_message(ws, session_store, inference, session_id, data)
            elif action == "regenerate":
                await _handle_regenerate(ws, session_store, inference, session_id, data)
            elif action == "status":
                queue_position = None
                estimated_wait = None
                if inference is not None:
                    queue_position = inference.queue_position(None)
                    estimated_wait = inference.estimate_wait(None)
                await ws_send(
                    ws,
                    {
                        "type": "status",
                        "queue_position": queue_position,
                        "estimated_wait_seconds": estimated_wait,
                    },
                )
            else:
                await _send_error(ws, f"Unknown action: {action}")

    except WebSocketDisconnect:
        # Client went away; nothing to report.
        return
    except Exception:
        logger.exception("ws.session.failed", extra={"session_id": session_id})
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await ws.close(code=1011)
        return
