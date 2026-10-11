# services/tool_service.py
"""
ToolService: discover, register, and invoke tool modules under intelligence.tools.

Responsibilities:
- Discover tool modules in the intelligence.tools package and register callable tool entrypoints.
- Provide a stable `invoke(name, args, context, *, client_context)` API for UI and services.
- Allow reloading tools during development.

Tool contract (expected in each tool module):
- NAME: str
- run(args: str, context: dict) -> str | {"text": str, "meta": dict}

Context built for each tool, lowest to highest precedence:
1. `client_context` (untrusted). Keys in SERVER_CONTEXT_KEYS, and keys present in
   `default_context`, are dropped; their names (never values) are logged once at WARNING.
2. `self.default_context` (server objects, e.g. "repos", "inference").
3. `context` (server-supplied by the caller; may carry protected keys).
A "logger" is supplied if none of the above provides one.

Error behaviour (ADR-0004 D3):
- `invoke` raises `UnknownToolError("Unknown tool: <name>")` for an unregistered name.
- Exceptions raised by a tool propagate unchanged (`ToolError` is for user-facing input errors).
- The registry lock is held only while the tool is looked up, never while it runs.
- Results are normalized to `{"text": str, "meta": dict}`; any other result type raises TypeError.

Usage:
    svc = ToolService(default_context={"repos": repos, "inference": inference})
    svc.reload_tools()
    svc.invoke("narrate", "describe the tavern")
"""

from __future__ import annotations

import threading
import types
from collections.abc import Callable
from typing import Any

from app.intelligence.tools import discover_tool_modules
from app.services.logger import get_logger

logger = get_logger(__name__)

# Keys a client may never supply through `client_context` (ADR-0004 D3).
SERVER_CONTEXT_KEYS = frozenset(
    {"inference", "repos", "store", "session_id", "message_id", "logger", "rng"}
)


class UnknownToolError(LookupError):
    """Raised by ToolService.invoke when no tool is registered under the given name."""


class ToolService:
    def __init__(
        self, default_context: dict[str, Any] | None = None, discover_on_init: bool = True
    ):
        """
        default_context: dict of objects to include in every tool invocation (ai_client, prompt_builder, repos, session, etc.)
        discover_on_init: if True, run discovery immediately
        """
        self.default_context: dict[str, Any] = default_context.copy() if default_context else {}
        self._registry: dict[str, Callable[[str, dict[str, Any]], Any]] = {}
        self._modules: dict[str, types.ModuleType] = {}
        self._lock = threading.RLock()
        if discover_on_init:
            self.reload_tools()

    # -------------------------
    # Discovery and management
    # -------------------------
    def reload_tools(self) -> None:
        """
        Discover and (re)load tool modules under app.intelligence.tools.
        This will import modules and register any module that exposes:
            NAME: str
            run: callable(args: str, context: dict) -> Any
        """
        with self._lock:
            self._registry.clear()
            self._modules.clear()
            for name, mod in discover_tool_modules().items():
                self._registry[name] = mod.run
                self._modules[name] = mod

    def list_tools(self) -> dict[str, str]:
        """
        Return a mapping of tool name -> module __name__ for discovered tools.
        """
        with self._lock:
            return {
                name: getattr(self._modules.get(name), "__name__", "")
                for name in self._registry.keys()
            }

    # -------------------------
    # Invocation
    # -------------------------
    def invoke(
        self,
        name: str,
        args: str = "",
        context: dict[str, Any] | None = None,
        *,
        client_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Invoke a registered tool by name.

        name: tool name (as defined by tool module's NAME)
        args: freeform string passed to the tool
        context: server-supplied context, merged over default_context (highest precedence)
        client_context: untrusted context from the client; protected keys are dropped (see module docstring)

        Returns: {"text": str, "meta": dict}

        Raises:
            UnknownToolError: no tool is registered under `name`
            TypeError: the tool returned an unsupported result type
            Any exception raised by the tool, unchanged
        """
        with self._lock:
            tool = self._registry.get(name)
            defaults = dict(self.default_context)
        if tool is None:
            raise UnknownToolError(f"Unknown tool: {name}")

        ctx: dict[str, Any] = {}
        dropped: list[str] = []
        for key, value in (client_context or {}).items():
            if key in SERVER_CONTEXT_KEYS or key in defaults:
                dropped.append(key)
            else:
                ctx[key] = value
        ctx.update(defaults)
        if context:
            ctx.update(context)
        if dropped:
            logger.warning(
                "Dropped client context keys for tool %s: %s", name, ", ".join(sorted(dropped))
            )
        if "logger" not in ctx:
            ctx["logger"] = _SimpleLogger()

        result = tool(args, ctx)
        return _normalize_result(name, result)

    # -------------------------
    # Helpers
    # -------------------------
    def register_tool(
        self,
        name: str,
        func: Callable[[str, dict[str, Any]], Any],
        module: types.ModuleType | None = None,
    ) -> None:
        """
        Manually register a tool function under `name`. Useful for tests or dynamic tools.
        """
        with self._lock:
            self._registry[name] = func
            if module:
                self._modules[name] = module

    def unregister_tool(self, name: str) -> None:
        with self._lock:
            self._registry.pop(name, None)
            self._modules.pop(name, None)


class _SimpleLogger:
    """Tiny logger used in contexts where no logger is provided."""

    def info(self, msg: str) -> None:
        try:
            logger.info(msg)
        except Exception:
            pass

    def warn(self, msg: str) -> None:
        try:
            logger.warning(msg)
        except Exception:
            pass

    def error(self, msg: str) -> None:
        try:
            logger.error(msg)
        except Exception:
            pass


def _normalize_result(name: str, result: Any) -> dict[str, Any]:
    """Return a tool result as {"text": str, "meta": dict}; reject any other type."""
    if isinstance(result, str):
        return {"text": result, "meta": {}}
    if isinstance(result, dict) and isinstance(result.get("text"), str):
        return {"text": result["text"], "meta": dict(result.get("meta") or {})}
    raise TypeError(f"Tool {name} returned an unsupported result type")


# -------------------------
# If run directly, demonstrate discovery (no-op if intelligence.tools missing)
# -------------------------
if __name__ == "__main__":
    svc = ToolService(default_context={})
    logger.info("Discovered tools: %s", svc.list_tools())
