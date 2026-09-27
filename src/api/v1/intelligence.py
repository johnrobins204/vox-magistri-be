# api/v1/intelligence.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from typing import Any

from app.schemas.v1 import (
    ToolListResp,
    ToolInvokeReq,
    ToolInvokeResp,
    IntelligenceStatusResp,
    SessionSnapshotResp,
)
from app.deps import (
    get_tool_service,
    get_inference_service,
    get_session_store,
)
from app.services.session_service import SessionService


router = APIRouter(prefix="/api/v1/intel", tags=["intelligence"])


# ------------------------------------------------------------
# Tool Discovery
# ------------------------------------------------------------
@router.get("/tools", response_model=ToolListResp)
def list_tools(tool_service=Depends(get_tool_service)):
    registry = tool_service.list_tools()
    tools = [
        {"name": name, "module": module}
        for name, module in registry.items()
    ]
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
# ------------------------------------------------------------
@router.get("/sessions/{run_id}/snapshot", response_model=SessionSnapshotResp)
def snapshot_session(
    run_id: int,
    session_store=Depends(get_session_store),
):
    # Wrap your existing SessionService around the repo
    svc = SessionService(repos={"session": session_store})

    snapshot = svc.snapshot_run(run_id)
    return SessionSnapshotResp(
        run_id=snapshot["run_id"],
        entries=snapshot["entries"],
        snapshot_at=snapshot["snapshot_at"],
    )
