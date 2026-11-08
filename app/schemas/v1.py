from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, constr

from app.reference.species import Species
from app.reference.weapons import Weapon

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


class AbilitiesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    STR: int = Field(..., ge=1, le=30)
    DEX: int = Field(..., ge=1, le=30)
    CON: int = Field(..., ge=1, le=30)
    INT: int = Field(..., ge=1, le=30)
    WIS: int = Field(..., ge=1, le=30)
    CHA: int = Field(..., ge=1, le=30)


CONDITION_STR = Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)]


class CharacterIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field("", max_length=64)
    name: str = Field(..., min_length=1, max_length=60)
    lineage: str = Field("", max_length=60)
    species_id: str | None = Field(None, max_length=64, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    char_class: str = Field("", max_length=40)
    level: int = Field(..., ge=1, le=20)
    hp_current: int = Field(..., ge=0, le=999)
    hp_max: int = Field(..., ge=1, le=999)
    ac: int = Field(..., ge=0, le=30)
    abilities: AbilitiesIn
    conditions: list[CONDITION_STR] = Field(default_factory=list, max_length=8)


class SessionCreateReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character: CharacterIn | None = None


ContentStr = constr(min_length=1, max_length=16384)


class MessageCreateReq(BaseModel):
    client_message_id: str | None = Field(
        None, description="Optional client-provided id for idempotency"
    )
    role: str | None = Field("user", description="Role of the author (user/system/assistant)")
    content: str = Field(
        ..., min_length=1, max_length=16384, description="Message text/prompt to be processed"
    )
    meta: dict[str, Any] | None = Field(None, description="Optional structured metadata")
    narrative_only: bool = Field(
        False,
        description="Ask for a narrative-only reply; stored server-side as meta.narrative_only",
    )

    class Config:
        schema_extra = {
            "example": {
                "client_message_id": "client-123",
                "role": "user",
                "content": "Describe a goblin ambush in two sentences.",
                "meta": {"tone": "grimdark"},
                "narrative_only": False,
            }
        }


class MessageUpdateReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(
        None, min_length=1, description="Replacement text (assistant replies only)"
    )
    canon: bool | None = Field(None, description="Set false to mark a message not canon")


class MessageResp(BaseModel):
    id: str = Field(..., description="Server-generated message id")
    client_message_id: str | None = Field(None, description="Client id if provided")
    role: str | None = Field(None, description="Role of the author")
    content: str | None = Field(None, description="Final or partial content")
    status: str = Field(..., description="Message status: queued|running|completed|error|cancelled")
    meta: dict[str, Any] | None = Field(None, description="Optional structured metadata")
    created_at: datetime | None = Field(None, description="Creation timestamp (UTC)")
    updated_at: datetime | None = Field(None, description="Last update timestamp (UTC)")
    canon: bool = Field(True, description="False when the message is marked not canon")

    class Config:
        orm_mode = True
        schema_extra = {
            "example": {
                "id": "a1b2c3d4-...",
                "client_message_id": "client-123",
                "role": "assistant",
                "content": "A band of goblins springs from the underbrush...",
                "status": "completed",
                "meta": {"length_tokens": 42},
                "created_at": "2026-09-26T12:34:56Z",
                "updated_at": "2026-09-26T12:35:10Z",
            }
        }


class MessageStatusResp(BaseModel):
    message_id: str = Field(..., description="Server-generated message id")
    status: str = Field(..., description="Message status: queued|running|completed|error|cancelled")
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
                        "status": "completed",
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
    description: str = Field("", description="One-line, user-facing summary of the tool")


class ToolListResp(BaseModel):
    """List of available tools."""

    tools: list[ToolInfo]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tools": [
                    {
                        "name": "narrate",
                        "module": "intelligence.tools.narrate",
                        "description": "Narrate the scene in the DM's voice.",
                    },
                    {
                        "name": "summon",
                        "module": "intelligence.tools.summon",
                        "description": "Summon a creature into the scene.",
                    },
                ]
            }
        }
    )


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


class SessionSnapshotResp(BaseModel):
    """Snapshot of a session (same message shape as the REST list)."""

    session_id: str
    entries: list[MessageResp]
    snapshot_at: float

    class Config:
        schema_extra = {
            "example": {
                "session_id": "b3f1c2d4-...",
                "entries": [],
                "snapshot_at": 1695841234.567,
            }
        }


# ============================================================
# Reference Data (SPEC-0011, PAT-ARCH-005 envelope)
# ============================================================


class SpeciesListResp(BaseModel):
    """Read-only species catalog envelope."""

    model_config = ConfigDict(extra="forbid")

    species: list[Species]


class WeaponListResp(BaseModel):
    """Read-only weapons catalog envelope."""

    model_config = ConfigDict(extra="forbid")

    weapons: list[Weapon]
