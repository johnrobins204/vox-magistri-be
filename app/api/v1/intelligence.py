# api/v1/intelligence.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.deps import (
    get_inference_service,
    get_session_store,
    get_tool_service,
)
from app.schemas.v1 import (
    IntelligenceStatusResp,
    SessionSnapshotResp,
    ToolInvokeReq,
    ToolInvokeResp,
    ToolListResp,
)
from app.services.messages import build_snapshot

router = APIRouter(prefix="/api/v1/intel", tags=["intelligence"])


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
        result = tool_service.invoke(tool_name, req.args, req.context or {})
    except Exception as e:
        return ToolInvokeResp(text=None, meta=None, error=str(e))

    # Normalize result
    if isinstance(result, dict):
        return ToolInvokeResp(
            text=result.get("text"),
            meta=result.get("meta"),
            error=result.get("error"),
        )

    return ToolInvokeResp(text=str(result), meta=None, error=None)


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
