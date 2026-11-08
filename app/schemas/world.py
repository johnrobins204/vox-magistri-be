# app/schemas/world.py
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.type_defs import EntityKind, EntityStatus

NAME_MAX = 120
ALIAS_MAX = 60
ALIASES_MAX = 20
NOTES_MAX = 1000


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# PAT-ARCH-005: the store keeps naive-UTC; the API edge emits aware UTC.
UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]

Name = Annotated[str, StringConstraints(min_length=1, max_length=NAME_MAX)]
Alias = Annotated[str, StringConstraints(min_length=1, max_length=ALIAS_MAX)]
Aliases = Annotated[list[Alias], Field(max_length=ALIASES_MAX)]
Notes = Annotated[str, StringConstraints(max_length=NOTES_MAX)]


class WorldEntityCreateReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    kind: EntityKind = EntityKind.OTHER
    aliases: Aliases = Field(default_factory=list)
    notes: Notes = ""
    status: EntityStatus = EntityStatus.CANON
    session_id: str | None = None


class WorldEntityPatchReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    kind: EntityKind | None = None
    aliases: Aliases | None = None
    notes: Notes | None = None
    status: EntityStatus | None = None

    @model_validator(mode="after")
    def _reject_explicit_null(self):
        nulls = sorted(k for k in self.model_fields_set if getattr(self, k) is None)
        if nulls:
            raise ValueError(f"null is not allowed for: {nulls}")
        return self


class WorldEntityResp(BaseModel):
    id: str
    session_id: str | None
    kind: EntityKind
    name: str
    aliases: list[str]
    notes: str
    status: EntityStatus
    # Read-only: set by the mention worker, never accepted from create/patch bodies.
    evidence: dict[str, Any] | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class WorldEntityListResp(BaseModel):
    entities: list[WorldEntityResp]
