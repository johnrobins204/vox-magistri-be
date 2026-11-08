# app/type_defs.py
from collections.abc import AsyncGenerator
from enum import StrEnum
from typing import Any, Protocol


class EntityKind(StrEnum):
    NPC = "npc"
    PLACE = "place"
    FACTION = "faction"
    QUEST = "quest"
    ITEM = "item"
    OTHER = "other"


class EntityStatus(StrEnum):
    CANON = "canon"
    PENDING = "pending"
    REJECTED = "rejected"


class WorldStore(Protocol):
    def create_entity(
        self,
        *,
        name: str,
        kind: str = "other",
        aliases: list[str] | None = None,
        notes: str = "",
        status: str = "canon",
        session_id: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
    def get_entity(self, entity_id: str) -> dict[str, Any]: ...
    def list_entities(
        self,
        session_id: str | None = None,
        *,
        status: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]: ...
    def update_entity(self, entity_id: str, changes: dict[str, Any]) -> dict[str, Any]: ...
    def delete_entity(self, entity_id: str) -> None: ...


class SessionStore(Protocol):
    def get_session(self, session_id: str) -> list[dict[str, Any]] | None: ...
    def create_session(self, session_id: str, character: dict[str, Any] | None = None) -> None: ...
    def get_character(self, session_id: str) -> dict[str, Any] | None: ...
    def create_message(
        self,
        session_id: str,
        message_id: str,
        payload: dict[str, Any],
        status: str = "queued",
    ) -> dict[str, Any]: ...
    def get_message(self, session_id: str, message_id: str) -> dict[str, Any] | None: ...
    def get_by_client_id(
        self, session_id: str, client_message_id: str
    ) -> dict[str, Any] | None: ...
    def list_messages(self, session_id: str) -> list[dict[str, Any]]: ...
    def update_message_status(
        self, session_id: str, message_id: str, status: str, meta: dict[str, Any] | None = None
    ) -> None: ...
    def update_message(
        self,
        session_id: str,
        message_id: str,
        *,
        content: str | None = None,
        canon: bool | None = None,
        meta: dict[str, Any] | None = None,
        reason: str = "edit",
    ) -> dict[str, Any]: ...


class InferenceService(Protocol):
    def enqueue(
        self, *, session_id: str, message_id: str, prompt: str, store: SessionStore
    ) -> bool: ...
    def cancel(self, message_id: str) -> bool: ...
    def validate_token(self, token: str) -> bool: ...
    def queue_position(self, message_id: str) -> int | None: ...
    def estimate_wait(self, message_id: str) -> float | None: ...
    async def generate_tokens(
        self, *, prompt: str, session_id: str | None, message_id: str
    ) -> AsyncGenerator[str]: ...
    @property
    def model_loaded(self) -> bool: ...
    async def shutdown(self) -> None: ...
