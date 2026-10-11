---
description: "Tool module contract and conventions for app/intelligence/tools."
applyTo: "app/intelligence/tools/**"
---
- A tool is a module in `app/intelligence/tools/` exposing `NAME: str` and
  `run(args: str, context: dict) -> Any`. Discovery requires both.
- Discovery goes only through `app.intelligence.tools.discover_tool_modules`
  (ADR-0001); do not add a second registry or import path.
- Log with `get_logger(__name__)`; tool context carries the `inference` service.
- `roll` and `narrate` are being implemented under REQ-0008 (SPEC-0007); until that lands, `roll.py` is still a stub.
- `clear` is deleted (REQ-0008, human decision 2026-10-11): there is no `clear` tool and no
  replacement. `/clear` is an unknown tool and gets the normal unknown-tool error (chat: the
  user message is marked `error`; `POST /api/v1/intel/tools/clear/invoke`: HTTP 404).
- Tests must not need network or Ollama (see `tests/test_tool_calling.py`).
