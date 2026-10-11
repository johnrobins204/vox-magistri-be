# api/v1/intelligence.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.deps import (
    get_inference_service,
    get_session_store,
    get_tool_service,
)
from app.intelligence.client import IntelligenceError
from app.intelligence.tools import ToolError
from app.schemas.v1 import (
    IntelligenceStatusResp,
    SessionSnapshotResp,
    ToolInvokeReq,
    ToolInvokeResp,
    ToolListResp,
)
from app.services.logger import get_logger
from app.services.messages import build_snapshot
from app.services.tool_service import UnknownToolError

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/intel", tags=["intelligence"])


def _tool_error(status_code: int, message: str, *, detail: str | None = None) -> JSONResponse:
    body = {"text": None, "meta": None, "error": message}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


# ------------------------------------------------------------
# Tool Discovery
# ------------------------------------------------------------
@router.get("/tools", response_model=ToolListResp)
def list_tools(tool_service=Depends(get_tool_service)):
    registry = tool_service.list_tools()
    tools = [{"name": name, "module": module} for name, module in registry.items()]
    return ToolListResp(tools=tools)


# ------------------------------------------------------------
# Tool Invocation
# ------------------------------------------------------------
@router.post("/tools/{tool_name}/invoke", response_model=ToolInvokeResp)
def invoke_tool(
    tool_name: str,
    req: ToolInvokeReq,
    tool_service=Depends(get_tool_service),
):
    try:
        result = tool_service.invoke(tool_name, req.args, client_context=req.context or {})
    except UnknownToolError as exc:
        return _tool_error(404, str(exc), detail=str(exc))
    except ToolError as exc:
        return _tool_error(400, str(exc))
    except IntelligenceError as exc:
        return _tool_error(502, str(exc))
    except Exception as exc:
        logger.exception("Tool %s failed", tool_name)
        return _tool_error(500, str(exc))

    return ToolInvokeResp(text=result["text"], meta=result["meta"], error=None)


# ------------------------------------------------------------
# Intelligence Layer Status
# ------------------------------------------------------------
@router.get("/status", response_model=IntelligenceStatusResp)
def intel_status(inference=Depends(get_inference_service)):
    if inference is None:
        raise HTTPException(status_code=503, detail="Inference service unavailable")

    return IntelligenceStatusResp(
        model_loaded=getattr(inference, "model_loaded", False),
        queue_position=inference.queue_position(None),
        estimated_wait_seconds=inference.estimate_wait(None),
    )


# ------------------------------------------------------------
# Session Snapshot (for React visualization)
# Reads the shared session store, the same one REST and WebSocket write to.
# ------------------------------------------------------------
@router.get("/sessions/{session_id}/snapshot", response_model=SessionSnapshotResp)
def snapshot_session(
    session_id: str,
    session_store=Depends(get_session_store),
):
    snapshot = build_snapshot(session_store, session_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionSnapshotResp(**snapshot)
