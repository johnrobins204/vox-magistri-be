# intelligence/client.py
"""
Intelligence client protocol and a small Ollama-backed implementation.

Design goals:
- Keep a simple sync interface `generate(prompt, model=None) -> str`.
- Raise IntelligenceError for any transport or response issues.
- Avoid side effects at import time.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class IntelligenceError(RuntimeError):
    """Raised for any intelligence client errors."""


class IntelligenceClient(Protocol):
    def generate(self, prompt: str, *, model: str | None = None) -> str: ...


class OllamaClient:
    """
    Minimal Ollama client wrapper.

    Usage:
        client = OllamaClient(settings)
        text = client.generate(prompt)
    """

    def __init__(self, base_url: str, default_model: str, timeout_seconds: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = timeout_seconds

    def _available_models(self) -> str:
        try:
            resp = httpx.get(f"{self._base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            tags = resp.json().get("models", [])
            return ", ".join(tag.get("model", tag.get("name", "?")) for tag in tags) or "none"
        except Exception:
            return "unknown"

    def generate(self, prompt: str, *, model: str | None = None) -> str:
        model_name = model or self._default_model
        try:
            resp = httpx.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                detail = f"model '{model_name}' not found. Available: {self._available_models()}"
            else:
                detail = exc.response.text or str(exc)
            logger.error("Ollama HTTP error: %s", detail)
            raise IntelligenceError(f"Intelligence request failed: {detail}") from exc
        except Exception as exc:
            logger.exception("Ollama request failed")
            raise IntelligenceError(f"Intelligence request failed: {exc}") from exc

        if not content:
            raise IntelligenceError("Intelligence endpoint returned an empty response.")
        return str(content)
