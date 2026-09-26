# app/api/v1/session.py (top imports)
from typing import Annotated, Any, List, Optional
from uuid import uuid4

from app.deps import get_inference_service, get_session_store, require_local_token
from app.logger import get_logger
from app.schemas.v1 import MessageCreateReq, MessageResp, SessionCreateResp
from app.types import InferenceService, SessionStore 
from fastapi import APIRouter, Depends, Header, HTTPException, Response, WebSocket, status
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/v1", tags=["sessions"])
logger = get_logger(__name__)


# Configurable limits (tweak in config.py later)
MAX_INPUT_TOKENS = 1024
MAX_QUEUE_RETRY_AFTER = 5  # seconds

router = APIRouter(prefix="/api/v1", tags=["sessions"])


@router.post("/sessions", response_model=SessionCreateResp, status_code=status.HTTP_201_CREATED)
async def create_session(
    response: Response,
    store: Annotated[Any, Depends(get_session_store)],
):
    session_id = str(uuid4())
    store.create_session(session_id)
    response.headers["Location"] = f"/api/v1/sessions/{session_id}"
    logger.info("session.created", extra={"session_id": session_id})
    return SessionCreateResp(session_id=session_id, capabilities={"streaming": True})



@router.get("/sessions/{session_id}/messages", 
            response_model=list[MessageResp], 
            dependencies=[Depends(require_local_token)]
            )
async def list_messages(
    session_id: str,
    store: Annotated[Any, Depends(get_session_store)],
):
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

@router.get(
    "/sessions/{session_id}/messages/{message_id}",
    response_model=MessageResp,
    dependencies=[Depends(require_local_token)],
)

@router.get(
    "/sessions/{session_id}/messages/{message_id}/status",
    dependencies=[Depends(require_local_token)],
)

async def get_message(
    session_id: str,
    message_id: str,
    store: Annotated[SessionStore, Depends(get_session_store)],
):
    session = store.get_session(session_id)
    if session is None:
        logger.debug("get_message: session not found", extra={"session_id": session_id, "message_id": message_id})
        raise HTTPException(status_code=404, detail="Session not found")

    for m in session:
        if m.get("id") == message_id:
            logger.info("get_message: found", extra={"session_id": session_id, "message_id": message_id})
            return m

    logger.debug("get_message: message not found", extra={"session_id": session_id, "message_id": message_id})
    raise HTTPException(status_code=404, detail="Message not found")



@router.get(
    "/sessions/{session_id}/messages/{message_id}/status",
    dependencies=[Depends(require_local_token)],
)
async def get_message_status(
    session_id: str,
    message_id: str,
    store: Annotated[SessionStore, Depends(get_session_store)],
    inference: Annotated[InferenceService, Depends(get_inference_service)],
):
    session = store.get_session(session_id)
    if session is None:
        logger.debug("get_message_status: session not found",
                      extra=
                        {
                          "session_id": session_id, 
                          "message_id": message_id
                        }
                    )
        raise HTTPException(status_code=404, detail="Session not found")

    msg = None
    for m in session:
        if m.get("id") == message_id:
            msg = m
            break

    if msg is None:
        logger.debug("get_message_status: message not found", extra={"session_id": session_id, "message_id": message_id})
        raise HTTPException(status_code=404, detail="Message not found")

    status_val = msg.get("status", "unknown")
    meta = msg.get("meta", {})

    queue_pos = None
    eta_seconds = None
    try:
        queue_pos = inference.queue_position(message_id)
    except Exception:
        queue_pos = None
    try:
        eta_seconds = inference.estimate_wait(message_id)
    except Exception:
        eta_seconds = None

    resp = {
        "message_id": message_id,
        "status": status_val,
        "meta": meta,
    }
    if queue_pos is not None:
        resp["queue_position"] = queue_pos
    if eta_seconds is not None:
        resp["estimated_wait_seconds"] = eta_seconds

    logger.info("get_message_status", 
                extra={
                    "session_id": session_id, 
                    "message_id": message_id, 
                    "status": status_val, 
                    "queue_position": queue_pos
                    }
                )
    return resp



@router.post("/sessions/{session_id}/messages", 
             status_code=status.HTTP_202_ACCEPTED, 
             dependencies=[Depends(require_local_token)]
             )
async def post_message(
    session_id: str,
    payload: MessageCreateReq,
    response: Response,
    store: Annotated[Any, Depends(get_session_store)],
    inference: Annotated[Any, Depends(get_inference_service)],
):
    # Basic session existence check
    if store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Prompt length validation (simple heuristic)
    if len(payload.content) > MAX_INPUT_TOKENS * 4:  # rough char->token heuristic
        raise HTTPException(status_code=400, detail=f"Prompt too long (max ~{MAX_INPUT_TOKENS} tokens)")

    # Idempotency by client_message_id
    if payload.client_message_id:
        existing = store.get_by_client_id(session_id, payload.client_message_id)
        if existing:
            # Return existing message metadata
            return JSONResponse(status_code=200, content={"message_id": existing["id"], "status": existing["status"]})

    # Create message record
    message_id = str(uuid4())
    msg = store.create_message(session_id, message_id, payload.dict())

    # Enqueue; inference.enqueue should return True if queued, False if queue full.
    queued = inference.enqueue(session_id=session_id, message_id=message_id, prompt=payload.content, store=store)
    if not queued:
        # Queue full: inform client to retry later
        return JSONResponse(
            status_code=429,
            content={"status": "queued_full", "retry_after": MAX_QUEUE_RETRY_AFTER, "message_id": message_id},
            headers={"Retry-After": str(MAX_QUEUE_RETRY_AFTER)}
        )

    # Optionally compute queue position if inference exposes it (best-effort)
    queue_pos = getattr(inference, "queue_position", None)
    response.headers["Location"] = f"/api/v1/sessions/{session_id}/messages/{message_id}"
    return {"message_id": message_id, "status": "queued", "queue_position": queue_pos}


@router.websocket("/stream")
async def stream_ws(
    ws: WebSocket,
    authorization: Optional[str] = Header(None),
    session_id: Optional[str] = None,
    store = Depends(get_session_store),
    inference = Depends(get_inference_service),
):
    """
    WebSocket streaming with Authorization header (Bearer token).
    Handshake: client sends {"action":"start","message_id":"...","prompt":"..."}.
    """
    # Validate Authorization header
    if not authorization or not authorization.startswith("Bearer "):
        await ws.close(code=1008)
        return
    token = authorization.split(" ", 1)[1]
    if not inference.validate_token(token):
        await ws.close(code=1008)
        return

    # Optional session check
    if session_id and store.get_session(session_id) is None:
        await ws.close(code=1008)
        return

    await ws.accept()
    try:
        data = await ws.receive_json()
        action = data.get("action")
        if action == "start":
            message_id = data.get("message_id") or str(uuid4())
            prompt = data.get("prompt", "")
            # If session provided, ensure message record exists
            if session_id:
                if store.get_session(session_id) is None:
                    await ws.send_json({"type": "error", "message": "session not found"})
                    await ws.close()
                    return
                # create message record if not present
                if not store.get_by_client_id(session_id, message_id) and not any(m["id"] == message_id for m in store.list_messages(session_id)):
                    store.create_message(session_id, message_id, {"content": "", "role": "assistant"})

            # Stream tokens from inference.generate_tokens
            async for tk in inference.generate_tokens(prompt=prompt, session_id=session_id, message_id=message_id):
                await ws.send_json({"type": "token", "token": tk, "message_id": message_id})
            await ws.send_json({"type": "done", "message_id": message_id})

        elif action == "cancel":
            mid = data.get("message_id")
            inference.cancel(mid)
            await ws.send_json({"type": "cancelled", "message_id": mid})
        else:
            await ws.send_json({"type": "error", "message": f"unknown action {action}"})
    except Exception as exc:
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        await ws.close()
