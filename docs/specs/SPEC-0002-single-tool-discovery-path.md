---
id: SPEC-0002
requirement: REQ-0002
adr: ADR-0001
status: accepted
date: 2026-10-10
---

# Single Tool Discovery Path for the Tool-Calling Pipeline

## 1. Requirement
> The tool-calling path MUST use one discovery path: `ToolService` MUST register
> every `app.intelligence.tools` module exposing `NAME: str` and callable
> `run(args: str, context: dict)` via the shared discovery function; discovery
> failures MUST be logged via `get_logger`, not swallowed; invocation MUST pass
> the `inference` service in context; `/api/v1/intel/tools` endpoints MUST reflect
> that registry; a test MUST exercise discovery and invocation without network or
> Ollama. The roll dice parser and the narrate body MUST NOT be changed under this
> requirement. (REQ-0002)

Decision: [ADR-0001](../adr/0001-single-tool-discovery-path.md), Option B (one
discovery function shared by `ToolService` and `discover_tools()`).

Verified facts this spec relies on (checked against the tree on 2026-10-10):
- [app/services/tool_service.py](../../app/services/tool_service.py#L38-L42) runs
  `import app.S.tools as _tools_pkg` inside `try/except`; `app/S` does not exist.
  The registry is therefore always empty and the failure is silent.
- `discover_tools()` in [app/intelligence/tools/__init__.py](../../app/intelligence/tools/__init__.py)
  uses the correct package and works, but its only caller is `get_registry()` in
  [app/intelligence/tool_handler.py](../../app/intelligence/tool_handler.py), which no
  code calls at runtime.
- Live callers reach tools only through `ToolService`: `build_services()`,
  [app/api/v1/intelligence.py](../../app/api/v1/intelligence.py), `GameService`, and
  `SessionService`.
- `narrate` ([app/intelligence/tools/narrate.py](../../app/intelligence/tools/narrate.py))
  has `NAME` and `run(args, context)`, so it satisfies the contract. Its body is
  broken (wrong `build_narrator_prompt` keyword arguments, `args` typed as `dict`
  but invoked with `str`, `inference.generate` does not exist on
  `OllamaInferenceService`). That body is a non-goal here.
- `roll.py` (`run_roll_tool`) and `clear.py` (`run_clear_tool`) have no `NAME` and no
  `run`, so discovery correctly skips them. They are non-goals here.
- `build_services()` in [app/services/build_services.py](../../app/services/build_services.py)
  builds `ToolService` before `inference`, so `inference` is not in the tool context.
- Import graph: `app/intelligence/*` imports only `app.services.logger` and
  `app.intelligence.client`. Importing `app.intelligence.tools` from `tool_service.py`
  creates no cycle.

## 2. Test Spec
Written before any work package. "Done" means all of the following pass.
New file: `tests/test_tool_calling.py`. Do not change `tests/conftest.py`.

1. **`test_discovery_registers_narrate`**
   - Exercises: `ToolService(discover_on_init=True).list_tools()`.
   - Expected: `"narrate"` is a key whose value is `"app.intelligence.tools.narrate"`.

2. **`test_discovery_skips_non_contract_modules`**
   - Exercises: the same `list_tools()` result.
   - Expected: neither `"roll"` nor `"clear"` is a key. (Update this assertion when
     those modules are brought under the contract.)

3. **`test_single_discovery_path`**
   - Exercises: `set(get_registry(refresh=True))` from
     `app.intelligence.tool_handler` and `set(ToolService().list_tools())`.
   - Expected: the two sets are equal, and both contain `"narrate"`.

4. **`test_invoke_passes_string_args_and_merged_context`**
   - Exercises: `ToolService(default_context={"repos": sentinel}, discover_on_init=False)`,
     `register_tool("echo", fn)`, then `invoke("echo", "hello", {"extra": 1})`. `fn`
     returns `(args, context)`.
   - Expected: `args == "hello"`, `context["repos"] is sentinel`,
     `context["extra"] == 1`.

5. **`test_invoke_unknown_tool_returns_message`**
   - Exercises: `ToolService(discover_on_init=False).invoke("nope")`.
   - Expected: returns `"Unknown tool: nope"` and does not raise.

6. **`test_invoke_exception_returns_error_string`**
   - Exercises: a registered tool that raises `ValueError("boom")`, invoked via `invoke`.
   - Expected: returns `"Tool bad error: boom"` and does not raise.

7. **`test_discovery_failure_is_logged_not_silent`**
   - Exercises: `monkeypatch.setattr(app.intelligence.tools, "TOOLS_PACKAGE",
     "app.no_such_tools")`, then `ToolService(discover_on_init=True)`, with `caplog`
     at ERROR level.
   - Expected: `list_tools()` returns `{}`, and at least one ERROR record is
     captured. If `caplog` does not see the record because `init_logging` disables
     propagation, assert on the logger from `get_logger` with `monkeypatch` instead.

8. **`test_api_lists_and_invokes_registered_tool`**
   - Exercises: `services = build_services(make_default_repos(), enable_tool_discovery=True)`,
     `app = create_app(services=services)`, `TestClient(app)`.
     `services["tool"].register_tool("echo", lambda a, c: f"echo:{a}")`, then
     `GET /api/v1/intel/tools` and `POST /api/v1/intel/tools/echo/invoke` with
     `{"args": "hi"}`.
   - Expected: GET 200 and `"narrate"` appears in the `tools` names. POST 200 and
     `body["text"] == "echo:hi"`.

9. **`test_build_services_injects_inference_into_tool_context`**
   - Exercises: `services = build_services(make_default_repos(), enable_tool_discovery=False)`.
   - Expected: `services["tool"].default_context["inference"] is services["inference"]`
     and `services["tool"].default_context["repos"]` is the repos dict passed in.

10. **Existing suite still passes.**
    - Exercises: `tests/test_app_factory.py` and `tests/test_logging_consistency.py`.
    - Expected: all tests pass. Total is 4 existing plus 9 new, so 13 passed.
    - `grep -rn "app\.S" app` returns no output.

No test in this spec may require network access or a running Ollama. Constructing
`OllamaInferenceService` starts a daemon thread but does not connect, and the
existing `conftest.py` already does this.

## 3. Work Packages

### WP-1: Add a shared discovery function in `app/intelligence/tools/__init__.py`
- **Files:** `app/intelligence/tools/__init__.py`
- **Inputs:** The file already defines `TOOLS_PACKAGE = "app.intelligence.tools"`,
  `logger = get_logger(__name__)`, `discover_tools(package: str | None = None) -> dict[str, Callable]`
  (returns `name -> run`), and `load_tool_module(module_name)`. `discover_tools` logs
  a package import failure at DEBUG and a module import failure with
  `logger.exception`. `pkgutil` and `importlib` are already imported.
- **Outputs:**
  1. Add `discover_tool_modules(package: str | None = None) -> dict[str, types.ModuleType]`.
     It resolves `pkg_name = package or TOOLS_PACKAGE` at call time, so a
     monkeypatched `TOOLS_PACKAGE` takes effect. If the package import fails, it calls
     `logger.exception("Failed to import tool package %s", pkg_name)` and returns `{}`.
     It iterates `pkgutil.iter_modules` over the package. For each module that fails
     to import it calls `logger.exception("Failed to import tool module %s", modname)`
     and continues. A module is accepted when `NAME` is a `str` and `run` is callable,
     and is stored as `result[NAME] = module`. Any other module is skipped with
     `logger.debug("Skipping %s: no NAME/run contract", modname)`.
  2. Rebuild `discover_tools(package)` as
     `{name: mod.run for name, mod in discover_tool_modules(package).items()}`. Its
     signature and return type do not change.
  3. Add `"discover_tool_modules"` to `__all__`.
  4. Leave `load_tool_module` unchanged.
- **Acceptance criteria:** `discover_tool_modules()` returns a dict whose only key is
  `"narrate"` in the current tree, and whose value is the `app.intelligence.tools.narrate`
  module. `discover_tools()` returns `{"narrate": <narrate.run>}`. A missing package
  logs at ERROR and returns `{}`, not a silent empty result. No `print(` call is
  introduced. No new third-party import is introduced.
- **Patterns used/created:** PAT-CODE-001 (accepted, logging via `get_logger`);
  ADR-0001 (proposed).

### WP-2: Make `ToolService` use the shared discovery function
- **Files:** `app/services/tool_service.py`
- **Inputs:** WP-1 is complete, so `discover_tool_modules(package=None)` exists in
  `app.intelligence.tools`. The file currently has a module-level `try/except` that
  runs `import app.S.tools as _tools_pkg` (lines 38-42), and `reload_tools()`
  iterates `_tools_pkg.__path__` with `pkgutil` and `importlib` directly.
- **Outputs:**
  1. Delete the module-level `try/except` block that imports `app.S.tools`.
  2. Add `from app.intelligence.tools import discover_tool_modules` among the imports.
  3. Rewrite the body of `reload_tools()` so that, under `self._lock`, it clears
     `_registry` and `_modules`, then calls `discover_tool_modules()`, and for each
     `(name, mod)` sets `self._registry[name] = mod.run` and `self._modules[name] = mod`.
  4. Remove the `importlib` and `pkgutil` imports if nothing else in the file uses them.
  5. Change the `reload_tools` docstring to refer to `app.intelligence.tools`.
  6. Leave `list_tools`, `invoke`, `register_tool`, `unregister_tool`, `_SimpleLogger`,
     and the `__main__` block unchanged.
- **Acceptance criteria:** The file contains no `app.S` and no `_tools_pkg`.
  `ToolService(discover_on_init=True).list_tools()` returns
  `{"narrate": "app.intelligence.tools.narrate"}`. `invoke` behaves exactly as it did
  before. `import app.services.build_services` succeeds with no circular-import error.
  The file contains no `print(` call.
- **Patterns used/created:** PAT-CODE-001 (accepted); ADR-0001 (proposed).

### WP-3: Pass `inference` into the tool context in `build_services`
- **Files:** `app/services/build_services.py`
- **Inputs:** The current order is: `ToolService(default_context={"repos": repos}, ...)`,
  then `GameService()`, then `settings = get_settings()`, then
  `inference = OllamaInferenceService(settings)`. `ToolService.__init__` copies
  `default_context` at construction time, so `inference` must exist before the
  `ToolService` is built.
- **Outputs:**
  1. Move `settings = get_settings()` and `inference = OllamaInferenceService(settings)`
     above the `ToolService` construction.
  2. Pass `default_context={"repos": repos, "inference": inference}` to `ToolService`.
  3. Leave `game_service`, the returned dict keys (`session`, `tool`, `game`,
     `inference`), and the `enable_tool_discovery` parameter unchanged.
- **Acceptance criteria:** After `build_services(repos, enable_tool_discovery=False)`,
  `services["tool"].default_context["inference"] is services["inference"]`,
  `services["tool"].default_context["repos"] is repos`, and the returned dict has
  exactly the keys `session`, `tool`, `game`, `inference`.
- **Patterns used/created:** none beyond ADR-0001 (proposed).

### WP-4: Add the tool-calling test module
- **Files:** `tests/test_tool_calling.py` (new). Do not modify `tests/conftest.py`.
- **Inputs:** WP-1, WP-2, and WP-3 are complete. Imports available:
  `from app.intelligence import tools as tools_pkg` (test 7 patches `tools_pkg.TOOLS_PACKAGE`),
  `from app.intelligence.tool_handler import get_registry`, `from app.services.tool_service import ToolService`,
  `from app.services.build_services import build_services`, `from app.services.repos import make_default_repos`,
  `from app.factory import create_app`, `from fastapi.testclient import TestClient`.
- **Outputs:** Implement the nine tests from Test Spec items 1-9 in `tests/test_tool_calling.py`,
  with the same names and assertions. Use `pytest` fixtures and `monkeypatch`/`caplog`
  as stated.
- **Acceptance criteria:** `./venv-dnd-server/bin/python -m pytest tests/test_tool_calling.py`
  passes all nine tests. `./venv-dnd-server/bin/python -m pytest` reports 13 passed.
  No test opens a network connection. `ruff check tests` reports no new findings.
- **Patterns used/created:** none.

### WP-5: Align the unused `tool_packages` setting with the real package
- **Files:** `app/config.py`, `settings.json`
- **Inputs:** [app/config.py](../../app/config.py#L53) defines
  `tool_packages: list[str] = Field(default_factory=lambda: ["intelligence.tools"])`.
  [settings.json](../../settings.json#L27) sets `"tool_packages": ["intelligence.tools"]`.
  No code reads this setting. This is a documented decision in ADR-0001.
- **Outputs:** Change both values to `["app.intelligence.tools"]`. Do not wire the
  setting into `ToolService` or `build_services` in this package.
- **Acceptance criteria:** `get_settings().tools.tool_packages == ["app.intelligence.tools"]`.
  `grep -rn "intelligence.tools\"" app/config.py settings.json` returns no output.
- **Patterns used/created:** none.

### WP-6: Update the stale known-gap note in the agent instructions
- **Files:** `.github/copilot-instructions.md`
- **Inputs:** The "Known gaps / traps" section has a first bullet, "Tool discovery is
  currently broken", that says `app/services/tool_service.py` imports
  `intelligence.tools`. After WP-1 to WP-3 this is no longer true.
- **Outputs:** Replace that bullet with one line stating that discovery uses
  `app.intelligence.tools.discover_tool_modules` via `ToolService.reload_tools()`, and
  that `tool_handler.get_registry()` shares that function. Leave the other gap bullets
  unchanged. Do not change the narrate or roll notes beyond what WP-1 to WP-3 require.
- **Acceptance criteria:** The file no longer says that discovery imports
  `intelligence.tools` or is broken. The other bullets are unchanged.
- **Patterns used/created:** none.

Dependency order: WP-1 -> WP-2 -> WP-3 -> WP-4. WP-5 and WP-6 are independent.
WP-4 depends on WP-1 to WP-3, because test 7 monkeypatches `TOOLS_PACKAGE` and
test 9 needs the inference injection.

## 4. Other Details
- **Risks:**
  - Circular import between `app.services` and `app.intelligence`. Checked statically:
    no cycle. WP-2 requires an import check to confirm this.
  - After this spec, invoking `narrate` through the API returns the string
    `"Tool narrate error: 'str' object has no attribute 'get'"`, not a successful
    narration. This is expected and documented. It is an error string, not a crash.
  - `caplog` may not capture logs if propagation is disabled. Test 7 has a fallback.
  - `ToolService.invoke` holds `RLock` during tool execution, so tool calls are
    serialized. This is existing behavior and is not changed here.
- **Rollback plan:** Revert the WP-1 to WP-6 edits and delete `tests/test_tool_calling.py`.
  No data, schema, or persisted state changes. The git revert is a single commit.
- **Patterns applied/created:**
  - PAT-CODE-001 (accepted): applied. Logging via `get_logger`.
  - ADR-0001 (proposed): applied. Requires human sign-off.
  - No new patterns created in this package. A tool-contract pattern is a candidate
    for a later proposed entry.
- **Non-goals (explicitly out of scope):**
  - Repairing the narrate tool body: `build_narrator_prompt` keyword arguments,
    `inference.generate` (should be `inference.client.generate`), `args: dict` versus
    `str`, and `game` and `session_run` context. Recommended as a separate requirement
    (REQ-0003).
  - The roll dice parser (`roll.py`) and bringing `roll.py` or `clear.py` under the
    `NAME`/`run` contract.
  - Deleting the unused `tool_handler.run_tool()` and `get_registry()` helpers.
  - Wiring `tools.tool_packages` into code.
  - Migrating deprecated `@app.on_event` hooks in `app/factory.py`.
  - Any production hardening (auth, multi-tenancy, scaling).
