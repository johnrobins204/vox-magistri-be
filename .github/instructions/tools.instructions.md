---
description: "Tool module contract and conventions for app/intelligence/tools."
applyTo: "app/intelligence/tools/**"
---
- A tool is a module in `app/intelligence/tools/` exposing `NAME: str` and
  `run(args: str, context: dict) -> Any`. Discovery requires both.
- Discovery goes only through `app.intelligence.tools.discover_tool_modules`
  (ADR-0001); do not add a second registry or import path.
- Log with `get_logger(__name__)`; tool context carries the `inference` service.
- `roll.py` is a stub and `narrate.py`'s body is out of scope unless a requirement says otherwise.
- Tests must not need network or Ollama (see `tests/test_tool_calling.py`).
