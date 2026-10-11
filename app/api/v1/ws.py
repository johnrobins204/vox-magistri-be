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
from app.services.messages import build_snapshot, submit_user_message

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/ws", tags=["websocket"])

TERMINAL_STATUSES = {"completed", "error", "cancelled"}
WS_POLL_INTERVAL_SECONDS = 0.05
WS_REPLY_MARGIN_SECONDS = 10.0


def _reply_timeout_seconds() -> float:
    return float(get_settings().ollama.timeout_seconds) + WS_REPLY_MARGIN_SECONDS


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
        for m in store.list_messages(session_id):
            if m.get("id") == message_id and m.get("status") in TERMINAL_STATUSES:
                return copy.deepcopy(m)
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(WS_POLL_INTERVAL_SECONDS)


def _find_reply(store, session_id: str, user_message_id: str) -> dict[str, Any] | None:
    for m in store.list_messages(session_id):
        reply_to = (m.get("meta") or {}).get("reply_to")
        if m.get("role") == "assistant" and reply_to == user_message_id:
            return copy.deepcopy(m)
    return None


async def _handle_user_message(
    ws: WebSocket, store, inference, session_id: str, data: dict[str, Any]
) -> None:
    # Validate before anything is stored; each failure reports an error and keeps the socket.
    if inference is None:
        await _send_error(ws, "Inference service unavailable")
        return
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        await _send_error(ws, "text is required")
        return
    client_message_id = data.get("client_message_id")
    if client_message_id is not None and not isinstance(client_message_id, str):
        await _send_error(ws, "client_message_id must be a string")
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
        },
    )
    await ws_send(ws, {"type": "entry", "entry": message})

    if created and not queued:
        await _send_error(ws, "Inference queue full; try again later", message_id=message["id"])
        return

    final = await _wait_for_terminal(store, session_id, message["id"], _reply_timeout_seconds())
    if final is None:
        await _send_error(ws, "Timed out waiting for reply", message_id=message["id"])
        return

    status = final["status"]
    if status == "completed":
        reply = _find_reply(store, session_id, message["id"])
        if reply is None:
            logger.error(
                "ws.reply.missing",
                extra={"session_id": session_id, "message_id": message["id"]},
            )
            await _send_error(ws, "Reply not found", message_id=message["id"])
            return
        await ws_send(ws, {"type": "entry", "entry": reply})
        await ws_send(
            ws,
            {"type": "done", "message_id": message["id"], "reply_id": reply["id"]},
        )
    elif status == "error":
        error_text = (final.get("meta") or {}).get("error") or "Inference failed"
        await _send_error(ws, error_text, message_id=message["id"])
    elif status == "cancelled":
        await _send_error(ws, "cancelled", message_id=message["id"])


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
