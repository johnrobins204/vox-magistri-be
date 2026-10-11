# intelligence/tool_handler.py
"""
Tool invocation helpers and a small payload parser.

This module provides:
- detect_tool(payload) -> (name, args)
- run_tool(payload, context, registry) -> (result, metadata)
- get_registry(refresh=False) wrapper around intelligence.tools.discover_tools

It is intentionally small and defensive: tool exceptions are caught and returned
as safe error strings so the UI/services can display them without crashing.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from app.intelligence.tools import discover_tools
from app.services.logger import get_logger

logger = get_logger(__name__)

TOOL_RE = re.compile(r"^/([^\s/]+)(?:\s+(.*))?$")


def detect_tool(payload: str | None) -> tuple[str | None, str | None]:
    if not payload:
        return None, None
    m = TOOL_RE.match(payload.strip())
    if not m:
        return None, None
    name = m.group(1).lower()
    args = m.group(2) or ""
    return name, args


# cached registry
_TOOL_REGISTRY_CACHE: dict[str, Callable[[str, dict[str, Any]], Any]] | None = None


def get_registry(refresh: bool = False, package: str | None = None) -> dict[str, Callable]:
    global _TOOL_REGISTRY_CACHE
    if _TOOL_REGISTRY_CACHE is None or refresh:
        _TOOL_REGISTRY_CACHE = discover_tools(package)
    return _TOOL_REGISTRY_CACHE or {}


def run_tool(
    payload: str, context: dict[str, Any] | None = None, registry: dict[str, Callable] | None = None
) -> tuple[Any, dict[str, Any]]:
    """
    Run a tool call like '/narrate look around'.

    Returns (result, metadata). On error, result is a safe string describing the error.
    metadata is a dict with keys like 'tool', 'args', 'error'.
    """
    name, args = detect_tool(payload)
    meta: dict[str, Any] = {"tool": name, "args": args}
    if not name:
        return "Tool calls must start with '/' followed immediately by the tool name.", meta

    reg = registry if registry is not None else get_registry()
    tool = reg.get(name)
    if not tool:
        return f"Unknown tool: /{name}", meta

    try:
        # Tools may expect different signatures; prefer (args, context) convention.
        if context is None:
            context = {}
        result = tool(args, context)
        return result, meta
    except TypeError:
        # fallback: try calling with more parameters for older tool signatures
        try:
            result = tool(args, context, meta)
            return result, meta
        except Exception as e:
            logger.exception("Tool /%s raised exception", name)
            return f"Tool /{name} error: {e}", {"tool": name, "args": args, "error": str(e)}
    except Exception as e:
        logger.exception("Tool /%s raised exception", name)
        return f"Tool /{name} error: {e}", {"tool": name, "args": args, "error": str(e)}
