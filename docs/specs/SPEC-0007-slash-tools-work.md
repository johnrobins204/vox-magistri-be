---
id: SPEC-0007
requirement: REQ-0008
adr: ADR-0004
status: proposed
date: 2026-10-11
---

# Slash Tools Work End to End: `narrate`, `roll`, Deletion of `clear`, Worker Dispatch, and a Strict `ToolService`

## 1. Requirement
> The tool-calling path MUST work end to end: (1) `narrate` MUST implement the `NAME: str` /
> `run(args: str, context: dict)` contract, MUST produce its reply through a real inference call
> on the injected `inference` service, and MUST build its prompt with the current
> `build_narrator_prompt` signature; (2) `roll` MUST be a discoverable tool that parses dice
> expressions (NdM with +/- modifiers; dice count and sides MUST be bounded; keep/advantage MAY be
> added if cheap) using an injectable random source and returns structured text and meta; (3)
> `clear` MUST be removed: `app/intelligence/tools/clear.py` MUST be deleted, `clear` MUST NOT be
> registered or dispatchable, no replacement, clear marker, or history-boundary logic MUST be
> added; an unknown `/clear` MUST produce the normal unknown-tool error; (4) slash commands
> (`/name args`) MUST be dispatched in the message flow shared by REST and WebSocket; (5) `ToolService` MUST NOT
> hold a global lock while a tool runs, MUST report unknown tools and tool failures as errors (not
> HTTP 200 text with `error` null), and MUST NOT let client-supplied `context` override service
> objects; (6) tests MUST run without network or Ollama, and `tests/test_tool_calling.py` and
> `.github/instructions/tools.instructions.md` MUST be updated to match. This requirement lifts the
> REQ-0002 exclusion of the roll parser and narrate body. Streaming (REQ-0007), auth/CORS
> (REQ-0009), API schema (REQ-0010), campaign domain (REQ-0015) and repo hygiene (REQ-0012) MUST
> NOT be changed. The two-step narrate/adjudicate flow (`settings.prompts.enable_narration` /
> `enable_adjudication`) is an open gate and MUST NOT be implemented without an explicit human
> decision. (REQ-0008)

Linked ADR: [ADR-0004](../adr/0004-slash-tools-in-worker.md) (**accepted** by the human 2026-10-11).
Linked patterns:
[PAT-ARCH-004](../patterns/architecture/PAT-ARCH-004-slash-tools-in-worker.md) (**accepted** 2026-10-11; applied by this spec),
[PAT-ARCH-003](../patterns/architecture/PAT-ARCH-003-prompt-pipeline-in-worker.md) (accepted; the two ADR-0004 amendments were approved by the human 2026-10-11 and applied to it),
[PAT-ARCH-001](../patterns/architecture/PAT-ARCH-001-session-store-single-api.md) (accepted, applied, NOT modified),
[PAT-ARCH-002](../patterns/architecture/PAT-ARCH-002-stdlib-sqlite-store.md) (accepted, NOT modified),
[PAT-CODE-001](../patterns/code/PAT-CODE-001-centralized-logging.md) (accepted, applied, NOT modified).

### Status of this spec and open gates (read before starting any work package)
Gates G-1 and G-2 were accepted by the human on 2026-10-11 (all defaults below approved as written); implementation may proceed.
No decision beyond G-1 and G-2 is relied on. Decision numbers D1..D4 refer to ADR-0004:
D1 dispatch in the worker; D2 narrate's LLM access and the shared `_ollama_lock`; D3 the
`ToolService` error contract and HTTP mapping; D4 `clear` is deleted (human decision 2026-10-11).

| Gate | What | Effect on this spec |
|---|---|---|
| **G-1** | Human acceptance of ADR-0004 **and** PAT-ARCH-004 (`proposed` -> `accepted`). | ACCEPTED 2026-10-11 (was: blocks every work package). |
| **G-2** | Human acceptance of the TWO PAT-ARCH-003 amendments flagged in ADR-0004: (i) "slash-command jobs skip the chat builder and run the tool"; (ii) "worker `chat` and the service's `generate` run under one `_ollama_lock`". | ACCEPTED 2026-10-11; the two amendments are applied to PAT-ARCH-003 (done by the orchestrator, not by a work package). WP-6..WP-8 are unblocked. |

Remaining open product gates (non-blocking; recorded as **defaults**; do not implement anything
beyond these defaults without an explicit human decision, which would amend this spec):

| Gate | Default used by this spec |
|---|---|
| (a) `enable_narration` / `enable_adjudication` remain unread (two-step narrate/adjudicate flow) | **Out of scope; stay unread.** No code reads them; no implementation. |
| (b) An unknown `/x` is an error and is NOT sent to the LLM | **An error** (user message `error`, no reply). It is not sent to the LLM. This includes `/clear`. |
| (c) Tool exchanges stay in LLM history like any completed message | **They remain** in history like any completed message (`/roll`, `/narrate` and their replies). |

### Traceability (REQ-0008 item -> work packages -> tests)
| REQ-0008 item | Work packages | Tests |
|---|---|---|
| (1) `narrate` contract, real inference call, current prompt signature | WP-4 (needs `generate` from WP-6 only for real use; tests use a fake) | T-20, T-21, T-22, T-38 |
| (2) `roll` discoverable, bounded, injectable rng, structured output | WP-3 | T-01..T-09, T-14, T-33, T-34 |
| (3) `clear` deleted; not registered or dispatchable; `/clear` is a normal unknown tool | WP-5 (deletion, registry, `/invoke` 404); WP-7 (worker `/clear` error path) | T-29, T-30, T-31, T-32 |
| (4) Slash dispatch shared by REST and WS | WP-7, WP-8 | T-32, T-33, T-34, T-35, T-36, T-37, T-38, T-39, T-40, T-41, T-42 |
| (5) `ToolService` errors, lock, context | WP-1, WP-2 (D3); WP-6 (D2 lock); WP-8 (composition) | T-10..T-13, T-15..T-18, T-19, T-23..T-28, T-43, T-44, T-45 |
| (6) Tests without network; `test_tool_calling.py` and `tools.instructions.md` updated | WP-1, WP-2 (test updates), WP-9 (docs) | T-10..T-13 (updated) plus every test in this spec runs offline |

### Assumptions where the architect output was ambiguous (flagged for review)
- **A-1** `UnknownToolError` is defined in `app/services/tool_service.py` (ADR only places `ToolError` in `app/intelligence/tools/__init__.py`).
- **A-2** Every non-2xx response from `invoke_tool` has the JSON body `{"text": null, "meta": null, "error": "<msg>"}`; the 404 body additionally has `"detail": "<msg>"` (ADR mentions both `detail` and `ToolInvokeResp.error`). Response models are unchanged.
- **A-3** `roll.evaluate(expr, rng)` returns the full `{"text": str, "meta": dict}` dict; `run` returns it unchanged. The only method called on the random source is `rng.randint(1, sides)`.
- **A-4** Roll text echoes a *normalized* expression (lowercase, all whitespace removed; `adv`/`dis` are NOT expanded in the echo). Dice are listed in rolled order, dropped dice in parentheses. Keep ties keep the earliest index. No whitespace inside a token (`2 d6` is invalid).
- **A-5** Any exception from a tool in the worker (including `ToolError` and non-`ToolError` bugs) is written as `meta.error = str(exc)` on the user message, same as the chat path today. Only `ToolError`/`UnknownToolError` messages are meant for users.
- **A-6** The worker MUST NOT hold `_ollama_lock` while a tool runs (it is a non-reentrant `threading.Lock`; `narrate` calls `generate`, which takes it). The worker holds it only around its own `client.chat` call.
- **A-7** `generate_tokens` (WS streaming stub, REQ-0007) is left untouched and still calls `client.generate` without the lock. Known gap, owned by REQ-0007.
- **A-8** `ToolService.invoke` drops the old `timeout_seconds` parameter (it was a documented no-op). WP-1 MUST confirm no caller passes it before removing.
- **A-9** `clear.py` is removed by plain file deletion. WP-5 MUST first confirm that nothing in `app/` or `tests/` imports `app.intelligence.tools.clear` or `run_clear_tool` (the stub is not discovered today, so none is expected); if something does, stop and report instead of porting. Stale `__pycache__` files are not tool modules (discovery uses `pkgutil.iter_modules` on source modules) and need no action.

### Verified facts (checked against the tree on 2026-10-11)
- Next free spec number is 0007 (`docs/specs/` holds SPEC-0001..SPEC-0006).
- `app/intelligence/tools/` holds `__init__.py` (discovery: `discover_tool_modules`, `TOOLS_PACKAGE`), `narrate.py`
  (has `NAME`/`run` but treats `args` as a dict and calls `build_narrator_prompt(game=..., ...)`, which no longer exists),
  `roll.py` (stub `run_roll_tool(args, session, game, session_run)`) and `clear.py` (stub `run_clear_tool(...)`; uses
  `session_run.entries.clear()`; to be deleted by WP-5). Only `narrate` is discovered today.
- `build_narrator_prompt(adjudicator_output: str, params: NarratorVoiceParams, player_intent: str | None = None) -> str` is in
  `app/intelligence/prompt_builders.py`. `NarratorVoiceParams` fields: `tone`, `dm_persona`, `verbosity`, `sensory_focus`,
  `consequence_level`. Settings: `get_settings().prompts` has `verbosity_default` and `dm_voice` with `tone`, `persona`,
  `sensory_focus`, `consequence_level`.
- `ToolService.invoke(name, args="", context=None, timeout_seconds=None)` holds `self._lock` (RLock) for the whole run, returns
  `"Unknown tool: x"` / `"Tool x error: e"` as plain values, and merges caller context over `default_context`.
  `register_tool(name, func, module=None)`, `unregister_tool`, `reload_tools`, `list_tools` exist and MUST keep working.
- `invoke_tool` in `app/api/v1/intelligence.py` catches every exception and returns HTTP 200 with `error=str(e)`; for a non-dict
  result it returns `text=str(result)`, `error=None`.
- `app.intelligence.tool_handler.detect_tool(payload) -> (name | None, args | None)`: regex `^/([^\s/]+)(?:\s+(.*))?$` on the stripped
  payload, name lowercased, args `""` when absent. It has no caller in `app/`.
- `OllamaInferenceService.__init__(self, settings)` has no `generate` and no tool support. `_worker_loop` marks the job `running`, then
  inside one `try` builds `build_chat_messages(...)` and calls `self.client.chat(messages)`, then `_append_reply(...)` and
  `_update_message_status(..., "completed")`; the `except` marks the user message `error` with `{"error": str(exc)}`.
  `_append_reply(self, store, session_id, user_message_id, text)` writes `meta={"reply_to": user_message_id}`.
- `OllamaClient.generate(prompt, *, model=None)` is `self.chat([{"role": "user", "content": prompt}], model=model)`.
  `IntelligenceError` lives in `app/intelligence/client.py`.
- `build_services(repos, enable_tool_discovery=True)` builds the inference service first, then
  `ToolService(default_context={"repos": repos, "inference": inference}, ...)`, and returns `{"session", "tool", "inference"}`.
- `build_chat_messages(system, history, current_message_id, current_text, *, max_turns, max_field_len)` loops `history`, stops at the
  current id, keeps `completed` messages with role `user`/`assistant`, takes the last `max_turns`.
- `tests/session_helpers.make_stub_service(**settings_kwargs)` builds `OllamaInferenceService(Settings(...))` (connects to nothing);
  `wait_idle(svc)`, `AUTH`, `FakeInference` exist. `tests/conftest.py` has fixtures `app`, `client`, `stub_svc` (chat patched to
  `"stub reply"`), `session_store` (`SqliteSessionStore(":memory:")`), `stub_client`.
- REST message route: `POST /api/v1/sessions/{sid}/messages` with header `AUTH`, body `{"content": ...}`, answers 202;
  `GET /api/v1/sessions/{sid}/messages` (with `AUTH`) lists messages. WS: `/api/v1/ws/sessions/{sid}`, first frame is a
  `snapshot`, send `{"action": "user_message", "text": ...}`, receive `entry` (user), then `entry` (reply) + `done`, or
  `{"type": "error", "message": ..., "message_id": ...}` when the user message ends `error`.
- Guard tests scan `app/`: `tests/test_single_session_model.py` (no `SessionService`, `GameService`, `session_service`,
  `game_service`, `SessionEntry`) and `tests/test_logging_consistency.py` (no `logging.getLogger(` outside `logger.py`, no `print(`).
- Tooling: Python 3.13; `pyproject.toml` has `[tool.ruff]` (line length 100, select E,F,I,UP,B) and `[tool.black]` (line length 100);
  `requirements-dev.txt` pins pytest, pytest-asyncio, ruff, black. **There was no shell when this spec was written; nothing was run.**

### Verification commands (run after each work package, and all of them at the end)
```
./venv-dnd-server/bin/pytest -q -p no:warnings -p no:cacheprovider
./venv-dnd-server/bin/ruff check app tests
./venv-dnd-server/bin/black --check app tests
```
(The repo formats with black, not `ruff format`; do not run `ruff format`.)

## 2. Test Spec
Written first. Test ids are `T-NN`. **Every test runs with no network and no Ollama**: tests that need the inference service use
`make_stub_service()` (which connects to nothing), patch `svc.client.chat` with a recording stub, use
`SqliteSessionStore(":memory:")`, use a scripted fake random source (a small class with `randint(a, b)` that returns the next value
of a list), and shut services down with `asyncio.run(svc.shutdown())`. `httpx` is never reached. Fixed values below
(e.g. `"2d6: [3, 4] = 7"`) assume `ScriptedRng([3, 4])`.

**Counts:** 45 tests: **41 new, 4 updated** (T-10..T-13 are the updated ones in `tests/test_tool_calling.py`). Five existing tests in
`tests/test_tool_calling.py` MUST stay green unchanged: `test_discovery_registers_narrate`, `test_single_discovery_path`,
`test_discovery_failure_is_logged_not_silent`, `test_api_lists_and_invokes_registered_tool`,
`test_build_services_injects_inference_into_tool_context`. All other existing tests MUST stay green.

### 2.1 `tests/test_roll.py` (new file; WP-3)
| Id | Test | Exercises | Expected observable outcome |
|---|---|---|---|
| T-01 | `test_empty_args_rolls_one_d20` | `roll.run("", {"rng": ScriptedRng([14])})` | `text == "1d20: [14] = 14"`; `meta["expression"] == "1d20"`; `meta["total"] == 14`. |
| T-02 | `test_basic_dice_with_modifier` | `run("2d6+3", ...)` with `[3, 4]`; and `run("1d8 - 2", ...)` with `[5]` | `"2d6+3: [3, 4] + 3 = 10"`, total 10; `"1d8-2: [5] - 2 = 3"`, total 3 (negative sign shown as ` - `). A constant-only `run("5", ...)` gives `"5: 5 = 5"`. |
| T-03 | `test_keep_highest_and_lowest` | `run("4d6kh3+2", rng [6,4,3,1])`; `run("4d6kl3", rng [6,4,3,1])`; out-of-order `run("4d6kh3", rng [3,6,1,4])`; tie `run("3d6kh1", rng [5,5,2])` | `"4d6kh3+2: [6, 4, 3, (1)] + 2 = 15"`; kl: `"4d6kl3: [(6), 4, 3, 1] = 8"`; `"4d6kh3: [3, 6, (1), 4] = 13"`; tie keeps earliest: `"3d6kh1: [5, (5), (2)] = 5"`. Meta dice term `rolls == [6,4,3,1]`, `kept == [6,4,3]`, `keep == 3`, `value == 13`. |
| T-04 | `test_advantage_and_disadvantage` | `run("adv", rng [7,15])`, `run("dis", rng [7,15])`, `run("adv+5", rng [7,15])` | adv: `"adv: [(7), 15] = 15"`; dis: `"dis: [7, (15)] = 7"`; `adv+5`: `"adv+5: [(7), 15] + 5 = 20"`, total 20. Meta term has `count == 2`, `sides == 20`, `keep == 1`. |
| T-05 | `test_case_insensitive_and_whitespace` | `run("  2D6 + 1d4 - 1 ", rng [3,4,2])` and `run("4D6KH3", ...)` | Echo is normalized: `meta["expression"] == "2d6+1d4-1"`; text starts `"2d6+1d4-1: "`; total `3+4+2-1 == 8`. Works with mixed case and spaces between tokens. `run("2 d6", ...)` raises `ToolError` (no spaces inside a token). |
| T-06 | `test_bounds_rejected` (parametrized) | `run(expr, {"rng": ScriptedRng([1]*500)})` for each of: `"0d6"`, `"101d6"`, `"1d1"`, `"1d1001"`, `"2d6kh3"`, `"2d6kh0"`, `"2d6kl3"`, `"1d20+1001"`, `"12345d6"` (more than 4 digits), `"60d6+60d6"` (more than 100 dice total), `"1+1+1+1+1+1+1+1+1+1+1"` (11 terms), a 65-character string (`"1" + "+1" * 32`), `"hello"`, `"2d"`, `"1d20++3"`, `"2d6kx1"`, `"-1d6"`, `"2adv"` | Each raises `app.intelligence.tools.ToolError`; no `rng.randint` call is made for syntactically invalid or over-bound input. Exact messages used: `"Dice sides must be 2-1000"`, `"Dice count must be 1-100"`, `"Total dice must be at most 100"`, `"Keep must be between 1 and the dice count"`, `"Constants must be 0-1000"`, `"At most 10 terms"`, `"Expression too long (max 64 characters)"`, else `"Invalid dice expression. Usage: /roll [NdM[kh\|klK]][+/-...] (e.g. 2d6+3, adv)"`. Boundary values pass (a second, non-parametrized assertion block): `"100d2"`, `"1d1000"`, `"1+1+1+1+1+1+1+1+1+1"` (10 terms), `"1d20+1000"`, and a 64-character valid expression (`"1d20" + " " * 55 + "+ 1d4"`). |
| T-07 | `test_seeded_rng_is_deterministic_and_default_rng_works` | `evaluate("4d6kh3+2", random.Random(1234))` twice; `run("2d6", {})` with no rng | The two seeded results are equal (text and meta). With no `rng` in context the module-level `random.Random()` is used: result total is between 2 and 12, no error. |
| T-08 | `test_run_returns_structured_text_and_meta` | `run("2d6kh1+4-d4", rng [2,6,3])` | Returns a `dict` with exactly keys `text`, `meta`. `meta["tool"] == "roll"`, `meta["expression"] == "2d6kh1+4-d4"`, `meta["total"] == 7`. `meta["terms"]` is a list of 3 dicts: dice terms have keys `sign, count, sides, keep, rolls, kept, value`; the constant term has keys `sign, constant, value` (`sign` is `"+"` or `"-"`; `value` is the unsigned subtotal; `keep` is `None` when absent). |
| T-09 | `test_roll_is_discoverable_and_invokable_without_network` | `ToolService(discover_on_init=True)`; `list_tools()`; `invoke("roll", "2d6", {"rng": ScriptedRng([3,4])})` | `list_tools()["roll"] == "app.intelligence.tools.roll"`; the invoke result is `{"text": "2d6: [3, 4] = 7", "meta": {...}}` with `meta["tool"] == "roll"`. |

### 2.2 `tests/test_tool_calling.py` (updated + new; WP-1, WP-2, WP-3, WP-4, WP-5, WP-8)
Updated (rewrite these four; keep their intent, change the expectations to the new contract), WP-1. Note: the existing `test_discovery_skips_non_contract_modules` currently asserts `roll` and `clear` are absent from discovery; the rewrite (T-10) removes both assertions, and `clear` absence is then asserted by T-30 instead:

| Id | Test | Exercises | Expected observable outcome |
|---|---|---|---|
| T-10 | `test_discovery_skips_non_contract_modules` (UPDATED) | Build a temporary tools package under `tmp_path` (`__init__.py`, `good.py` with `NAME="good"` + `run`, `bad.py` with no `NAME`), `monkeypatch.syspath_prepend(tmp_path)`, `monkeypatch.setattr(tools_pkg, "TOOLS_PACKAGE", "<unique_pkg_name>")`, `ToolService(discover_on_init=True)` | `list_tools()` has exactly the key `"good"`; `"bad"` is skipped. (No longer asserts anything about `roll`/`clear`, so it passes before and after WP-3/WP-5.) |
| T-11 | `test_invoke_passes_string_args_and_merged_context` (UPDATED) | Register a tool that records `(args, ctx)` and returns `"ok"`; `ToolService(default_context={"repos": sentinel})`; `invoke("echo", "hello", {"extra": 1})` | The tool saw `args == "hello"`, `ctx["repos"] is sentinel`, `ctx["extra"] == 1`; the return value is `{"text": "ok", "meta": {}}`. |
| T-12 | `test_invoke_unknown_tool_raises` (UPDATED; replaces `..._returns_message`) | `invoke("nope")` | Raises `UnknownToolError` (from `app.services.tool_service`) with message `"Unknown tool: nope"`. |
| T-13 | `test_invoke_exception_propagates` (UPDATED; replaces `..._returns_error_string`) | Tool raising `ValueError("boom")`; tool raising `ToolError("bad input")` | `ValueError` propagates with `"boom"`; `ToolError` propagates with `"bad input"`; nothing is returned as text. |

New, `ToolService` (WP-1):

| Id | Test | Exercises | Expected observable outcome |
|---|---|---|---|
| T-15 | `test_invoke_normalizes_results` | Tools returning `"plain"`, `{"text": "t", "meta": {"a": 1}}`, `{"text": "t"}`, and `42` | Results: `{"text": "plain", "meta": {}}`, `{"text": "t", "meta": {"a": 1}}`, `{"text": "t", "meta": {}}`; `42` raises `TypeError`. |
| T-16 | `test_client_context_cannot_override_server_keys` | `ToolService(default_context={"inference": real, "repos": real_repos})`; `invoke("echo", "", {"session_id": "s1"}, client_context={"inference": evil, "repos": evil, "store": evil, "session_id": "evil", "message_id": "evil", "logger": evil, "rng": evil, "extra": 1})` with `caplog` at WARNING on `app.services.tool_service` | Tool saw `ctx["inference"] is real`, `ctx["repos"] is real_repos`, `ctx["session_id"] == "s1"`, `ctx["extra"] == 1`; `ctx["store"]`, `ctx["message_id"]`, `ctx["rng"]` are absent, `ctx["logger"] is not evil`. One WARNING record names the dropped keys (`inference`, `repos`, `store`, `message_id`, `logger`, `rng`, `session_id`) and does NOT contain the string form of `evil`. |
| T-17 | `test_client_context_cannot_override_default_context_keys` | `default_context={"custom": "server"}`; `client_context={"custom": "client", "fresh": 2}` | Tool saw `ctx["custom"] == "server"` and `ctx["fresh"] == 2`; a WARNING names `custom`. |
| T-18 | `test_tool_runs_outside_the_registry_lock` | Tool `slow` blocks on a `threading.Event`; tool `fast` returns `"fast"`; start `invoke("slow")` on a thread, wait until it has started; then call `invoke("fast")` and `list_tools()` from the main thread | `invoke("fast")` returns `{"text": "fast", "meta": {}}` and `list_tools()` returns while `slow` is still blocked (use a join/timeout of 2 s; fail if exceeded). After setting the event the slow call finishes. |

New, narrate (WP-4):

| Id | Test | Exercises | Expected observable outcome |
|---|---|---|---|
| T-20 | `test_narrate_empty_args_raises_tool_error` | `narrate.run("", ctx)` and `run("   ", ctx)` with a fake inference | `ToolError("Usage: /narrate <what happens>")`; the fake's `generate` is never called. |
| T-21 | `test_narrate_builds_current_prompt_and_uses_inference` | Fake inference with `generate(prompt)` recording its argument and returning `"The tavern hums."`; `narrate.run("  describe the tavern  ", {"inference": fake})` | `generate` called once with exactly `build_narrator_prompt("describe the tavern", NarratorVoiceParams(tone=p.dm_voice.tone, dm_persona=p.dm_voice.persona, verbosity=p.verbosity_default, sensory_focus=p.dm_voice.sensory_focus, consequence_level=p.dm_voice.consequence_level), None)` where `p = get_settings().prompts`; result is `{"text": "The tavern hums.", "meta": {"tool": "narrate"}}` (no `prompt` key in meta). |
| T-22 | `test_narrate_via_tool_service_uses_injected_inference` | `ToolService(default_context={"inference": fake})`, discovery on; `invoke("narrate", "a storm")` | Result text equals the fake's return; the fake was called once; `meta == {"tool": "narrate"}`. |

New, roll discovery (WP-3):

| Id | Test | Exercises | Expected observable outcome |
|---|---|---|---|
| T-14 | `test_discovery_registers_roll_and_narrate` | `ToolService(discover_on_init=True).list_tools()` | `roll` -> `"app.intelligence.tools.roll"`; `narrate` -> `"app.intelligence.tools.narrate"`. |

New, `clear` deletion (WP-5; the fourth deletion test, T-32, is in section 2.3 because it needs worker dispatch). `clear` is deleted, not ported; there is no replacement:

| Id | Test | Exercises | Expected observable outcome |
|---|---|---|---|
| T-29 | `test_clear_module_file_is_deleted` | `pathlib.Path(tools_pkg.__file__).parent / "clear.py"` where `tools_pkg` is `app.intelligence.tools` | `.exists()` is `False`. (Also assert `importlib.util.find_spec("app.intelligence.tools.clear") is None`.) |
| T-30 | `test_clear_is_not_registered` | `ToolService(discover_on_init=True).list_tools()`; `app.intelligence.tools.discover_tool_modules()`; `app.intelligence.tools.discover_tools()` | `"clear"` is not a key in any of the three results (`roll` and `narrate` still are). |
| T-31 | `test_invoke_endpoint_clear_is_unknown_tool_404` | `build_services(make_default_repos(), enable_tool_discovery=True)`, `create_app(services=...)`, `POST /api/v1/intel/tools/clear/invoke` `{"args": ""}` | HTTP 404; `error == "Unknown tool: clear"` and `detail == "Unknown tool: clear"`; `text` and `meta` null. (This is the same unknown-tool contract as T-24; it must hold for `clear` with no special-casing.) |

New, endpoint (WP-2). Each builds the app like the existing `test_api_lists_and_invokes_registered_tool` (keep the `services` dict) and registers a tool with `services["tool"].register_tool`:

| Id | Test | Exercises | Expected observable outcome |
|---|---|---|---|
| T-23 | `test_invoke_endpoint_success_passes_meta` | Tool returns `{"text": "hi", "meta": {"k": 1}}` | HTTP 200; `{"text": "hi", "meta": {"k": 1}, "error": null}`. |
| T-24 | `test_invoke_endpoint_unknown_tool_is_404` | `POST .../tools/nope/invoke` | HTTP 404; `error == "Unknown tool: nope"` and `detail == "Unknown tool: nope"`; `text` and `meta` null. |
| T-25 | `test_invoke_endpoint_tool_error_is_400` | Tool raises `ToolError("bad dice")` | HTTP 400; `error == "bad dice"`; `text` null. |
| T-26 | `test_invoke_endpoint_intelligence_error_is_502` | Tool raises `IntelligenceError("ollama down")` | HTTP 502; `error == "ollama down"`. |
| T-27 | `test_invoke_endpoint_other_exception_is_500` | Tool raises `RuntimeError("boom")` | HTTP 500; `error == "boom"`; an ERROR-level record with the traceback is logged. |
| T-28 | `test_invoke_endpoint_ignores_client_supplied_service_objects` | Tool records its ctx; `POST` with `{"args": "", "context": {"inference": "evil", "repos": "evil", "extra": 1}}` | HTTP 200; the tool saw `ctx["inference"] is services["inference"]`, `ctx["repos"]` is the real repos, `ctx["extra"] == 1`. |

New, wiring (WP-8):

| Id | Test | Exercises | Expected observable outcome |
|---|---|---|---|
| T-19 | `test_build_services_wires_tool_service_into_inference` | `build_services(repos, enable_tool_discovery=False)` | `services["inference"]._tool_service is services["tool"]`; `services["tool"].default_context["inference"] is services["inference"]`; `default_context["repos"] is repos`. (Existing `test_build_services_injects_inference_into_tool_context` still passes.) |

### 2.3 `tests/test_slash_dispatch.py` (new file; WP-6, WP-7, WP-8)
Fixture `slash_env` (defined in this file): `ts = ToolService(discover_on_init=True, default_context={"rng": ScriptedRng([3, 4])})`,
`svc = make_stub_service(tool_service=ts)`, `ts.default_context["inference"] = svc`, `svc.client.chat` patched to a stub that appends
its `messages` argument to a list `chat_calls` and returns `"stub reply"`, `store = SqliteSessionStore(":memory:")`,
`app = create_app(services={"inference": svc, "session": store, "tool": ts})`, a `TestClient`. Teardown: `asyncio.run(svc.shutdown())`, `store.close()`.

| Id | Test | Exercises | Expected observable outcome |
|---|---|---|---|
| T-32 | `test_rest_clear_is_unknown_tool_error_and_never_reaches_llm` (WP-7) | `POST /sessions/{sid}/messages {"content": "/clear"}` via REST with the `slash_env` fixture (discovery on, so the real registry is used); `wait_idle(svc)`; list messages | 202; the user message has `status == "error"` and `meta["error"] == "Unknown tool: clear"`; no assistant message exists (the list has exactly the one user message); `chat_calls == []` (the LLM is not called); no HTTP 404 is returned by the message route (404 applies only to `POST /api/v1/intel/tools/clear/invoke`, T-31). |
| T-33 | `test_rest_slash_roll_creates_tool_reply` (WP-7) | `POST /sessions/{sid}/messages {"content": "/roll 2d6"}`; `wait_idle(svc)`; list messages | 202; messages are `[user, assistant]`; user `status == "completed"`; assistant `status == "completed"`, `content == "2d6: [3, 4] = 7"`, `meta["tool"] == "roll"`, `meta["reply_to"] == <user id>`, `meta["total"] == 7`; `chat_calls == []`. |
| T-34 | `test_ws_slash_roll_creates_tool_reply` (WP-8) | WS `user_message` text `"/roll 2d6"` | Events: `entry` (user), `entry` (reply with `role == "assistant"`, `meta.tool == "roll"`, `meta.reply_to == user id`, `content == "2d6: [3, 4] = 7"`), then `{"type": "done", "message_id": <user id>, "reply_id": <reply id>}`; `chat_calls == []`. |
| T-35 | `test_rest_unknown_slash_command_marks_user_message_error` (WP-7) | `/nope hi` via REST; `wait_idle` | User message `status == "error"` with `meta["error"] == "Unknown tool: nope"`; no assistant message exists; `chat_calls == []`. |
| T-36 | `test_ws_unknown_slash_command_sends_error_event` (WP-8) | `/nope hi` via WS | After the user `entry`, an event `{"type": "error", "message": "Unknown tool: nope", "message_id": <user id>}`; no reply `entry`; `chat_calls == []`. |
| T-37 | `test_slash_tool_error_marks_user_message_error` (WP-7) | `/roll 1d1` via REST | User `status == "error"`, `meta["error"] == "Dice sides must be 2-1000"`; no reply; `chat_calls == []`. |
| T-38 | `test_slash_narrate_runs_in_worker_without_deadlock` (WP-7) | `/narrate a storm` via REST; `wait_idle(svc)` (fails if the worker hangs) | Reply content `"stub reply"`, `meta["tool"] == "narrate"`, `meta["reply_to"] == <user id>`; `chat_calls` has exactly one entry equal to `[{"role": "user", "content": build_narrator_prompt("a storm", <params from get_settings().prompts>, None)}]` (no system message, no history); user message `completed`. |
| T-39 | `test_non_slash_messages_use_chat_path` (WP-7) | Messages `"hello"`, `"/ roll 2d6"`, `"path/to/x"`, `"say /roll"` | Each goes through the chat path: `chat_calls` gets one entry per message whose last item is the user's text, and each gets a `"stub reply"` assistant reply with `meta == {"reply_to": <id>}`. |
| T-40 | `test_without_tool_service_slash_goes_to_chat` (WP-7) | `make_stub_service()` (no `tool_service`); `/roll 2d6` enqueued | Goes to chat; reply `"stub reply"`; existing behaviour unchanged. |
| T-41 | `test_worker_passes_server_context_to_tool` (WP-7) | Register `echo` that records ctx; enqueue `/echo x` for session `s1`, message `u1` | ctx has `store is <the job's store>`, `session_id == "s1"`, `message_id == "u1"`, plus `default_context` keys; reply text is the echo's return. |
| T-42 | `test_tool_bug_marks_error_and_worker_survives` (WP-7) | Tool raising `RuntimeError("boom")`; then a normal `"hello"` | First user message `status == "error"`, `meta["error"] == "boom"`, no reply; the second message still completes with `"stub reply"` (worker thread alive). |
| T-43 | `test_generate_holds_the_ollama_lock` (WP-6) | `svc.client.chat` stub records `svc._ollama_lock.locked()`; `svc.generate("p")` | Returns the chat stub's text; `locked()` was `True` during the call and `False` after; the stub received `[{"role": "user", "content": "p"}]`. |
| T-44 | `test_worker_chat_holds_the_ollama_lock` (WP-6) | Normal job through the worker with the same recording stub | `locked()` was `True` during the worker's `client.chat`; reply stored as before. |
| T-45 | `test_generate_calls_do_not_overlap` (WP-6) | Chat stub increments a shared counter, blocks until released, records max concurrency; two threads call `svc.generate` | Max concurrency observed is 1; both calls return after release. |

## 3. Work Packages
Order: WP-1 -> WP-2 -> WP-3 -> WP-4 -> WP-5 (need only G-1); WP-6 -> WP-7 -> WP-8 (**gated on G-2**); WP-9 last (needs only G-1; run it after WP-8, or after WP-5 if G-2 is pending).
Gate map: G-1 only = WP-1, WP-2, WP-3, WP-4, WP-5, WP-9. G-1 and G-2 = WP-6 (amendment ii, shared `_ollama_lock`), WP-7 (amendments i and ii: slash jobs skip the chat builder; relies on WP-6's lock), WP-8 (amendment i: composition and the WebSocket proof).
After each WP, run the three verification commands above; the whole suite must be green, not only the tests named.
No WP edits `.github/BACKLOG.json`, `docs/adr/`, `docs/patterns/` or touches git.

### WP-1: `ToolError`, `UnknownToolError`, and a strict `ToolService.invoke`
- **Gate:** G-1.
- **Files:** `app/intelligence/tools/__init__.py`, `app/services/tool_service.py`, `tests/test_tool_calling.py`.
- **Inputs:** `discover_tool_modules`, `TOOLS_PACKAGE` in `tools/__init__.py`; the current `ToolService` (RLock `self._lock`, `register_tool`, `unregister_tool`, `reload_tools`, `list_tools`, `_SimpleLogger`).
- **Change:**
  1. In `app/intelligence/tools/__init__.py` add `class ToolError(ValueError)` (docstring: raised by a tool for bad user input; its message is shown to the user), add `"ToolError"` to `__all__`, and update the module docstring so `run(args: str, context: dict)` returns `str | {"text": str, "meta": dict}`.
  2. In `app/services/tool_service.py` add `class UnknownToolError(LookupError)` and a module constant `SERVER_CONTEXT_KEYS = frozenset({"inference", "repos", "store", "session_id", "message_id", "logger", "rng"})`.
  3. Replace `invoke` with `invoke(self, name: str, args: str = "", context: dict | None = None, *, client_context: dict | None = None) -> dict` that:
     - takes `self._lock` ONLY to read `self._registry.get(name)` and to copy `self.default_context`; the tool is called after the lock is released;
     - if the tool is missing raises `UnknownToolError(f"Unknown tool: {name}")`;
     - builds the context in this order: (1) `client_context` keys, **excluding** any key in `SERVER_CONTEXT_KEYS` and any key in the default_context copy; (2) the default_context copy; (3) `context` (server-supplied, may contain protected keys). If any client keys were dropped, log ONE `logger.warning` listing the dropped key names only (never values);
     - if `"logger"` is not in the final context, sets it to `_SimpleLogger()` (as today);
     - calls `tool(args, ctx)`; **does not catch** exceptions (they propagate unchanged, no "Tool x error" text, no logging here);
     - normalizes the result: `str` -> `{"text": s, "meta": {}}`; `dict` whose `"text"` is a `str` -> `{"text": d["text"], "meta": dict(d.get("meta") or {})}`; anything else raises `TypeError(f"Tool {name} returned an unsupported result type")`.
  4. Remove the `timeout_seconds` parameter (assumption A-8: first search `app/` and `tests/` for callers passing it; if one exists, keep it as an accepted-and-ignored keyword-only argument instead and note that in the module docstring). Update the module docstring (contract, context rules, error behaviour). Keep `reload_tools`, `list_tools`, `register_tool`, `unregister_tool` behaviour unchanged. Use `get_logger(__name__)` only; no `logging.getLogger`, no `print`.
  5. In `tests/test_tool_calling.py` rewrite T-10..T-13 as specified in Test Spec 2.2 and add T-15..T-18. Leave the other five existing tests untouched. Add the imports you need (`threading`, `ToolError`, `UnknownToolError`, `pytest`, `tmp_path` fixtures).
- **Outputs:** `ToolError` importable from `app.intelligence.tools`; `UnknownToolError`, `SERVER_CONTEXT_KEYS`, and the new `invoke` in `app.services.tool_service`.
- **Tests that must pass:** T-10, T-11, T-12, T-13, T-15, T-16, T-17, T-18, plus the five unchanged tests in `tests/test_tool_calling.py` and the rest of the suite.
- **Acceptance criteria (restated in full):** `invoke` returns `{"text": str, "meta": dict}` for `str` and `{"text", "meta"?}` results and raises `TypeError` otherwise; an unregistered name raises `UnknownToolError("Unknown tool: <name>")`; tool exceptions (including `ToolError`, `ValueError`) propagate unchanged; the registry lock is held only while looking up the tool (a tool blocked on one thread does not stop `invoke` of another tool or `list_tools` on another thread); client-supplied context keys named in `SERVER_CONTEXT_KEYS` or present in `default_context` are ignored and their names (not values) are logged once at WARNING, while other client keys are passed through; server `context` and `default_context` always win over client keys; the full pytest suite, `ruff check app tests` and `black --check app tests` pass.
- **Patterns used/created:** PAT-ARCH-004 (proposed; points 1, 2, 5), PAT-CODE-001; ADR-0004 D3. Created: none.

### WP-2: HTTP error mapping in `invoke_tool`
- **Gate:** G-1; requires WP-1 done.
- **Files:** `app/api/v1/intelligence.py`, `tests/test_tool_calling.py`.
- **Inputs:** `ToolService.invoke(name, args, context=None, *, client_context=None)` from WP-1 raising `UnknownToolError` and propagating tool exceptions; `ToolError` in `app.intelligence.tools`; `IntelligenceError` in `app.intelligence.client`; `ToolInvokeReq(args: str, context: dict | None)` and `ToolInvokeResp(text, meta, error)` in `app/schemas/v1.py` (do NOT change these models or any other schema).
- **Change:** In `invoke_tool`, call `tool_service.invoke(tool_name, req.args, client_context=req.context or {})` (no server `context`). Remove the blanket `except Exception` that returned HTTP 200. Map:
  - success -> HTTP 200, `ToolInvokeResp(text=result["text"], meta=result["meta"], error=None)`;
  - `UnknownToolError` -> HTTP 404, body `{"text": None, "meta": None, "error": str(exc), "detail": str(exc)}`;
  - `ToolError` -> HTTP 400, body `{"text": None, "meta": None, "error": str(exc)}`;
  - `IntelligenceError` -> HTTP 502, same body shape;
  - any other `Exception` -> `logger.exception(...)` (use `get_logger(__name__)`; add the logger at module top) and HTTP 500, same body shape with `error=str(exc)`.
  Return error statuses via `fastapi.responses.JSONResponse(status_code=..., content=...)`. Keep the `response_model=ToolInvokeResp` on the route and the route path unchanged. Add T-23..T-28 to `tests/test_tool_calling.py`.
- **Outputs:** the endpoint answers 200/404/400/502/500 as above.
- **Tests that must pass:** T-23, T-24, T-25, T-26, T-27, T-28 and the existing `test_api_lists_and_invokes_registered_tool` (a tool returning `"echo:hi"` still gives HTTP 200, `text == "echo:hi"`).
- **Acceptance criteria (restated in full):** a successful invoke returns HTTP 200 with `error` null and the tool's `text`/`meta`; an unknown tool returns HTTP 404 with `error` and `detail` both `"Unknown tool: <name>"`; a `ToolError` returns HTTP 400 with `error` set to its message; an `IntelligenceError` returns 502 with `error` set; any other exception returns 500 with `error` set and an ERROR log entry; client `context` containing `inference`/`repos`/`store`/`session_id`/`message_id`/`logger`/`rng` or any `default_context` key never reaches the tool; response models and routes are unchanged; the full suite, `ruff check`, and `black --check` pass.
- **Patterns used/created:** PAT-ARCH-004 (point 5); ADR-0004 D3. Created: none.

### WP-3: `roll` tool (dice parser)
- **Gate:** G-1; requires WP-1 (for `ToolError`).
- **Files:** `app/intelligence/tools/roll.py` (replace the whole stub), `tests/test_roll.py` (new), `tests/test_tool_calling.py` (add T-14).
- **Inputs:** `from app.intelligence.tools import ToolError`; stdlib `re` and `random` only (no new dependency).
- **Change:** Rewrite `roll.py` with `NAME = "roll"`, a module-level `_DEFAULT_RNG = random.Random()`, a pure `evaluate(expr: str, rng) -> dict` and `run(args: str, context: dict) -> dict` that calls `evaluate(args, context.get("rng") or _DEFAULT_RNG)`. The only call made on `rng` is `rng.randint(1, sides)`. Delete `run_roll_tool`.
  Grammar (case-insensitive; whitespace allowed **between** tokens, not inside one):
  `expr := term (('+'|'-') term)*`; `term := dice | INT | 'adv' | 'dis'`; `dice := INT? 'd' INT (('kh'|'kl') INT)?`; `INT := [0-9]{1,4}`. `adv` means `2d20kh1`, `dis` means `2d20kl1`. Empty or blank args mean `1d20`. The first term has no sign (a leading `-` is invalid).
  Validation order: strip args; if longer than 64 characters raise `ToolError("Expression too long (max 64 characters)")` **before** any regex work; lowercase and parse; any syntax problem raises `ToolError("Invalid dice expression. Usage: /roll [NdM[kh|klK]][+/-...] (e.g. 2d6+3, adv)")`. Bounds (all `ToolError`, checked before any `randint` call): more than 10 terms -> `"At most 10 terms"`; dice count not 1..100 (default 1) -> `"Dice count must be 1-100"`; sides not 2..1000 -> `"Dice sides must be 2-1000"`; keep not `1 <= keep <= count` -> `"Keep must be between 1 and the dice count"`; constant not 0..1000 -> `"Constants must be 0-1000"`; total dice across all terms above 100 -> `"Total dice must be at most 100"`.
  Evaluation: roll each dice term's dice in order with `rng.randint(1, sides)`. For `kh` keep the `keep` highest values, for `kl` the lowest; on ties keep the earliest index; with no keep modifier all dice are kept. Term value = sum of kept dice (unsigned); total = sum of `sign * value`.
  Output `{"text": ..., "meta": ...}`. Text = `f"{normalized}: {parts} = {total}"` where `normalized` is the expression lowercased with all whitespace removed (`adv`/`dis` kept as typed), and `parts` is the terms joined: dice term -> `[r1, r2, ...]` in rolled order with dropped dice written `(r)`; constant -> its number; the first term as is, later terms preceded by ` + ` or ` - `. Example: `"4d6kh3+2: [6, 4, 3, (1)] + 2 = 15"`. Meta = `{"tool": "roll", "expression": normalized, "total": total, "terms": [...]}` where each dice term is `{"sign": "+"|"-", "count", "sides", "keep" (int or None), "rolls", "kept" (kept values in rolled order), "value"}` and each constant is `{"sign", "constant", "value"}`. (`adv` records `count=2, sides=20, keep=1`.) Use `get_logger(__name__)` only if logging is needed (it is not required).
  Create `tests/test_roll.py` with a local `ScriptedRng` class (`randint(self, a, b)` pops the next scripted value and asserts `a == 1`) and tests T-01..T-09. Add T-14 (`test_discovery_registers_roll_and_narrate`) to `tests/test_tool_calling.py`.
- **Outputs:** `roll` is discovered by `ToolService` (`list_tools()["roll"] == "app.intelligence.tools.roll"`).
- **Tests that must pass:** T-01..T-09 and T-14; all other tests stay green (the old `test_discovery_skips_non_contract_modules` was already rewritten in WP-1; if WP-1 is not yet applied, that old test fails because `roll` is now discovered; do WP-1 first).
- **Acceptance criteria (restated in full):** `roll.NAME == "roll"` and `run(args, context)` returns `{"text", "meta"}` as specified; `"2d6+3"`, `"d20"`, `"adv"`, `"dis"`, `"4d6kh3+2"`, `"4D6KL3 - 1d4"` all evaluate with an injected `rng` and are deterministic for a seeded `random.Random`; empty args equal `1d20`; every bound violation and malformed input raises `ToolError` with the exact messages above and never calls `rng.randint`; boundary values (`100d2`, `1d1000`, `1d20+1000`, 10 terms, a 64-character expression) are accepted; with no `rng` in context the module-level `random.Random()` is used; `ToolService(discover_on_init=True).list_tools()` contains `roll` and `narrate`; no new dependency; the full suite, `ruff check`, and `black --check` pass.
- **Patterns used/created:** PAT-ARCH-004 (points 1, 7). Created: none.

### WP-4: `narrate` tool
- **Gate:** G-1; requires WP-1 (`ToolError`, new `invoke` for T-22).
- **Files:** `app/intelligence/tools/narrate.py`, `tests/test_tool_calling.py`.
- **Inputs:** `build_narrator_prompt(adjudicator_output: str, params: NarratorVoiceParams, player_intent: str | None = None) -> str` and `NarratorVoiceParams(tone, dm_persona, verbosity, sensory_focus, consequence_level)` from `app.intelligence.prompt_builders`; `get_settings().prompts` from `app.config`; `context["inference"]` is an object with `generate(prompt: str) -> str`. (`OllamaInferenceService.generate` itself is added in WP-6; this WP is tested with a fake and does not need it.)
- **Change:** Rewrite `narrate.py`: `NAME = "narrate"`; `run(args: str, context: dict)`; `text = (args or "").strip()`; if empty raise `ToolError("Usage: /narrate <what happens>")`; `p = get_settings().prompts`; `params = NarratorVoiceParams(tone=p.dm_voice.tone, dm_persona=p.dm_voice.persona, verbosity=p.verbosity_default, sensory_focus=p.dm_voice.sensory_focus, consequence_level=p.dm_voice.consequence_level)`; `prompt = build_narrator_prompt(text, params, None)`; `reply = context["inference"].generate(prompt)`; return `{"text": reply, "meta": {"tool": NAME}}`. Do not put the prompt in `meta` and do not log it. Do not read `args` as a dict, and do not use `game`/`session_run` context keys. If `inference` is missing from context let the `KeyError` propagate (server misconfiguration). Do NOT read `settings.prompts.enable_narration` or `enable_adjudication` (open gate (a)). Imports go at module top (no lazy import needed). Add T-20..T-22 to `tests/test_tool_calling.py` using a fake inference class.
- **Outputs:** `narrate.run("<text>", {"inference": obj})` -> `{"text": <generate result>, "meta": {"tool": "narrate"}}`.
- **Tests that must pass:** T-20, T-21, T-22 and the existing `test_discovery_registers_narrate`.
- **Acceptance criteria (restated in full):** `narrate` keeps the `NAME: str` / `run(args: str, context: dict)` contract; empty or whitespace-only args raise `ToolError("Usage: /narrate <what happens>")` without calling inference; the prompt passed to `context["inference"].generate` is exactly `build_narrator_prompt(args.strip(), NarratorVoiceParams(<from settings.prompts>), None)` using the current three-parameter signature; the return value is `{"text": <generate result>, "meta": {"tool": "narrate"}}` with no prompt in meta; nothing reads `enable_narration`/`enable_adjudication`; the full suite, `ruff check`, and `black --check` pass.
- **Patterns used/created:** PAT-ARCH-004 (points 1, 4), PAT-ARCH-003 (builders unchanged). Created: none.

### WP-5: Delete `clear` (no port, no replacement)
- **Gate:** G-1; requires WP-2 done (T-31 needs the 404 mapping) and WP-3 done (T-30 asserts `roll`/`narrate` are still discovered). The fourth deletion test, T-32 (`/clear` through the worker), needs slash dispatch and therefore lands in WP-7 (G-2); it is part of this deletion's acceptance but is verified there.
- **Files:** `app/intelligence/tools/clear.py` (**delete the file**), `tests/test_tool_calling.py` (add T-29, T-30, T-31).
- **Inputs:** `app/intelligence/tools/` currently holds `__init__.py`, `clear.py`, `narrate.py`, `roll.py`; the `/invoke` 404 mapping from WP-2; `discover_tool_modules()` and `discover_tools()` in `app/intelligence/tools/__init__.py`.
- **Change:**
  1. Before deleting, search `app/` and `tests/` for any import of `app.intelligence.tools.clear` or the name `run_clear_tool` (assumption A-9). The stub is not discovered today, so none is expected. If one exists, STOP and report it; do not port or rewrite anything.
  2. Delete `app/intelligence/tools/clear.py` with plain file deletion (remove the file from the working tree; do not stage or commit, git is not touched). Do NOT create any replacement module, helper, constant, history marker, `meta.history_cleared` flag, or special case for the word `clear` anywhere (not in `ToolService`, the worker, `build_chat_messages`, `tool_handler.py`, or the routers). `/clear` is handled by the generic unknown-tool path from WP-1/WP-2 (and, once WP-7 exists, by the worker's generic error path).
  3. In `tests/test_tool_calling.py` add exactly these three tests (full definitions are in Test Spec 2.2): T-29 `test_clear_module_file_is_deleted` (`Path(app.intelligence.tools.__file__).parent / "clear.py"` does not exist and `importlib.util.find_spec("app.intelligence.tools.clear") is None`); T-30 `test_clear_is_not_registered` (`"clear"` is not a key in `ToolService(discover_on_init=True).list_tools()`, in `discover_tool_modules()`, or in `discover_tools()`); T-31 `test_invoke_endpoint_clear_is_unknown_tool_404` (`POST /api/v1/intel/tools/clear/invoke` with `{"args": ""}` returns HTTP 404 with `error == "Unknown tool: clear"` and `detail == "Unknown tool: clear"`, `text` and `meta` null; build the app as in `test_api_lists_and_invokes_registered_tool`).
- **Outputs:** `clear.py` no longer exists; `clear` is unknown everywhere.
- **Tests that must pass:** T-29, T-30, T-31, plus the whole existing suite. (T-32 is added and passes in WP-7.)
- **Acceptance criteria (restated in full):** `app/intelligence/tools/clear.py` does not exist; no replacement, marker, history-boundary logic or `clear`-specific code was added anywhere; `"clear"` is not a key in the `ToolService` registry (`list_tools()`) nor in `discover_tool_modules()`/`discover_tools()`; `POST /api/v1/intel/tools/clear/invoke` returns the existing unknown-tool HTTP 404 with `error`/`detail` equal to `"Unknown tool: clear"`; (verified in WP-7 by T-32) a `/clear` chat message makes the user message `error` with `meta.error == "Unknown tool: clear"`, writes no assistant reply and does not call the LLM; `build_chat_messages` is unchanged; the full suite, `ruff check app tests` and `black --check app tests` pass.
- **Patterns used/created:** PAT-ARCH-004 (consequences; ADR-0004 D4). Created: none.

### WP-6: `generate` and the shared `_ollama_lock`  (**GATED on G-2, amendment (ii)**)
- **Gate:** G-1 **and** G-2. Do not start until a human has accepted the PAT-ARCH-003 amendment "worker `chat` and the service's `generate` run under one `_ollama_lock`". Do not edit PAT-ARCH-003.
- **Files:** `app/services/inference_service.py`, `tests/test_slash_dispatch.py` (new file; add T-43..T-45 and the imports they need).
- **Inputs:** `OllamaInferenceService.__init__(self, settings)`, `self.client` (an `OllamaClient` with `chat(messages, *, model=None)` and `generate(prompt, *, model=None)`), the worker's `text = self.client.chat(messages)` call, `make_stub_service(**settings_kwargs)` in `tests/session_helpers.py`.
- **Change:**
  1. In `__init__` add `self._ollama_lock = threading.Lock()` (non-reentrant; exact attribute name).
  2. Add `def generate(self, prompt: str) -> str:` that does `with self._ollama_lock: return self.client.generate(prompt)`. Log with `get_logger` only counts/ids, never the prompt.
  3. In `_worker_loop` change only the chat call to `with self._ollama_lock: text = self.client.chat(messages)`. The lock MUST NOT be held anywhere else in the worker (WP-7 runs tools without it).
  4. Leave `generate_tokens` untouched (assumption A-7).
  5. Do NOT touch `tests/session_helpers.py` in this WP (WP-7 changes the helper together with the constructor argument it needs). T-43..T-45 use `make_stub_service()` with no argument.
  6. Create `tests/test_slash_dispatch.py` and add T-43, T-44, T-45 (these three need only `make_stub_service()`, a recording chat stub, `wait_idle`, `threading`). The `slash_env` fixture and the other tests in this file are added in WP-7 and WP-8.
- **Outputs:** `OllamaInferenceService.generate(prompt) -> str`; `_ollama_lock` serializes `generate` and the worker's `chat`.
- **Tests that must pass:** T-43, T-44, T-45, and all of `tests/test_inference_reply.py` unchanged.
- **Acceptance criteria (restated in full):** `OllamaInferenceService` has `_ollama_lock` (a `threading.Lock`) and `generate(prompt)` that calls `self.client.generate(prompt)` while holding it; the worker's `self.client.chat(messages)` runs while holding the same lock and the lock is not held during any other worker step; two concurrent `generate` calls never overlap; `generate_tokens` and every other public method are unchanged; existing inference-reply tests pass unchanged; the full suite, `ruff check`, and `black --check` pass.
- **Patterns used/created:** PAT-ARCH-004 (point 4), PAT-ARCH-003 (amendment gated); ADR-0004 D2. Created: none.

### WP-7: Slash dispatch in `_worker_loop`  (**GATED on G-2, amendments (i) and (ii)**)
- **Gate:** G-1 **and** G-2; requires WP-1, WP-2, WP-3, WP-4, WP-5, WP-6 done. Do not start until a human has accepted the PAT-ARCH-003 amendment "slash-command jobs skip the chat builder and run the tool" (and the lock amendment WP-6 depends on).
- **Files:** `app/services/inference_service.py`, `tests/session_helpers.py`, `tests/test_slash_dispatch.py` (add the `slash_env` fixture, `ScriptedRng`, and T-32, T-33, T-35, T-37, T-38, T-39, T-40, T-41, T-42).
- **Inputs:** `detect_tool(payload) -> (name | None, args | None)` from `app.intelligence.tool_handler` (name lowercased, args `""` when absent); `ToolService.invoke(name, args, context)` returning `{"text", "meta"}` and raising `UnknownToolError`/`ToolError`/others (WP-1); the existing worker `try/except` (the `except` already marks the user message `error` with `{"error": str(exc)}`); `_append_reply(self, store, session_id, user_message_id, text)`.
- **Change:**
  1. Constructor: `def __init__(self, settings, tool_service=None)`; store `self._tool_service = tool_service`. Import `detect_tool` at module top.
  2. `_append_reply(self, store, session_id, user_message_id, text, meta=None)`: the stored meta becomes `{**(meta or {}), "reply_to": user_message_id}`; with `meta=None` the stored meta is exactly `{"reply_to": user_message_id}` as before.
  3. In `_worker_loop`, inside the existing `try` right after the `"job.start"` log: compute `name, args = detect_tool(job.prompt) if self._tool_service is not None else (None, None)`. If `name` is not `None`: `result = self._tool_service.invoke(name, args or "", {"store": job.store, "session_id": job.session_id, "message_id": job.message_id})`, then `self._append_reply(job.store, job.session_id, job.message_id, result["text"], meta={**result["meta"], "tool": name})`, then fall through to the existing `completed` status update, ETA, and `job.completed` log. Do NOT call `build_chat_messages`/`client.chat` for slash jobs and do NOT hold `_ollama_lock` here. Otherwise run the existing chat path unchanged. Do not add any new `except`: a tool exception (including `UnknownToolError` and `ToolError`) takes the existing `except` path (user message `error` with `meta.error = str(exc)`, no reply written). Do not log prompt/args text (log ids and the tool name only). No new role, no new status.
  4. `tests/session_helpers.py`: `make_stub_service(tool_service=None, **settings_kwargs)` and `return OllamaInferenceService(settings, tool_service=tool_service)`.
  5. In `tests/test_slash_dispatch.py` add the `slash_env` fixture described in Test Spec 2.3, `ScriptedRng`, and the listed tests. T-32 sends `/clear` through the real discovered registry (no `clear` module exists after WP-5) and asserts the generic unknown-tool outcome; add no special handling of `clear` in the worker. Do NOT modify `app/api/v1/*.py` or `app/services/messages.py`.
- **Outputs:** `/name args` messages are executed by the worker for REST and WS (WS verified in WP-8); results are `role='assistant'` replies with `meta.tool` and `meta.reply_to`; an unknown `/x` (including `/clear`) is an error with no reply and no LLM call.
- **Tests that must pass:** T-32, T-33, T-35, T-37, T-38, T-39, T-40, T-41, T-42, T-43, T-44, T-45, and every pre-existing test (especially `tests/test_inference_reply.py`, `tests/test_session_rest.py`, `tests/test_ws_session.py`).
- **Acceptance criteria (restated in full):** with a `tool_service` wired, a message whose stripped content matches `/name args` runs that tool in the worker and **never** calls `client.chat`; on success exactly one new `role='assistant'` `completed` message is stored with `meta == {**tool_meta, "reply_to": <user id>, "tool": <name>}` and the user message becomes `completed`; on `UnknownToolError`, `ToolError` or any other tool exception the user message becomes `error` with `meta.error` set to the message (`"Unknown tool: nope"` for an unknown tool, `"Unknown tool: clear"` for `/clear`), no reply is written, the LLM is not called, and the worker keeps processing later jobs; the tool context contains the server-set `store`, `session_id`, `message_id` plus the tool service's `default_context`; messages that do not match (`hello`, `/ roll 2d6`, `path/to/x`, `say /roll`) and every message when `tool_service is None` use the unchanged chat path with reply meta `{"reply_to": id}`; `build_chat_messages` and `app/intelligence/prompt_builders.py` are not edited; REST, WS and `messages.py` are not edited; the full suite, `ruff check`, and `black --check` pass.
- **Patterns used/created:** PAT-ARCH-004 (points 3, 6), PAT-ARCH-001 (single reply writer), PAT-ARCH-003 (amendments gated); ADR-0004 D1, D4. Created: none.

### WP-8: Compose services and prove the WebSocket path  (**GATED on G-2, amendment (i)**)
- **Gate:** G-1 **and** G-2; requires WP-7 done.
- **Files:** `app/services/build_services.py`, `tests/test_tool_calling.py` (add T-19), `tests/test_slash_dispatch.py` (add T-34, T-36).
- **Inputs:** `OllamaInferenceService(settings, tool_service=None)` from WP-7; `ToolService(default_context=..., discover_on_init=...)`; current `build_services` creates the inference service first and passes it into `ToolService.default_context`.
- **Change:** In `build_services` create `tool_service = ToolService(default_context={"repos": repos}, discover_on_init=enable_tool_discovery)` first; then `inference = OllamaInferenceService(settings, tool_service=tool_service)`; then `tool_service.default_context["inference"] = inference`; return the same dict keys `{"session", "tool", "inference"}`. Add T-19 to `tests/test_tool_calling.py`. Add T-34 and T-36 to `tests/test_slash_dispatch.py` (WS frames as described in Test Spec 2.3 / Verified facts). No edits to `app/api/v1/ws.py`.
- **Outputs:** the production service graph dispatches slash commands; the WS path is verified.
- **Tests that must pass:** T-19, T-34, T-36, the existing `test_build_services_injects_inference_into_tool_context` and `test_api_lists_and_invokes_registered_tool`, and the whole suite.
- **Acceptance criteria (restated in full):** `build_services(...)["inference"]._tool_service is build_services(...)["tool"]` (same object within one call); `services["tool"].default_context["inference"] is services["inference"]` and `default_context["repos"] is repos`; the returned dict keys are unchanged; a WS `user_message` of `/roll 2d6` yields `entry` (user), `entry` (assistant reply with `meta.tool == "roll"` and `meta.reply_to == <user id>`), then `done`; a WS `/nope` yields an `error` event `"Unknown tool: nope"` carrying the user's `message_id`; no WS or REST route file is edited; the full suite, `ruff check`, and `black --check` pass.
- **Patterns used/created:** PAT-ARCH-004 (point 3), PAT-ARCH-001 (transports stay thin). Created: none.

### WP-9: Update tool docs (`.github/instructions/tools.instructions.md` and the tools line of `.github/copilot-instructions.md`)
- **Gate:** G-1; do this after WP-8 (or after WP-5 if G-2 is still pending, writing only the facts already true and keeping the dispatch bullet marked "pending G-2").
- **Files:** `.github/instructions/tools.instructions.md` (keep the front matter `description`/`applyTo` lines), `.github/copilot-instructions.md` (only the `app/intelligence/tools/` bullet in the Architecture list and, once WP-3 is done, the "`roll.py` is a stub" bullet under "Known gaps / traps").
- **Inputs:** the final behaviour from WP-1..WP-8. Note: this revision of the spec already made two small doc edits ahead of the code (removed `clear.py` from the tools list in `.github/copilot-instructions.md`, and replaced the "`roll.py` is a stub" line in `tools.instructions.md` with a "roll/narrate implemented under REQ-0008; `clear` deleted, `/clear` is an unknown tool" statement). WP-9 makes the final text correct; do not revert those edits.
- **Change:** Replace the body of `tools.instructions.md` with bullets that state, in this order: (1) a tool is a module in `app/intelligence/tools/` exposing `NAME: str` and `run(args: str, context: dict)` returning `str` or `{"text": str, "meta": dict}`; discovery requires both; (2) raise `app.intelligence.tools.ToolError` for bad user input (its message is shown to the user: HTTP 400 / user message `error`); any other exception is a bug (HTTP 500); tools never write messages or touch the store; (3) discovery goes only through `discover_tool_modules` (ADR-0001), no second registry; (4) context: server-owned keys `inference, repos, store, session_id, message_id, logger, rng` cannot be overridden by clients; `session_id`/`message_id`/`store` are set only by the worker; use `context["inference"].generate(prompt)` for LLM calls and `context.get("rng")` for randomness; (5) slash commands `/name args` are dispatched by the inference worker (`detect_tool`) and the result is stored as an assistant reply with `meta.tool`/`meta.reply_to`; an unknown `/x` is an error and is not sent to the LLM; `clear` is deleted (REQ-0008, human decision 2026-10-11), there is no clear tool or replacement, and `/clear` is an unknown tool (chat: user message `error`; `POST /api/v1/intel/tools/clear/invoke`: HTTP 404); (6) `ToolService.invoke` raises `UnknownToolError` / propagates tool errors and does not hold its lock while a tool runs; (7) log with `get_logger(__name__)`, never log prompts; (8) tests must not need network or Ollama (see `tests/test_tool_calling.py`, `tests/test_roll.py`, `tests/test_slash_dispatch.py`). Keep no line saying `roll.py` is a stub or that `narrate.py`'s body is out of scope. Do not mention `enable_narration`/`enable_adjudication` except as "not read; open gate". In `.github/copilot-instructions.md`: the tools bullet lists only `roll.py` and `narrate.py` (no `clear.py`), and, after WP-3 is done, delete the "`app/intelligence/tools/roll.py` is a stub" bullet under "Known gaps / traps". Change nothing else in that file.
- **Outputs:** the instruction files match the shipped contract.
- **Tests that must pass:** none new; the full suite still passes.
- **Acceptance criteria (restated in full):** `tools.instructions.md` keeps its `description` and `applyTo: "app/intelligence/tools/**"` front matter; it contains the eight statements above, says `clear` is deleted and `/clear` is an unknown tool, and no longer says `roll.py` is a stub; `.github/copilot-instructions.md` does not list `clear.py` as a tool module and (after WP-3) no longer calls `roll.py` a stub, with no other change to it; every statement is true of the code at that point; the full suite, `ruff check`, and `black --check` pass.
- **Patterns used/created:** PAT-ARCH-004. Created: none.

### Final verification (after the last WP that was executed)
Run the three verification commands. If G-2 is still pending, WP-6..WP-8 are not executed, so T-19, T-32..T-45 (the slash-dispatch, WebSocket and lock tests, including the `/clear` worker test T-32) will not exist yet; that is a partial delivery. The spec is complete only when all 45 tests exist and pass.

## 4. Other Details
- **Risks:**
  - *Tools queue behind LLM jobs:* `/roll` waits behind queued narration (accepted by ADR-0004). A direct `/invoke` narrate plus a queued job can push a WS reply past `ollama.timeout_seconds + 10`; the `_ollama_lock` is not FIFO.
  - *Deadlock:* `_ollama_lock` is non-reentrant. If the worker held it while running a tool, `narrate` would deadlock; WP-6 limits the lock to the worker's `chat` call and T-38 guards it.
  - *`generate_tokens` unlocked* (A-7) can overlap with the worker until REQ-0007.
  - *Unknown `/x` is an error* (gate (b)): a user who types a leading slash in ordinary chat gets an error. That now includes `/clear`, which a user who remembers the old debug shorthand may still type; they see `Unknown tool: clear`.
  - *Tool chatter in LLM history* (gate (c)): `/roll` exchanges consume `max_turns` slots.
  - *Meta must be JSON-serializable* (stored as JSON TEXT in SQLite): tools MUST return plain dict/list/str/int/None in `meta`.
  - *Partial delivery:* with G-2 pending, WP-1..WP-5 and WP-9 give working `roll`/`narrate` modules, a strict `/invoke`, and the `clear` deletion, but `/narrate` over `/invoke` fails (500) until WP-6 adds `OllamaInferenceService.generate`, and slash commands in chat do nothing until WP-7/WP-8 (`/clear` typed in chat is then still sent to the LLM as ordinary text, as it is today, because no dispatch exists yet).
  - *Tests that read `get_settings()`* depend on the repo's `settings.json`/defaults; T-21 and T-38 build expectations from `get_settings().prompts` so they follow the same source as the code.
  - *Previously stored data:* the earlier `clear` stub never produced a stored marker (it was never discovered or dispatched), so no stored message needs migration.
- **Rollback plan:** Work packages are independent commits. WP-7 is reverted by deleting the dispatch branch and the `tool_service` constructor arg (the chat path is unchanged). WP-6 by removing `generate` and the `with` around `chat`. WP-5 is reverted by restoring `clear.py` from git history (the old stub was not functional, so there is nothing to preserve). WP-1/WP-2 by restoring the old `invoke` and endpoint. No schema, Protocol, role or status changed, so no data migration is needed. Tool replies already stored remain ordinary `assistant` messages with an extra `meta.tool`.
- **Patterns applied/created:**
  - Applied: PAT-ARCH-004 (accepted), PAT-ARCH-003 (accepted; two amendments approved and applied 2026-10-11), PAT-ARCH-001 (accepted), PAT-ARCH-002 (accepted; tests use `:memory:`), PAT-CODE-001 (accepted), ADR-0001 tool contract; ADR-0004 D1..D4 (**proposed**).
  - Created by this spec: none. The patterns index lists no `spec`-category patterns, so none were applicable; `docs/patterns/INDEX.md` is not edited.
  - No ADR or pattern is marked accepted by this spec.
- **Non-goals:**
  - Streaming (REQ-0007), auth/CORS (REQ-0009), API schema and response models (REQ-0010), campaign domain (REQ-0015), repo hygiene (REQ-0012).
  - The two-step narrate/adjudicate flow and any read of `settings.prompts.enable_narration` / `enable_adjudication` (gate (a)).
  - Any replacement for `clear`: no new tool, no REST clear endpoint, no clear marker, no history-boundary logic, no change to `build_chat_messages`, no data deletion, no `SessionStore` Protocol method, SQLite schema change, or new message role or status (ADR-0004 D4).
  - Passing unknown `/x` to the LLM (gate (b)); hiding tool exchanges from LLM history (gate (c)).
  - Removing the dead `tool_handler.get_registry` / `run_tool` (ADR-0001 follow-up).
  - Locking `generate_tokens`; strict FIFO between `/intel/tools/*/invoke` and worker jobs.
  - Editing ADR-0004, PAT-ARCH-004, PAT-ARCH-003, `.github/BACKLOG.json`, or git state.
