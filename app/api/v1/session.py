# app/api/v1/session.py (top imports)
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse

from app.deps import get_inference_service, get_session_store, require_local_token
from app.schemas.v1 import MessageCreateReq, MessageResp, SessionCreateResp
from app.services.logger import get_logger
from app.services.messages import submit_user_message
from app.type_defs import InferenceService, SessionStore

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


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageResp],
    dependencies=[Depends(require_local_token)],
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
async def get_message(
    session_id: str,
    message_id: str,
    store: Annotated[SessionStore, Depends(get_session_store)],
):
    session = store.get_session(session_id)
    if session is None:
        logger.debug(
            "get_message: session not found",
            extra={"session_id": session_id, "message_id": message_id},
        )
        raise HTTPException(status_code=404, detail="Session not found")

    for m in session:
        if m.get("id") == message_id:
            logger.info(
                "get_message: found",
                extra={"session_id": session_id, "message_id": message_id},
            )
            return m

    logger.debug(
        "get_message: message not found",
        extra={"session_id": session_id, "message_id": message_id},
    )
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
        logger.debug(
            "get_message_status: session not found",
            extra={"session_id": session_id, "message_id": message_id},
        )
        raise HTTPException(status_code=404, detail="Session not found")

    msg = None
    for m in session:
        if m.get("id") == message_id:
            msg = m
            break

    if msg is None:
        logger.debug(
            "get_message_status: message not found",
            extra={"session_id": session_id, "message_id": message_id},
        )
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

    logger.info(
        "get_message_status",
        extra={
            "session_id": session_id,
            "message_id": message_id,
            "status": status_val,
            "queue_position": queue_pos,
        },
    )

    return resp


@router.post(
    "/sessions/{session_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_local_token)],
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
        raise HTTPException(
            status_code=400, detail=f"Prompt too long (max ~{MAX_INPUT_TOKENS} tokens)"
        )

    # Idempotency, message creation and enqueue are shared with the WS transport (PAT-ARCH-001).
    message, created, queued = submit_user_message(
        store=store, inference=inference, session_id=session_id, payload=payload.dict()
    )
    if not created:
        # Idempotent hit on client_message_id: return existing message metadata
        return JSONResponse(
            status_code=200,
            content={"message_id": message["id"], "status": message["status"]},
        )

    if not queued:
        # Queue full: inform client to retry later
        return JSONResponse(
            status_code=429,
            content={
                "status": "queued_full",
                "retry_after": MAX_QUEUE_RETRY_AFTER,
                "message_id": message["id"],
            },
            headers={"Retry-After": str(MAX_QUEUE_RETRY_AFTER)},
        )

    # Optionally compute queue position if inference exposes it (best-effort)
    queue_pos = inference.queue_position(message["id"])
    response.headers["Location"] = f"/api/v1/sessions/{session_id}/messages/{message['id']}"
    return {"message_id": message["id"], "status": "queued", "queue_position": queue_pos}
