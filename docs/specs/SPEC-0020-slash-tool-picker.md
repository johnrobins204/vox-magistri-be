---
id: SPEC-0020
requirement: REQ-0034
adr: ADR-0014
status: draft
date: 2026-11-08
---

# Slash tool picker in the chat composer

## 1. Requirement
REQ-0034; restatement in [`docs/requirements/LOG.md`](../requirements/LOG.md) (row REQ-0034).
ADR: [ADR-0014](../adr/0014-slash-tool-picker.md) (status **proposed**, not human-confirmed).
- **CONFIRMED (ADR-0014):** selecting a tool inserts `/name ` into the draft (D1-A). That one behaviour lives in a single function, `applyToolSelection` (WP-4), so it can change without touching the rest.
- No new endpoint: extend `GET /api/v1/intel/tools` with an additive `description` string (`""` when a tool has none). `ToolService.list_tools()` stays byte-for-byte unchanged (20+ tests use it).
- Descriptions come from a one-line `DESCRIPTION` constant in each of the five tool modules. A new test (not `test_patterns.py`) fails if one is missing; the API never fails, it returns `""`.
- The PAT-ARCH-004 amendment (`DESCRIPTION` becomes part of the tool contract) is **PROPOSED, not accepted**. It is isolated in gated WP-7 and MUST NOT be applied without human sign-off.
- Frontend has no test runner and adding one is out of scope (new dependency). Frontend packages are verified by `npm run build` (tsc) plus a manual checklist. Pure logic is kept in `frontend/src/lib/slash.ts` so a runner can be added later.

## 2. Test Spec
Backend tests are pytest, run with `./venv-dnd-server/bin/python -m pytest -q` from the repo root.
New backend tests live in `tests/test_tool_descriptions.py` (one file, so each WP appends to it).
Frontend checks: from `frontend/`, `npm run build` MUST pass, then the manual checklist with the backend running
(`http://127.0.0.1:5000`, token `dev`) and `npm run dev`. Manual rows are marked "manual" and name the file under test.
Existing tests (notably `tests/test_tool_calling.py`, `tests/test_roll.py`, `tests/test_patterns.py`) MUST keep passing in every WP.

### WP-1
| Id | Exercises | Expected outcome | File |
|---|---|---|---|
| T-1 | `test_every_tool_module_has_description`: loop `discover_tool_modules()` from `app.intelligence.tools` | each module has `DESCRIPTION`, a `str`, non-empty after strip, one line (no `\n`), at most 100 characters; failure message names the module | `tests/test_tool_descriptions.py` |
| T-2 | `test_descriptions_are_user_text`: same loop | no description contains `REQ-`, `SPEC-` or `ADR-` | `tests/test_tool_descriptions.py` |
| T-3 | `test_five_known_tools_discovered`: same loop | discovered names are a superset of `{"narrate","rules","monster","attack","roll"}` (guards the loop from passing vacuously) | `tests/test_tool_descriptions.py` |

### WP-2
| Id | Exercises | Expected outcome | File |
|---|---|---|---|
| T-4 | `test_list_tool_descriptions_matches_list_tools`: `ToolService(discover_on_init=True)` | `list_tool_descriptions()` keys equal `list_tools()` keys; every value is a non-empty `str` for the five built-in tools | `tests/test_tool_descriptions.py` |
| T-5 | `test_manually_registered_tool_has_empty_description`: `register_tool("echo", fn)` with no module | `list_tool_descriptions()["echo"] == ""` | `tests/test_tool_descriptions.py` |
| T-6 | `test_non_string_description_becomes_empty`: `register_tool("odd", fn, module=<types.ModuleType with DESCRIPTION = 5>)` | `list_tool_descriptions()["odd"] == ""` | `tests/test_tool_descriptions.py` |
| T-7 | `test_list_tools_unchanged`: same service | `list_tools()` still returns `dict[str, str]` of name -> module `__name__` (e.g. `list_tools()["roll"] == "app.intelligence.tools.roll"`) | `tests/test_tool_descriptions.py` |

### WP-3
| Id | Exercises | Expected outcome | File |
|---|---|---|---|
| T-8 | `test_api_tools_include_description`: `build_services(make_default_repos(), enable_tool_discovery=True)`, `create_app(services=...)`, `TestClient(app).get("/api/v1/intel/tools")` | 200; for each of the five tools the item has `name`, `module` and a non-empty `description` | `tests/test_tool_descriptions.py` |
| T-9 | `test_api_tool_without_description_is_empty_string`: register `echo` (no module) via `services["tool"].register_tool`, then GET | the `echo` item has `"description": ""` and the response is still 200 | `tests/test_tool_descriptions.py` |
| T-10 | `test_openapi_tool_info_has_optional_description`: `GET /openapi.json` | `components.schemas.ToolInfo.properties` has `description` and `"description"` is not in `required` | `tests/test_tool_descriptions.py` |
| T-11 | `test_tool_list_resp_uses_v2_config`: import `ToolListResp` | `"json_schema_extra"` is in `ToolListResp.model_config`; the class body has no `Config` attribute | `tests/test_tool_descriptions.py` |

### WP-4
No test runner. Verified by the checks below.
| Id | Exercises | Expected outcome | File |
|---|---|---|---|
| T-12 | `npm run build` in `frontend/` | passes with no TypeScript errors | `frontend/src/lib/slash.ts`, `api.ts`, `types.ts` |
| T-13 | manual: DevTools console, call `getTools()` through a temporary `console.log` that is removed afterwards | resolves to an array of `{name, module, description}` with 5 items | `frontend/src/lib/api.ts` |
| T-14 | read the code: `slash.ts` | `slashQuery("/ro") === "ro"`, `slashQuery("/") === ""`, `slashQuery("hi /ro") === null`, `slashQuery("/roll 2d6") === null`, `slashQuery("") === null`; `filterTools` is case-insensitive prefix match, empty query returns all | `frontend/src/lib/slash.ts` |

### WP-5
| Id | Exercises | Expected outcome | File |
|---|---|---|---|
| T-15 | `npm run build` | passes | `frontend/src/components/SlashPicker.tsx` |
| T-16 | manual: temporarily render `<SlashPicker>` with two fake tools in `Composer` and revert | list shows name and description per row; active row visibly highlighted; clicking a row calls `onSelect` | `frontend/src/components/SlashPicker.tsx`, `frontend/src/index.css` |

### WP-6
| Id | Exercises | Expected outcome | File |
|---|---|---|---|
| T-17 | manual: type `/` | popup lists all five tools with descriptions, fetched from the backend (Network tab shows one `GET /api/v1/intel/tools`) | `frontend/src/components/Composer.tsx` |
| T-18 | manual: type `hello`, then `a /`, then empty | popup never shown | same |
| T-19 | manual: type `/ro` | only tools whose name starts with `ro` (`roll`, `rules`); `/zzz` shows no popup | same |
| T-20 | manual: ArrowDown / ArrowUp | active row moves and wraps; page does not scroll | same |
| T-21 | manual: Enter with popup open | selects the active tool (see WP-4 `applyToolSelection`; CONFIRMED: draft becomes `/name `), does NOT send; popup closes | same |
| T-22 | manual: click a row | same result as T-21; textarea keeps focus | same |
| T-23 | manual: Escape | popup closes and stays closed until the draft text changes; draft unchanged | same |
| T-24 | manual: Enter with popup closed | message is sent exactly as before (regression) | same |
| T-25 | manual: stop the backend, reload, type `/` | no popup, no crash, composer still works; restart backend, type `/` again, popup appears | same |
| T-26 | `npm run build` | passes | same |

### WP-7
| Id | Exercises | Expected outcome | File |
|---|---|---|---|
| T-27 | `test_pat_arch_004_tool_modules_follow_the_contract` | required names are `{"NAME", "DESCRIPTION", "run"}`, message `"tool needs NAME, DESCRIPTION and run()"`; passes for all five tools | `tests/test_patterns.py` |

## 3. Work Packages
Order: WP-1, WP-2, WP-3 (backend, sequential); WP-4, WP-5, WP-6 (frontend, sequential; WP-4 may start once the response shape in WP-3 is known); WP-7 only after human acceptance.

### WP-1: DESCRIPTION constants on the five tools
- **Files:** `app/intelligence/tools/narrate.py`, `rules.py`, `monster.py`, `attack.py`, `roll.py` (same folder); `tests/test_tool_descriptions.py` (new).
- **Inputs:** each module already defines `NAME = "<tool>"` at top level; discovery is `discover_tool_modules()` in `app/intelligence/tools/__init__.py`. Depends on no other package.
- **Outputs:** directly under each `NAME = ...` line add `DESCRIPTION = "<one plain-language line>"`. Suggested text (adjust to match the tool's `_USAGE`): narrate "Describe what happens next in the story."; rules "Look up a rule from the rules reference."; monster "Look up a monster's stat block."; attack "Make an attack with a weapon."; roll "Roll dice, e.g. 2d6+3 (a bare /roll rolls 1d20)." Do not change any other line.
- **Acceptance criteria:** T-1..T-3 pass; each description is a plain string literal (no f-string, no imports); `run()` behaviour is untouched and the full existing suite still passes.
- **Patterns used/created:** PAT-ARCH-004 (tool contract: not amended here); none created.

### WP-2: `ToolService.list_tool_descriptions()`
- **Files:** `app/services/tool_service.py`; `tests/test_tool_descriptions.py` (append).
- **Inputs:** `ToolService` keeps `self._registry` (name -> callable) and `self._modules` (name -> module) under `self._lock`; `list_tools()` at ~line 87 returns `{name: module __name__}`. Tool modules now define `DESCRIPTION` (WP-1; tests T-4 need it).
- **Outputs:** a new method placed directly after `list_tools()`: `def list_tool_descriptions(self) -> dict[str, str]` returning, for every name in `self._registry`, `DESCRIPTION` of its module (from `self._modules.get(name)`) stripped, or `""` when there is no module, no attribute, or the value is not a `str`. Hold `self._lock` while reading. Add one line to the module docstring contract: `DESCRIPTION: str (optional, one line, shown in the client tool picker)`.
- **Acceptance criteria:** T-4..T-7 pass. `list_tools()` is not edited at all. The method never raises for odd modules.
- **Patterns used/created:** PAT-ARCH-004 (tool registry stays in `ToolService`); none created.

### WP-3: Return `description` from `GET /api/v1/intel/tools`
- **Files:** `app/schemas/v1.py` (classes `ToolInfo`, `ToolListResp`, ~lines 174-196); `app/api/v1/intelligence.py` (`list_tools` route, ~line 40); `docs/api/openapi.json` (ONLY if the file exists: it does not at spec time, so then do nothing and do not create it); `tests/test_tool_descriptions.py` (append).
- **Inputs:** `ToolService.list_tool_descriptions()` from WP-2; `ConfigDict` is already imported in `app/schemas/v1.py`. Route currently builds `[{"name": n, "module": m} ...]` from `tool_service.list_tools()`.
- **Outputs:** (1) `ToolInfo` gains `description: str = Field("", description="One-line, user-facing summary of the tool")` (optional in the schema, default empty string). (2) The route also calls `tool_service.list_tool_descriptions()` once and adds `"description": descriptions.get(name, "")` to each item; envelope `{"tools": [...]}` and path unchanged. (3) In `ToolListResp` replace `class Config: schema_extra = {...}` with `model_config = ConfigDict(json_schema_extra={...})` (same example, add a `description` to each example tool). Pydantic v2 idiom only.
- **Acceptance criteria:** T-8..T-11 pass; existing `test_api_lists_and_invokes_registered_tool` still passes; response keeps `name` and `module`; `/invoke` route untouched (its non-PAT-ARCH-005 error body is a known, out-of-scope deviation).
- **Patterns used/created:** PAT-ARCH-005 (envelope, explicit model, pydantic v2 `model_config`); none created.

### WP-4: Frontend types, `getTools()` and pure slash helpers
- **Files:** `frontend/src/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/lib/slash.ts` (new).
- **Inputs:** backend returns `GET {getApiBaseUrl()}/api/v1/intel/tools` -> `{"tools": [{"name": string, "module": string|null, "description": string}]}` (no auth needed, as for `getIntelStatus`; if it answers 401/403 use `authHeaders()`). `api.ts` has `parseJson<T>(response)` and the pattern `getWeapons()` (fetch, parse envelope, return array). `types.ts` has `WeaponListResp`-style envelope types.
- **Outputs:** in `types.ts`: `export interface ToolInfo { name: string; module: string | null; description: string }` and `export interface ToolListResp { tools: ToolInfo[] }`. In `api.ts`: `export async function getTools(): Promise<ToolInfo[]>` modelled on `getWeapons()`. In `slash.ts`, no React imports: `slashQuery(draft: string): string | null` (returns text after the leading `/` when the draft starts with `/` and contains no whitespace, else `null`); `filterTools(tools: ToolInfo[], query: string): ToolInfo[]` (case-insensitive name-prefix match; empty query returns all; keeps backend order); and, **CONFIRMED (ADR-0014)**, `applyToolSelection(tool: ToolInfo, draft: string): string` returning `` `/${tool.name} ` ``. Put a comment above it: `// ADR-0014 (accepted): selecting a tool inserts "/name ". Change only here.` No tool name appears anywhere in frontend code.
- **Acceptance criteria:** T-12..T-14. `grep -rn "narrate\|monster" frontend/src` finds no new hits.
- **Patterns used/created:** none.

### WP-5: `SlashPicker` presentational component
- **Files:** `frontend/src/components/SlashPicker.tsx` (new), `frontend/src/index.css` (append a `/* ---------- Slash picker ---------- */` block after the Composer block, ~line 765).
- **Inputs:** `ToolInfo` type from `../types` (WP-4). CSS variables in use: `--brass`, `--ink`, `--faint`, `--border`, `--mono`; `.composer` is `display: grid` and the textarea is `width: 100%`.
- **Outputs:** `export function SlashPicker({ tools, activeIndex, onSelect, onHover }: { tools: ToolInfo[]; activeIndex: number; onSelect: (tool: ToolInfo) => void; onHover: (index: number) => void })`. Renders `<ul role="listbox" id="slash-picker" className="slash-picker">` with one `<li role="option" aria-selected={i === activeIndex} className={...active}>` per tool showing `/{name}` and the description. Row handlers: `onMouseDown={(e) => { e.preventDefault(); onSelect(tool) }}` (keeps textarea focus) and `onMouseEnter={() => onHover(i)}`. No state, no fetching, no key handling. CSS: dark panel matching `.panel`, `max-height` about 12rem with `overflow-y: auto`, active row uses a brass border or tint, name in `--mono`, description in `--faint`. Position in normal flow (not absolute) so it cannot be clipped.
- **Acceptance criteria:** T-15, T-16. The component imports nothing but `react` types and `../types`.
- **Patterns used/created:** none.

### WP-6: Wire the picker into `Composer`
- **Files:** `frontend/src/components/Composer.tsx` only.
- **Inputs:** `Composer` props `{draft, onDraftChange, onSubmit, canSend}`; a controlled `<textarea id="prompt">` whose `onKeyDown` submits on Enter without Shift. From earlier packages: `getTools` (`../lib/api`), `slashQuery`, `filterTools`, `applyToolSelection` (`../lib/slash`), `ToolInfo` (`../types`), `SlashPicker` (`./SlashPicker`, props `tools, activeIndex, onSelect, onHover`, also uses id `slash-picker`). Do not change `Composer`'s props or `App.tsx`.
- **Outputs:** state `tools: ToolInfo[] | null`, `activeIndex: number`, `dismissedFor: string | null`. Fetch: when `slashQuery(draft) !== null` and `tools === null`, call `getTools()` once (useEffect); on error leave `tools` null (so the next `/` retries) and show nothing. Derived: `matches = tools ? filterTools(tools, query) : []`; `open = query !== null && matches.length > 0 && dismissedFor !== draft`. Render `<SlashPicker>` above the textarea only when `open`; add `aria-controls="slash-picker"` and `aria-expanded={open}` to the textarea. Reset `activeIndex` to 0 whenever `query` changes. `handleKeyDown`: when `open`: ArrowDown/ArrowUp move `activeIndex` with wrap and `preventDefault`; Enter without Shift calls `select(matches[activeIndex])` and `preventDefault` WITHOUT calling `onSubmit`; Escape sets `dismissedFor = draft` and `preventDefault`. When not `open`, the existing Enter-to-submit logic runs unchanged. `select(tool)` calls `onDraftChange(applyToolSelection(tool, draft))` (CONFIRMED, ADR-0014: this is the only place the selection effect is used) and is also the `onSelect` prop of the picker.
- **Acceptance criteria:** T-17..T-26 (this package's Test Spec). Popup never shown unless the draft begins with `/` and has no whitespace yet.
- **Patterns used/created:** none.

### WP-7: (GATED) Accept `DESCRIPTION` into the PAT-ARCH-004 tool contract
- **GATE:** do NOT start until a human has accepted the amendment proposed in ADR-0014 "Pattern Impact" (ADR status changed by the human). Absent that sign-off, skip this package; WP-1..WP-6 are complete without it.
- **Files:** `docs/patterns/architecture/PAT-ARCH-004-slash-tools-in-worker.md` (rule 1); `docs/patterns/INDEX.md` (PAT-ARCH-004 row and the "Mechanically enforced" row `PAT-ARCH-004 / tool contract`); `tests/test_patterns.py` (`test_pat_arch_004_tool_modules_follow_the_contract`, ~line 132).
- **Inputs:** the human-approved wording (ADR-0014): "A module also exposes `DESCRIPTION: str`, one plain-language line shown in the client tool picker. `GET /api/v1/intel/tools` returns it as `description`." The WP-1 test file stays as it is.
- **Outputs:** the sentence added to rule 1 of the pattern; INDEX rows say tools are `NAME` + `DESCRIPTION` + `run`; the test requires `{"NAME", "DESCRIPTION", "run"}` with message `"tool needs NAME, DESCRIPTION and run()"`. Do not change the pattern's `status` or any other rule.
- **Acceptance criteria:** T-27 and the full `tests/test_patterns.py` pass. Marking the ADR or pattern accepted is the human's step, not this package's.
- **Patterns used/created:** amends PAT-ARCH-004 (accepted pattern, human sign-off required).

## 4. Other Details (at most ten lines)
- **Risks:** D1-A is unconfirmed (only `/roll` works without args; the rest reply with a Usage error); `docs/api/openapi.json` and its drift test do not exist, so WP-3 skips regeneration; no frontend test runner, so WP-4..6 rely on the manual checklist.
- **Rollback plan:** revert the commit. `description` is additive and `list_tools()` is untouched; the frontend change is three files plus one component; to change the selection effect edit only `applyToolSelection` (and `select` in `Composer`).
- **Patterns applied/created:** PAT-ARCH-004 (accepted; amendment proposed in WP-7, gated), PAT-ARCH-005 (accepted); none created.
- **Non-goals:** invoking tools from the popup (`/invoke`), new endpoint, argument hints, popup on non-leading `/`, fuzzy search, i18n, a frontend test runner, fixing the `/invoke` error body.
