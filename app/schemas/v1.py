from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, constr

# ============================================================
# Existing Models (Preserved Exactly As-Is)
# ============================================================

class SessionCreateResp(BaseModel):
    session_id: str = Field(..., description="Server-generated session identifier")
    capabilities: dict[str, Any] = Field(
        default_factory=dict, description="Capabilities supported by this session"
    )

    class Config:
        schema_extra = {
            "example": {"session_id": "b3f1c2d4-...", "capabilities": {"streaming": True}}
        }


ContentStr = constr(min_length=1, max_length=16384)


class MessageCreateReq(BaseModel):
    client_message_id: str | None = Field(
        None, description="Optional client-provided id for idempotency"
    )
    role: str | None = Field("user", description="Role of the author (user/system/assistant)")
    content: str = Field(
        ..., min_length=1, max_length=16384,
        description="Message text/prompt to be processed"
    )
    meta: dict[str, Any] | None = Field(None, description="Optional structured metadata")

    class Config:
        schema_extra = {
            "example": {
                "client_message_id": "client-123",
                "role": "user",
                "content": "Describe a goblin ambush in two sentences.",
                "meta": {"tone": "grimdark"},
            }
        }


class MessageResp(BaseModel):
    id: str = Field(..., description="Server-generated message id")
    client_message_id: str | None = Field(None, description="Client id if provided")
    role: str | None = Field(None, description="Role of the author")
    content: str | None = Field(None, description="Final or partial content")
    status: str = Field(..., description="Message status: queued|in_progress|done|error|cancelled")
    meta: dict[str, Any] | None = Field(None, description="Optional structured metadata")
    created_at: datetime | None = Field(None, description="Creation timestamp (UTC)")
    updated_at: datetime | None = Field(None, description="Last update timestamp (UTC)")

    class Config:
        orm_mode = True
        schema_extra = {
            "example": {
                "id": "a1b2c3d4-...",
                "client_message_id": "client-123",
                "role": "assistant",
                "content": "A band of goblins springs from the underbrush...",
                "status": "done",
                "meta": {"length_tokens": 42},
                "created_at": "2026-09-26T12:34:56Z",
                "updated_at": "2026-09-26T12:35:10Z",
            }
        }


class MessageStatusResp(BaseModel):
    message_id: str = Field(..., description="Server-generated message id")
    status: str = Field(..., description="Message status: queued|in_progress|done|error|cancelled")
    meta: dict[str, Any] | None = Field(None, description="Optional structured metadata")
    queue_position: int | None = Field(None, description="Best-effort queue position")
    estimated_wait_seconds: float | None = Field(None, description="Best-effort ETA in seconds")

    class Config:
        schema_extra = {
            "example": {
                "message_id": "a1b2c3d4-...",
                "status": "queued",
                "meta": {"priority": "normal"},
                "queue_position": 3,
                "estimated_wait_seconds": 12.5,
            }
        }


class MessageListResp(BaseModel):
    messages: list[MessageResp]
    next_cursor: str | None = Field(None, description="Cursor for next page (opaque)")
    total: int | None = Field(None, description="Optional total count (if available)")

    class Config:
        schema_extra = {
            "example": {
                "messages": [
                    {
                        "id": "a1b2c3d4-...",
                        "client_message_id": "client-123",
                        "role": "assistant",
                        "content": "A band of goblins springs from the underbrush...",
                        "status": "done",
                        "meta": {"length_tokens": 42},
                        "created_at": "2026-09-26T12:34:56Z",
                        "updated_at": "2026-09-26T12:35:10Z",
                    }
                ],
                "next_cursor": None,
                "total": 1,
            }
        }


# ============================================================
# Additive Models for MVP Intelligence Layer Exposure
# ============================================================

class ToolInfo(BaseModel):
    """Metadata for a discovered tool."""
    name: str = Field(..., description="Tool name")
    module: str | None = Field(None, description="Module path where the tool is defined")


class ToolListResp(BaseModel):
    """List of available tools."""
    tools: list[ToolInfo]

    class Config:
        schema_extra = {
            "example": {
                "tools": [
                    {"name": "narrate", "module": "intelligence.tools.narrate"},
                    {"name": "summon", "module": "intelligence.tools.summon"},
                ]
            }
        }


class ToolInvokeReq(BaseModel):
    """Request to invoke a tool."""
    args: str = Field(..., description="Arguments passed to the tool")
    context: dict[str, Any] | None = Field(None, description="Optional context for the tool")


class ToolInvokeResp(BaseModel):
    """Response from a tool invocation."""
    text: str | None = Field(None, description="Tool output text")
    meta: dict[str, Any] | None = Field(None, description="Optional metadata")
    error: str | None = Field(None, description="Error message if invocation failed")

    class Config:
        schema_extra = {
            "example": {
                "text": "The tavern is dimly lit, filled with the scent of oak and ale.",
                "meta": {"source": "narrate"},
                "error": None,
            }
        }


class IntelligenceStatusResp(BaseModel):
    """Status of inference/model layer."""
    model_loaded: bool = Field(..., description="Whether the model is loaded")
    queue_position: int | None = Field(None, description="Current queue position")
    estimated_wait_seconds: float | None = Field(None, description="Estimated wait time")

    class Config:
        schema_extra = {
            "example": {
                "model_loaded": True,
                "queue_position": 2,
                "estimated_wait_seconds": 8.4,
            }
        }


class SessionEntry(BaseModel):
    """Typed representation of a session entry for React visualization."""
    id: int
    run_id: int
    timestamp: float
    role: str
    text: str
    meta: dict[str, Any] | None = None

    class Config:
        schema_extra = {
            "example": {
                "id": 1695841234000,
                "run_id": 7,
                "timestamp": 1695841234.123,
                "role": "Assistant",
                "text": "The goblins leap from the shadows!",
                "meta": {"tool_call": False},
            }
        }


class SessionSnapshotResp(BaseModel):
    """Snapshot of a session run."""
    run_id: int
    entries: list[SessionEntry]
    snapshot_at: float

    class Config:
        schema_extra = {
            "example": {
                "run_id": 7,
                "entries": [],
                "snapshot_at": 1695841234.567,
            }
        }
