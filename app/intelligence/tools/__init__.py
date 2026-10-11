# intelligence/tools/__init__.py
"""
Tool discovery helpers.

Tools are expected to live under intelligence.tools (a package) and expose:
- NAME: str
- run(args: str, context: dict) -> Any

ToolService (in services) will import and register tools dynamically. This module
keeps discovery logic minimal and testable.
"""

__all__ = ["discover_tool_modules", "discover_tools", "load_tool_module"]

import importlib
import pkgutil
import types
from collections.abc import Callable

from app.services.logger import get_logger

logger = get_logger(__name__)
TOOLS_PACKAGE = "app.intelligence.tools"


def discover_tool_modules(package: str | None = None) -> dict[str, types.ModuleType]:
    pkg_name = package or TOOLS_PACKAGE
    result: dict[str, types.ModuleType] = {}
    try:
        pkg = importlib.import_module(pkg_name)
    except Exception:
        logger.exception("Failed to import tool package %s", pkg_name)
        return result

    for _finder, modname, _ispkg in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
        try:
            mod = importlib.import_module(modname)
        except Exception:
            logger.exception("Failed to import tool module %s", modname)
            continue
        name = getattr(mod, "NAME", None)
        run_fn = getattr(mod, "run", None)
        if isinstance(name, str) and callable(run_fn):
            result[name] = mod
        else:
            logger.debug("Skipping %s: no NAME/run contract", modname)
    return result


def discover_tools(package: str | None = None) -> dict[str, Callable]:
    return {name: mod.run for name, mod in discover_tool_modules(package).items()}


def load_tool_module(module_name: str) -> types.ModuleType | None:
    try:
        return importlib.import_module(module_name)
    except Exception:
        logger.exception("Failed to import tool module %s", module_name)
        return None
