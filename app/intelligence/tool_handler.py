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

import logging
import re
from typing import Any, Callable, Dict, Optional, Tuple

from .tools import discover_tools

logger = logging.getLogger(__name__)

TOOL_RE = re.compile(r"^/([^\s/]+)(?:\s+(.*))?$")


def detect_tool(payload: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not payload:
        return None, None
    m = TOOL_RE.match(payload.strip())
    if not m:
        return None, None
    name = m.group(1).lower()
    args = m.group(2) or ""
    return name, args


# cached registry
_TOOL_REGISTRY_CACHE: Optional[Dict[str, Callable[[str, Dict[str, Any]], Any]]] = None


def get_registry(refresh: bool = False, package: Optional[str] = None) -> Dict[str, Callable]:
    global _TOOL_REGISTRY_CACHE
    if _TOOL_REGISTRY_CACHE is None or refresh:
        _TOOL_REGISTRY_CACHE = discover_tools(package)
    return _TOOL_REGISTRY_CACHE or {}


def run_tool(payload: str, context: Optional[Dict[str, Any]] = None, registry: Optional[Dict[str, Callable]] = None) -> Tuple[Any, Dict[str, Any]]:
    """
    Run a tool call like '/narrate look around'.

    Returns (result, metadata). On error, result is a safe string describing the error.
    metadata is a dict with keys like 'tool', 'args', 'error'.
    """
    name, args = detect_tool(payload)
    meta: Dict[str, Any] = {"tool": name, "args": args}
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
