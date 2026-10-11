---
id: SPEC-0001
requirement: REQ-0001
adr: null
status: done
date: 2026-10-10
---

# Centralized Logging Consistency

## 1. Requirement
> The application MUST provide a single, centralized logging utility that
> captures ERROR-level, DEBUG-level, and general application/operational log
> records. All modules MUST use this utility — via `get_logger(__name__)` —
> rather than `print()` or ad-hoc stdlib `logging` configuration. The
> implementation SHOULD follow established logging best practices:
> structured/machine-readable output for operational logs, human-readable
> output for console/debug use, log rotation to bound file size, correct
> separation of log levels, consistent logger naming, and no sensitive data
> (tokens, secrets, PII) written to logs. (REQ-0001)

No ADR was produced for this requirement. The senior-architect determined this
is a consistency/enforcement fix, not a design decision: the centralized
logger already exists and is fully functional at
[app/services/logger.py](../../app/services/logger.py) (`init_logging`,
`get_logger`, `JsonFormatter`, `RotatingFileHandler`-based handlers for
`logs/debug.log` and `logs/operations.jsonl`, plus a console handler). It
already satisfies the structural/rotation/level-separation/no-secrets
requirements. What remains is mechanical: a handful of modules don't call
through it yet.

## 2. Test Spec
Written before any work package. "Done" means all of the following pass.

1. **No stdlib `logging.getLogger` usage outside the logger module itself.**
   - Exercises: a grep across `app/` for the pattern
     `logging.getLogger(` excluding `app/services/logger.py` (which
     legitimately wraps stdlib logging internally).
   - Expected observable outcome: zero matches.
   - Command: `grep -rn "logging.getLogger(" app --include=*.py | grep -v app/services/logger.py`
     returns no output (exit with no matching lines).
   - Not a pytest test (it's a repo-hygiene grep check); documented here and
     run manually/by CI as part of verifying the work is complete. Optionally
     captured as `tests/test_logging_consistency.py` (see test 3 below) to
     make it automatic.

2. **No bare stdlib `import logging` left importing the module-level logger
   in the straggler files**, i.e. each straggler file imports `get_logger`
   from `app.services.logger` instead of calling `logging.getLogger(__name__)`.
   - Exercises: each of the four straggler files
     ([app/intelligence/client.py](../../app/intelligence/client.py),
     [app/intelligence/prompt_builders.py](../../app/intelligence/prompt_builders.py),
     [app/intelligence/tool_handler.py](../../app/intelligence/tool_handler.py),
     [app/intelligence/tools/__init__.py](../../app/intelligence/tools/__init__.py))
     and [app/services/tool_service.py](../../app/services/tool_service.py).
   - Expected observable outcome: each file contains
     `from app.services.logger import get_logger` and
     `logger = get_logger(__name__)`, and does not contain
     `logging.getLogger(`.
   - Covered by test 3's automated grep-based pytest check.

3. **Automated regression test for the pattern, added at
   `tests/test_logging_consistency.py`.**
   - Exercises: walks `app/` for `.py` files (excluding
     `app/services/logger.py`) and asserts none contain the substring
     `logging.getLogger(`; also asserts none contain a bare `print(` call
     inside `app/services/tool_service.py` specifically (the known straggler
     file for `print()` usage).
   - Expected observable outcome: test passes once all work packages are
     applied; it would have failed before this spec's changes (can be
     confirmed by running it against the pre-change tree if desired, but is
     not required — this is a forward-looking regression guard).
   - File: `tests/test_logging_consistency.py`.

4. **`app/services/tool_service.py` has no `print()` calls.**
   - Exercises: `grep -n "print(" app/services/tool_service.py`.
   - Expected observable outcome: zero matches.
   - Covered by test 3 above (specific assertion for this file) and
     independently verifiable via the same grep command.

5. **Existing test suite still passes end-to-end.**
   - Exercises: `tests/test_app_factory.py` (`test_app_builds_with_default_services`,
     `test_create_session_endpoint`), which build a real app with in-memory
     repos via the `app`/`client` fixtures in
     [tests/conftest.py](../../tests/conftest.py).
   - Expected observable outcome: `pytest` run from the repo root (using
     `./venv-dnd-server/bin/python -m pytest`) exits 0, with all existing
     tests (including the new `tests/test_logging_consistency.py`) passing.
   - This confirms the straggler fixes did not break app startup, tool
     discovery (`build_services(repos, enable_tool_discovery=False)` in the
     fixture doesn't exercise `tool_service.py` discovery directly, but the
     module must still import cleanly), or session/websocket routing.

6. **Manual smoke check: app still starts and logs to both files.**
   - Exercises: `python -m app.main --debug` for a few seconds (or just import
     `app.main` and call `init_logging()` directly in a REPL/test), then
     inspect `logs/debug.log` and `logs/operations.jsonl`.
   - Expected observable outcome: both files receive new lines on
     startup-related log calls, `debug.log` is human-readable text,
     `operations.jsonl` is one JSON object per line. Not automated as part of
     this spec (no new behavior is introduced — `init_logging`/`get_logger`
     themselves are unchanged); listed here as an optional manual
     double-check, not a blocking acceptance gate.

## 3. Work Packages

### WP-1: Fix `app/intelligence/client.py` to use centralized logger
- **Files:** `app/intelligence/client.py`
- **Inputs:** The file currently (near the top, ~line 18) contains:
  ```python
  import logging
  ...
  logger = logging.getLogger(__name__)
  ```
  The centralized logger utility lives at `app/services/logger.py` and
  exposes `get_logger(name: str) -> logging.Logger`, imported as
  `from app.services.logger import get_logger`.
- **Outputs:** Replace the `import logging` line with
  `from app.services.logger import get_logger`, and replace
  `logger = logging.getLogger(__name__)` with `logger = get_logger(__name__)`.
  Do not change any other logging call sites in the file (e.g.
  `logger.info(...)`, `logger.error(...)` calls elsewhere in the file, if
  any, already work unchanged against the new logger instance). If
  `logging` is used elsewhere in the file for anything other than
  `getLogger` (e.g. log level constants), keep the `import logging` line and
  only change the `getLogger` call; otherwise remove the now-unused
  `import logging` line entirely.
- **Acceptance criteria:** `app/intelligence/client.py` no longer contains
  `logging.getLogger(`; it contains `from app.services.logger import
  get_logger` and `logger = get_logger(__name__)`; the file still imports
  and the module's existing behavior (the `generate()` method, `IntelligenceError`,
  `IntelligenceClient` protocol) is unchanged. No new runtime dependency is
  introduced.
- **Patterns used/created:** PAT-CODE-001 (status: proposed).

### WP-2: Fix `app/intelligence/prompt_builders.py` to use centralized logger
- **Files:** `app/intelligence/prompt_builders.py`
- **Inputs:** The file currently (near the top, ~line 20) contains:
  ```python
  import logging
  ...
  logger = logging.getLogger(__name__)
  ```
  alongside other unrelated imports (`json`, `collections.abc.Iterable`,
  `dataclasses.dataclass`, `typing.Any`). The centralized logger utility
  lives at `app/services/logger.py` and exposes
  `get_logger(name: str) -> logging.Logger`.
- **Outputs:** Replace `import logging` with
  `from app.services.logger import get_logger`, and replace
  `logger = logging.getLogger(__name__)` with `logger = get_logger(__name__)`.
  Leave all other imports and the rest of the module (prompt-building
  functions, `_truncate` helper, etc.) unchanged.
- **Acceptance criteria:** `app/intelligence/prompt_builders.py` no longer
  contains `logging.getLogger(`; it contains `from app.services.logger
  import get_logger` and `logger = get_logger(__name__)`; the module still
  imports cleanly and all prompt-builder functions behave identically to
  before the change.
- **Patterns used/created:** PAT-CODE-001 (status: proposed).

### WP-3: Fix `app/intelligence/tool_handler.py` to use centralized logger
- **Files:** `app/intelligence/tool_handler.py`
- **Inputs:** The file currently (near the top, ~line 23) contains:
  ```python
  import logging
  ...
  from app.intelligence.tools import discover_tools

  logger = logging.getLogger(__name__)
  ```
  The centralized logger utility lives at `app/services/logger.py` and
  exposes `get_logger(name: str) -> logging.Logger`.
- **Outputs:** Replace `import logging` with
  `from app.services.logger import get_logger`, keeping the existing
  `from app.intelligence.tools import discover_tools` import line intact (it
  is unrelated), and replace `logger = logging.getLogger(__name__)` with
  `logger = get_logger(__name__)`.
- **Acceptance criteria:** `app/intelligence/tool_handler.py` no longer
  contains `logging.getLogger(`; it contains `from app.services.logger
  import get_logger` and `logger = get_logger(__name__)`; `detect_tool`,
  `run_tool`, and `get_registry` (or equivalent exported functions) remain
  functionally unchanged; the module still imports cleanly.
- **Patterns used/created:** PAT-CODE-001 (status: proposed).

### WP-4: Fix `app/intelligence/tools/__init__.py` to use centralized logger
- **Files:** `app/intelligence/tools/__init__.py`
- **Inputs:** The file currently (near the top, ~line 22) contains:
  ```python
  import importlib
  import logging
  import pkgutil
  import types
  from collections.abc import Callable
  from typing import Dict, Optional

  logger = logging.getLogger(__name__)
  TOOLS_PACKAGE = "app.intelligence.tools"
  ```
  The centralized logger utility lives at `app/services/logger.py` and
  exposes `get_logger(name: str) -> logging.Logger`.
- **Outputs:** Replace the `import logging` line with
  `from app.services.logger import get_logger`, keeping `importlib`,
  `pkgutil`, `types`, and the `typing`/`collections.abc` imports unchanged,
  and replace `logger = logging.getLogger(__name__)` with
  `logger = get_logger(__name__)`. Leave `TOOLS_PACKAGE` and the rest of the
  module (`discover_tools`, `load_tool_module`) unchanged.
- **Acceptance criteria:** `app/intelligence/tools/__init__.py` no longer
  contains `logging.getLogger(`; it contains `from app.services.logger
  import get_logger` and `logger = get_logger(__name__)`; `discover_tools`
  and `load_tool_module` (exported via `__all__`) behave identically; the
  package still imports cleanly (this module is imported by
  `app/intelligence/tool_handler.py` and by `app/services/tool_service.py`'s
  discovery path, so an import error here would break both).
- **Patterns used/created:** PAT-CODE-001 (status: proposed).

### WP-5: Replace `print()` calls in `app/services/tool_service.py` with centralized logging
- **Files:** `app/services/tool_service.py`
- **Inputs:** The file currently has no `import logging` or logger usage at
  module scope. There are two `print()`-based pieces:
  1. A private `_SimpleLogger` class (used as a fallback in `invoke()` when
     no `"logger"` key is present in the tool invocation context) whose
     `info`, `warn`, and `error` methods each call `print(f"[ToolService]
     LEVEL: {msg}")` wrapped in a bare `try/except Exception: pass`.
  2. A `if __name__ == "__main__":` block at the bottom that does
     `print("Discovered tools:", svc.list_tools())`.
  The centralized logger utility lives at `app/services/logger.py` (same
  package, so use a relative-style absolute import:
  `from app.services.logger import get_logger`) and exposes
  `get_logger(name: str) -> logging.Logger`.
- **Outputs:**
  - Add `from app.services.logger import get_logger` to the imports and a
    module-level `logger = get_logger(__name__)`.
  - Rewrite `_SimpleLogger.info` to call `logger.info(msg)`, `.warn` to call
    `logger.warning(msg)` (stdlib `Logger` has no `.warn`-as-canonical method;
    use `warning` to match stdlib `logging.Logger` semantics — but keep the
    `_SimpleLogger.warn` method name itself unchanged so existing callers
    that call `ctx["logger"].warn(...)` keep working), and `.error` to call
    `logger.error(msg)`. Drop the inner `try/except Exception: pass` guards
    around each `print()` only if removing them doesn't change behavior for
    callers (logging calls to a properly configured logger don't raise under
    normal operation); if in doubt, keep a `try/except Exception: pass`
    wrapper around each `logger.*(msg)` call to preserve the "never raise
    from the fallback logger" guarantee.
  - Replace the `__main__` block's `print("Discovered tools:",
    svc.list_tools())` with `logger.info("Discovered tools: %s",
    svc.list_tools())`.
  - Do not touch the unrelated `import app.S.tools as _tools_pkg` block, the
    `ToolService` class's discovery/invocation logic, or any other method.
- **Acceptance criteria:** `app/services/tool_service.py` contains no
  `print(` calls anywhere in the file; it imports and calls
  `get_logger(__name__)` from `app.services.logger`; `_SimpleLogger.info`,
  `.warn`, and `.error` route through the module logger instead of
  `print()`; the `__main__` block logs instead of printing; `ToolService`'s
  public API (`reload_tools`, `list_tools`, `invoke`, `register_tool`,
  `unregister_tool`) is otherwise unchanged and callers passing their own
  `"logger"` in `context` are unaffected (the `_SimpleLogger` fallback path
  is only used when no logger is supplied).
- **Patterns used/created:** PAT-CODE-001 (status: proposed).

### WP-6: Normalize `app/main.py` logger name (cosmetic, low priority)
- **Files:** `app/main.py`
- **Inputs:** The file currently has:
  ```python
  from app.services.logger import get_logger, init_logging
  ...
  logger = get_logger("dnd_app")
  ```
  at module scope (around line 13).
- **Outputs:** Change `logger = get_logger("dnd_app")` to
  `logger = get_logger(__name__)`. No other change in this file.
- **Acceptance criteria:** `app/main.py` no longer passes the literal string
  `"dnd_app"` to `get_logger`; it calls `get_logger(__name__)` instead,
  consistent with every other module's convention. `main()`'s behavior
  (argument parsing, `init_logging()` call, server startup) is unchanged —
  only the logger's name in log output changes (from `"dnd_app"` to
  `"app.main"`), which is cosmetic and does not affect log routing, level,
  or handlers (all loggers propagate to the same root handlers regardless
  of name).
- **Patterns used/created:** PAT-CODE-001 (status: proposed).

### WP-7: Add automated regression test for logging consistency
- **Files:** `tests/test_logging_consistency.py` (new file)
- **Inputs:** Assumes WP-1 through WP-6 are already applied (so the test
  passes), but is self-contained and can be written/run independently to
  verify current state at any time — it would fail before those work
  packages are applied, which is expected and fine for a TDD-style check.
  The test needs no fixtures from `tests/conftest.py`.
- **Outputs:** A new pytest file containing:
  1. A helper that walks all `.py` files under the `app/` directory
     (relative to the repo root, discoverable via
     `pathlib.Path(__file__).resolve().parent.parent / "app"`), excluding
     `app/services/logger.py` itself.
  2. `test_no_stdlib_getlogger_outside_logger_module()`: reads each file's
     text and asserts `"logging.getLogger("` does not appear in any of them.
     On failure, the assertion message MUST list the offending file paths.
  3. `test_tool_service_has_no_print_calls()`: reads
     `app/services/tool_service.py` and asserts the substring `"print("`
     does not appear in it.
  4. Both tests MUST be runnable via
     `./venv-dnd-server/bin/python -m pytest tests/test_logging_consistency.py`
     with no network, Ollama, or app-startup dependency (pure static text
     scanning of source files).
- **Acceptance criteria:** Running
  `./venv-dnd-server/bin/python -m pytest tests/test_logging_consistency.py`
  exits 0 after WP-1 through WP-6 are applied; running it before those
  changes would fail with a clear assertion message naming the specific
  straggler file(s) and line pattern found. The test file follows existing
  conventions in `tests/` (plain `pytest`, no unittest-style classes, matching
  the style of [tests/test_app_factory.py](../../tests/test_app_factory.py)).
- **Patterns used/created:** PAT-CODE-001 (status: proposed).

### WP-8: Full regression run
- **Files:** none changed; this package only runs existing + new tests.
- **Inputs:** Assumes WP-1 through WP-7 are complete.
- **Outputs:** Run `./venv-dnd-server/bin/python -m pytest` from the repo
  root and confirm all tests pass, including
  [tests/test_app_factory.py](../../tests/test_app_factory.py)
  (`test_app_builds_with_default_services`, `test_create_session_endpoint`)
  and the new `tests/test_logging_consistency.py`.
- **Acceptance criteria:** `pytest` exits 0 with no failures or errors
  across the full suite. If any test fails, the failure must be diagnosed
  and attributed to a specific WP-1..WP-7 change before this spec is
  considered complete (no unrelated pre-existing failures are expected,
  per the senior-architect's findings that this is a purely mechanical
  fix).
- **Patterns used/created:** none (verification-only package).

## 4. Other Details
- **Risks:**
  - Low. Every change is a mechanical swap of `logging.getLogger(__name__)` →
    `get_logger(__name__)` or `print(...)` → `logger.*(...)`, with no change
    to control flow, signatures, or public APIs.
  - `app/services/tool_service.py`'s `_SimpleLogger` fallback is only reached
    when a tool invocation's context has no `"logger"` key; WP-5 preserves
    that fallback's shape (same method names) so no caller contract changes.
  - `app/main.py`'s logger rename (WP-6) changes the `logger` field in log
    output from `"dnd_app"` to `"app.main"` — purely cosmetic, flagged as
    low priority in the source findings.
- **Rollback plan:** Each work package is an independent, small diff;
  reverting any single file's change (via `git revert`/`git checkout` on that
  file) fully undoes it without affecting the others. No data migrations,
  schema changes, or new dependencies are involved.
- **Patterns applied/created:**
  - Applied: PAT-CODE-001 (status: proposed) — `docs/patterns/code/PAT-CODE-001-centralized-logging.md`.
  - No new patterns created by this spec; it closes the "stragglers" gap
    already documented in PAT-CODE-001's Consequences section.
- **Non-goals:**
  - No change to `app/services/logger.py` itself (formatters, rotation
    sizes, handler config) — it already satisfies REQ-0001.
  - No change to log *levels* used at existing call sites beyond what's
    needed to route through `get_logger` (e.g. not auditing whether every
    `logger.info(...)` call should actually be `logger.debug(...)`).
  - No change to `data/` (not-yet-wired SQLAlchemy layer) — out of scope
    per `docs/constraints.md` and the architecture notes; it isn't live yet.
  - No change to the unrelated `import app.S.tools as _tools_pkg` line in
    `app/services/tool_service.py` (appears to be a separate, pre-existing
    import-path issue, not a logging issue) — not touched by this spec.
  - No enforcement tooling beyond the pytest check in WP-7 (e.g. no
    pre-commit hook, no ruff custom rule) — consistent with the
    solo/hobby-project smallest-edit constraint.
