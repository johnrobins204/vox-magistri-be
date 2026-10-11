---
id: ADR-0001
status: accepted
date: 2026-10-10
requirement: REQ-0002
supersedes: null
superseded_by: null
---

# Single tool discovery path for the tool-calling pipeline

## Context
REQ-0002 requires the tool-calling path to discover, register, and invoke tools
through one path. Two discovery implementations exist today:

- `ToolService.reload_tools()` in [app/services/tool_service.py](../../app/services/tool_service.py#L41)
  does `import app.S.tools as _tools_pkg` inside a `try/except` that sets the
  package to `None` on failure. `app.S` does not exist, so the registry is always
  empty and the failure is silent. `ToolService` is the only discovery path used at
  runtime: `build_services()`, the `/api/v1/intel/tools` routes, `GameService`, and
  `SessionService` all reach tools through it.
- `discover_tools()` in [app/intelligence/tools/__init__.py](../../app/intelligence/tools/__init__.py#L27)
  uses the correct package (`app.intelligence.tools`), logs import failures, and
  returns `name -> run`. Its only caller is `get_registry()` in
  [app/intelligence/tool_handler.py](../../app/intelligence/tool_handler.py#L43),
  and nothing in the app calls `get_registry()` or `run_tool()`, so it is dead at
  runtime.

Both implementations therefore exist, but only the silent, broken one is live.
The decision is which discovery implementation becomes the single source of truth.

Related pattern: [PAT-CODE-001](../patterns/code/PAT-CODE-001-centralized-logging.md)
(accepted) requires logging via `get_logger(__name__)`; any new discovery code
MUST follow it. No `accepted` architecture pattern is affected.

## Decision Drivers
| Dimension | Weight | Why it matters here |
|---|---|---|
| Simplicity / smallest-edit fit | High (3) | Solo, part-time project; constraints.md standing constraint 1 |
| Reversibility | High (3) | Low stakes; keep the change easy to undo |
| Maintainability for one part-time person | High (3) | Two discovery implementations already diverged once (the silent failure above) |
| Reuse of existing code | Medium (2) | `discover_tools()` already works against the correct package |
| Fun / learning value | Medium (2) | constraints.md standing constraint 5 |
| Performance / scalability | Low (1) | De-prioritized; tool discovery runs once at startup |
| Security hardening beyond sane defaults | Low (1) | No production intent; the relevant concern is not hiding failures, covered under maintainability |

## Considered Options
1. **A - Fix the import only.** Change `import app.S.tools` to
   `import app.intelligence.tools` in `ToolService` and leave both implementations.
2. **B - One discovery function, used by both callers.** Extract the module-level
   logic of `discover_tools()` into a function that returns `name -> module`,
   rebuild `discover_tools()` on top of it, and have `ToolService.reload_tools()`
   call it. `tool_handler.get_registry()` keeps calling `discover_tools()`.
3. **C - Move discovery into `ToolService` and delete the other path.** Remove
   `discover_tools()`, `load_tool_module()`, and `get_registry()`/`run_tool()` in
   `tool_handler.py`, and make `ToolService` the sole implementation.
4. **D - Do nothing.** Leave tool discovery broken.

## Rubric Scoring
Scores are 1 (poor) to 5 (strong). Weighted total = sum of (score x weight).

| Option | Simplicity (3) | Reversibility (3) | Maintainability (3) | Reuse (2) | Fun / learning (2) | Performance (1) | Security / hygiene (1) | Weighted Total |
|---|---|---|---|---|---|---|---|---|
| A - Import fix only | 5: one-line change at [tool_service.py#L41](../../app/services/tool_service.py#L41) | 5: trivially revertible | 2: two implementations remain and already diverged | 2: `discover_tools()` stays unused at runtime | 2: no new learning | 3: neutral | 3: silent-failure path remains unless separately fixed | **50** |
| B - Shared discovery function | 4: about 20 lines across `tools/__init__.py` and `tool_service.py` | 4: contained to two modules | 5: one discovery function for both callers | 5: reuses the existing `discover_tools()` logic | 3: moderate | 3: neutral | 3: failures logged in one place | **61** |
| C - Absorb into `ToolService`, delete the rest | 2: touches three modules and removes public helpers | 3: deletions are harder to undo | 4: one class owns discovery | 3: discards working code | 4: clean design | 3: neutral | 3: neutral | **47** |
| D - Do nothing | 5: no change | 5: no change | 1: tools stay broken | 1: discards working code path | 1: none | 3: neutral | 3: neutral | **43** |

Option B wins on the weighted rubric (61 versus 50 for A, 47 for C, 43 for D).

## Decision Outcome
Choose **Option B**.

- `app/intelligence/tools/__init__.py` gets one function that returns
  `name -> module` for modules satisfying the contract. `discover_tools()` is
  rebuilt on top of it, so its existing signature and behavior remain.
- `ToolService.reload_tools()` calls that function instead of importing a package
  itself. The `app.S` import is removed.
- Discovery failures are logged through `get_logger(__name__)` and are never
  silently swallowed.
- `tool_handler.py` is left as it is. It is dead code at runtime today, and
  removing it is a separate cleanup.

Traded away: `tool_handler.get_registry()` and `ToolService` still keep two
registry caches, although they now share one discovery function. Option C would
have removed that duplication at a higher cost in reversibility and edit size.

## Consequences
- Positive: one discovery implementation for both callers; the silent failure
  mode is removed; the fix is small and reversible.
- Negative: `tool_handler.get_registry()` and `run_tool()` remain unused,
  duplicating the registry role.
- Follow-up work or risks accepted:
  - `tools.tool_packages` in [app/config.py](../../app/config.py#L53) and
    [settings.json](../../settings.json#L27) is not read by any code. It still says
    `intelligence.tools`. This run accepts updating its value to
    `app.intelligence.tools` without wiring it up. Wiring it is a follow-up.
  - Deleting the unused `tool_handler` helpers (Option C) is a follow-up if the
    duplication becomes a problem.
  - The narrate tool body is not repaired by this decision. See the spec's
    non-goals.

## Pattern Impact
- Uses: PAT-CODE-001 (accepted) for logging. No change requested.
- Creates: none in this run. A tool-contract pattern (`NAME: str` +
  `run(args: str, context: dict)`) is a candidate for a later proposed entry.
- Changes to accepted patterns: none.
