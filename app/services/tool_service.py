# services/tool_service.py
"""
ToolService: discover, register, and invoke tool modules under intelligence.tools.

Responsibilities:
- Discover tool modules in the intelligence.tools package and register callable tool entrypoints.
- Provide a stable `invoke(name, args, context)` API for UI and services to call tools.
- Allow reloading tools during development.
- Supply a minimal, safe execution environment (catch exceptions, return error messages).

Tool contract (expected in each tool module):
- NAME: str
- run(args: str, context: dict) -> Any

Context provided to tools:
- The service will merge `self.default_context` with the caller-provided `context`.
- Common keys in default_context: "ai_client", "prompt_builder", "repos", "session", "logger"

Usage:
    svc = ToolService(default_context={"ai_client": ai, "prompt_builder": pb, "repos": repos})
    svc.reload_tools()
    svc.invoke("narrate", "describe the tavern", {})
"""

from __future__ import annotations

import importlib
import pkgutil
import threading
import traceback
import types
from collections.abc import Callable
from typing import Any

# Attempt to import the intelligence.tools package; discovery will fail gracefully if missing.
try:
    import intelligence.tools as _tools_pkg  # type: ignore
except Exception:
    _tools_pkg = None  # discovery will be a no-op


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
        Discover and (re)load tool modules under intelligence.tools.
        This will import modules and register any module that exposes:
            NAME: str
            run: callable(args: str, context: dict) -> Any
        """
        with self._lock:
            self._registry.clear()
            self._modules.clear()
            if _tools_pkg is None:
                return
            try:
                prefix = _tools_pkg.__name__ + "."
                for finder, modname, ispkg in pkgutil.iter_modules(_tools_pkg.__path__, prefix):
                    try:
                        mod = importlib.import_module(modname)
                        name = getattr(mod, "NAME", None)
                        run = getattr(mod, "run", None)
                        if isinstance(name, str) and callable(run):
                            self._registry[name] = run
                            self._modules[name] = mod
                    except Exception:
                        # swallow individual module import errors but keep going
                        continue
            except Exception:
                # If package introspection fails, leave registry empty
                pass

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
        timeout_seconds: float | None = None,
    ) -> Any:
        """
        Invoke a registered tool by name.

        name: tool name (as defined by tool module's NAME)
        args: freeform string passed to the tool
        context: additional context merged with default_context for this invocation
        timeout_seconds: reserved for future use (no-op in MVP)

        Returns:
            - The tool's return value on success
            - A string describing the error on failure
        """
        with self._lock:
            tool = self._registry.get(name)
            if not tool:
                return f"Unknown tool: {name}"

            # Build invocation context
            ctx = {}
            ctx.update(self.default_context or {})
            if context:
                # shallow merge; caller context overrides defaults
                ctx.update(context)

            # Provide a minimal logger in context if none provided
            if "logger" not in ctx:
                ctx["logger"] = _SimpleLogger()

            try:
                # Call the tool. Tools are expected to be synchronous and quick.
                result = tool(args, ctx)
                return result
            except Exception as e:
                # Capture traceback for debugging but return a safe message
                tb = traceback.format_exc()
                # If a logger exists, log the exception
                try:
                    logger = ctx.get("logger")
                    if logger and hasattr(logger, "error"):
                        logger.error(f"Tool {name} raised exception: {e}\n{tb}")
                except Exception:
                    pass
                return f"Tool {name} error: {e}"

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
            print(f"[ToolService] INFO: {msg}")
        except Exception:
            pass

    def warn(self, msg: str) -> None:
        try:
            print(f"[ToolService] WARN: {msg}")
        except Exception:
            pass

    def error(self, msg: str) -> None:
        try:
            print(f"[ToolService] ERROR: {msg}")
        except Exception:
            pass


# -------------------------
# If run directly, demonstrate discovery (no-op if intelligence.tools missing)
# -------------------------
if __name__ == "__main__":
    svc = ToolService(default_context={})
    print("Discovered tools:", svc.list_tools())
