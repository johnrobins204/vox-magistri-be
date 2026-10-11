---
id: PAT-CODE-001
category: code
status: accepted
supersedes: null
superseded_by: null
---

# Centralized logging via app.services.logger

## Problem
Modules need ERROR/DEBUG/operational logging without each one configuring its
own handlers, formats, or rotation — and without secrets/PII leaking into logs.

## Context
Applies to every module in `app/` (and eventually `data/` once it's wired up)
that needs to log anything. Does not apply to one-off scratch scripts that
aren't part of the running app (e.g. `app/tst.py`).

## Solution
- Call `app.services.logger.init_logging(...)` exactly once, from
  `app/main.py`, before anything else logs. It configures the root logger with
  three handlers: a rotating text file (`logs/debug.log`, DEBUG or INFO
  depending on `--debug`), a rotating JSON file (`logs/operations.jsonl`,
  INFO+), and a console `StreamHandler` (text, DEBUG or INFO).
- Every other module gets its logger via `from app.services.logger import
  get_logger` then `logger = get_logger(__name__)` at module scope, and logs
  through it (`logger.info(...)`, `logger.exception(...)`, etc.) — never
  `print()` and never a bare `import logging; logging.getLogger(__name__)`.
- Because `get_logger` just wraps stdlib `logging.getLogger`, loggers created
  this way still attach to the root logger's handlers via normal propagation —
  the import matters for convention/consistency and to guarantee nobody
  bypasses it with ad-hoc handler config, not because stdlib loggers are
  functionally disconnected today.
- Do not log secrets, tokens, or PII; `JsonFormatter` only emits
  timestamp/level/logger/message/module/function/line/exception — keep message
  bodies free of sensitive values at the call site.

## Consequences
- Single place (`app/services/logger.py`) to change rotation size, formats, or
  add handlers later (e.g. shipping JSON logs elsewhere).
- Relies on log-level discipline at call sites (don't log everything at
  ERROR); no automated enforcement beyond code review.
- `app/main.py`'s top-level logger intentionally keeps the literal name
  (`"dnd_app"`) rather than `__name__`; `python -m app.main` would make
  `__name__` resolve to `"__main__"`, which is less useful in logs.

## Examples
- [app/services/logger.py](../../../app/services/logger.py) — implementation.
- [app/main.py](../../../app/main.py#L15) — `init_logging()` call + logger use.
- [app/api/v1/session.py](../../../app/api/v1/session.py#L14) — correct usage.
- [app/factory.py](../../../app/factory.py#L9) — correct usage.
- [app/services/inference_service.py](../../../app/services/inference_service.py#L14) — correct usage.
- **Stragglers not yet following this pattern** (stdlib `logging.getLogger`
  instead of `get_logger`): [app/intelligence/client.py](../../../app/intelligence/client.py#L18),
  [app/intelligence/prompt_builders.py](../../../app/intelligence/prompt_builders.py#L20),
  [app/intelligence/tool_handler.py](../../../app/intelligence/tool_handler.py#L23),
  [app/intelligence/tools/__init__.py](../../../app/intelligence/tools/__init__.py#L22).
- **`print()` instead of logging**: [app/services/tool_service.py](../../../app/services/tool_service.py#L181-L203)
  (four call sites — info/warn/error helpers and a `__main__` debug print).
