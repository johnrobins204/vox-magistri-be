"""Shared helpers for the session tests (SPEC-0004). Plain module; no fixtures."""

import time
from typing import Any

import pytest

from app.config import OllamaSettings, Settings
from app.services.inference_service import OllamaInferenceService

# require_local_token only accepts a "Bearer " prefix; the value is a test placeholder.
AUTH = {"Authorization": "Bearer test-token"}


def make_stub_service(
    tool_service=None, species=None, world_store=None, **settings_kwargs
) -> OllamaInferenceService:
    """Real OllamaInferenceService built from a real Settings; constructing it connects to nothing."""
    settings = Settings(
        ollama=OllamaSettings(base_url="http://127.0.0.1:1", model="stub", timeout_seconds=1.0),
        **settings_kwargs,
    )
    return OllamaInferenceService(
        settings, tool_service=tool_service, species=species, world_store=world_store
    )


def wait_idle(svc, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while svc._queue.unfinished_tasks != 0:
        if time.monotonic() > deadline:
            pytest.fail("inference worker did not become idle")
        time.sleep(0.01)


class FakeInference:
    """Inference stand-in. Never touches the store, so statuses never change."""

    def __init__(self, accept: bool = True):
        self.accept = accept
        self.calls: list[dict[str, Any]] = []
        self.model_loaded = True

    def enqueue(self, *, session_id, message_id, prompt, store) -> bool:
        self.calls.append(
            {
                "session_id": session_id,
                "message_id": message_id,
                "prompt": prompt,
                "store": store,
            }
        )
        return self.accept

    def queue_position(self, message_id) -> int:
        return 0

    def estimate_wait(self, message_id) -> float:
        return 0.0

    def cancel(self, message_id) -> bool:
        return True

    def validate_token(self, token) -> bool:
        return True

    async def shutdown(self) -> None:
        return None
