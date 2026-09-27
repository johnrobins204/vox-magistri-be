# api/v1/ws.py
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from typing import Any

from app.deps import (
    get_inference_service,
    get_session_store,
)
from app.services.session_service import SessionService


router = APIRouter(prefix="/api/v1/ws", tags=["websocket"])


# ------------------------------------------------------------
# Utility: send JSON safely
# ------------------------------------------------------------
async def ws_send(ws: WebSocket, payload: dict[str, Any]):
    try:
        await ws.send_json(payload)
    except Exception:
        # Client disconnected or network issue
        pass


# ------------------------------------------------------------
# Main WebSocket: Live session updates + token streaming
# ------------------------------------------------------------
@router.websocket("/sessions/{run_id}")
async def ws_session(
    ws: WebSocket,
    run_id: int,
    session_store=Depends(get_session_store),
    inference=Depends(get_inference_service),
):
    await ws.accept()

    # Wrap your existing SessionService around the repo
    svc = SessionService(repos={"session": session_store})

    # Send initial snapshot
    snapshot = svc.snapshot_run(run_id)
    await ws_send(ws, {
        "type": "snapshot",
        "run_id": snapshot["run_id"],
        "entries": snapshot["entries"],
        "snapshot_at": snapshot["snapshot_at"],
    })

    try:
        while True:
            # Wait for client messages (React may send commands)
            data = await ws.receive_json()

            action = data.get("action")

            # ------------------------------------------------------------
            # Client requests: append user message
            # ------------------------------------------------------------
            if action == "user_message":
                text = data.get("text", "")
                entry = svc.append_entry(run_id, "You", text)
                await ws_send(ws, {"type": "entry", "entry": entry})

                # If inference is available, stream tokens
                if inference:
                    async for tk in inference.generate_tokens(
                        prompt=text,
                        session_id=None,
                        message_id=str(entry["id"]),
                    ):
                        await ws_send(ws, {
                            "type": "token",
                            "token": tk,
                            "message_id": entry["id"],
                        })

                    await ws_send(ws, {
                        "type": "done",
                        "message_id": entry["id"],
                    })

            # ------------------------------------------------------------
            # Client requests: fetch queue status
            # ------------------------------------------------------------
            elif action == "status":
                pos = inference.queue_position(None) if inference else None
                eta = inference.estimate_wait(None) if inference else None
                await ws_send(ws, {
                    "type": "status",
                    "queue_position": pos,
                    "estimated_wait_seconds": eta,
                })

            # ------------------------------------------------------------
            # Unknown action
            # ------------------------------------------------------------
            else:
                await ws_send(ws, {
                    "type": "error",
                    "message": f"Unknown action: {action}",
                })

    except WebSocketDisconnect:
        # Client disconnected gracefully
        return
    except Exception as exc:
        await ws_send(ws, {"type": "error", "message": str(exc)})
        return
