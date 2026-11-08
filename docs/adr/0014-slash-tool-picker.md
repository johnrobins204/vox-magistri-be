---
id: ADR-0014
status: accepted
date: 2026-11-08
requirement: REQ-0034
supersedes: null
superseded_by: null
---

# Slash tool picker: selecting a tool inserts `/name ` into the composer; descriptions come from a per-tool `DESCRIPTION` constant on the existing `GET /api/v1/intel/tools`

## Context
REQ-0034 (`docs/requirements/LOG.md`). Patterns opened: PAT-ARCH-004, PAT-ARCH-005; others from the INDEX.

| Fact | Where |
|---|---|
| A listing endpoint exists: `GET /api/v1/intel/tools` returns `{"tools": [{name, module}]}`, no description | `app/api/v1/intelligence.py` `list_tools`; `app/schemas/v1.py` `ToolInfo` |
| `ToolService.list_tools()` returns `dict[name, module]` and has 20+ test call sites | `app/services/tool_service.py`; `tests/test_tool_calling.py`, `tests/test_roll.py` |
| `ToolService` already keeps each discovered module in `_modules` | `tool_service.py` `reload_tools` |
| Tool modules have only `NAME` + `run`; no user-facing description exists; module docstrings start with REQ/SPEC ids | `app/intelligence/tools/*.py` lines 2-9 |
| `narrate`, `rules`, `monster`, `attack` raise `ToolError` on empty args; only `roll` defaults (`1d20`) | each tool's `run` |
| Tools run only in the worker; only the worker writes replies; `/invoke` returns text out of band and writes nothing | PAT-ARCH-004 rules 3 and 5, PAT-ARCH-001 |
| Composer is a controlled textarea; `draft` lives in `App.tsx` and is sent by `submitDraft` | `frontend/src/components/Composer.tsx`; `App.tsx` |
| `ToolListResp` still uses `class Config: schema_extra` (pydantic v1 idiom) | `app/schemas/v1.py`; PAT-ARCH-005 rule 6 |

| Trigger | Fired | Fact |
|---|---|---|
| Two viable approaches | yes | D1 selection effect (left UNRESOLVED by REQ-0034); D2 where descriptions come from |
| Accepted-pattern change | yes (additive) | D2-A adds a name to the PAT-ARCH-004 tool contract (rule 1) |
| Hard to reverse / new dependency | no | an optional response field and frontend code only; no new package |

## Decision Drivers
Scores 1-5; High 3, Medium 2, Low 1 (`docs/constraints.md`). Gate: the option must meet
REQ-0034's MUSTs (name **and** description; no hardcoded tool names).

| Dimension | W | Why |
|---|---|---|
| Simplicity, Reversibility, Maintainability | 3 each | solo part-time; one-sprint scope |
| Reuse, Fun/learning | 2 each | standing |
| Performance, Security | 1 each | standing, de-prioritised |

## Considered Options
D1, effect of selecting a tool:
- **D1-A** Insert `/name ` into the draft; the user adds args and sends as usual (worker dispatch).
- **D1-B** Call `POST /intel/tools/{name}/invoke` directly from the popup.
- **D1-C** Send `/name` as a chat message at once (no args).

D2, description source:
- **D2-A** Optional module constant `DESCRIPTION: str`; new `ToolInfo.description` (empty string if absent); a sibling service method so `list_tools()` stays as it is.
- **D2-B** First line of the module docstring (`__doc__`).
- **D2-C** Status quo endpoint, name only.

## Rubric Scoring
Order: Simp, Rev, Maint (x3); Reuse, Fun (x2); Perf, Sec (x1).

| Option | Scores and one-line facts | Total |
|---|---|---|
| D1-A | 5 one `onDraftChange` call; 5 frontend-only; 5 keeps PAT-ARCH-004's one dispatch path; 5 reuses WS send + `detect_tool`; 3 plain UI work; 5 no request; 4 no new surface | **70** |
| D1-B | 2 new api fn, args prompt, out-of-band result view; 3 new UI state to remove; 2 result never enters history, a second tool path next to the worker (PAT-ARCH-001/004); 3 endpoint exists but errors are non-PAT-005 `JSONResponse` bodies; 4 new flow; 4 one request; 4 same surface | 43 |
| D1-C | 4 one call; 5 frontend-only; 3 4 of 5 tools answer with a Usage error message in the log; 5 same path as A; 3; 4 one job; 4 | 60 |
| D2-A | 4 five one-line constants, one field, one service method, OpenAPI regen; 5 additive nullable field; 5 explicit, greppable, test-checkable like `NAME`; 4 mirrors the `NAME` convention; 3; 5; 5 | **66** |
| D2-B | 4 no new name but five docstrings rewritten; 5; 2 developer docs (REQ/SPEC ids) become UI text, edits for devs silently change the picker; 3; 3; 5; 5 | 55 |
| D2-C | fails the gate: REQ-0034 MUSTs a description, and adding one client-side would hardcode tool names | excluded |

## Decision Outcome
**D1-A (70) + D2-A (66).** Inserting `/name ` keeps PAT-ARCH-004 intact: the tool still runs
in the worker, the result is an assistant reply in history, and tools that need args get them
before sending. D2-A is the smallest change that gives kid-readable text without coupling it to
developer docstrings. Traded away: one-click invoke (only `/roll` works without args) and a
fully zero-backend change. The endpoint stays at its path and keeps the `{"tools": [...]}`
envelope; `description` is an additive field, so `list_tools()` and its tests are not touched.

## Consequences
- Positive: no new endpoint, no new dependency, one dispatch path; the popup shows new tools
  automatically once they define `DESCRIPTION`.
- Negative: the tool contract gains a third name; descriptions are English-only, one line.
- Follow-up (for the spec, not decided here): fetch the list once (new `getTools()` in
  `frontend/src/lib/api.ts`) and filter client-side by prefix; the popup shows only while the
  draft starts with `/` and has no space yet; Enter with the popup open selects instead of
  submitting; the touched `ToolListResp` moves to `model_config`/`json_schema_extra`
  (PAT-ARCH-005 rule 6); regenerate `docs/api/openapi.json`. The `/invoke` error-body deviation
  from PAT-ARCH-005 rule 1 is pre-existing and out of scope.

## Pattern Impact
- Uses PAT-ARCH-004 (dispatch unchanged) and PAT-ARCH-005 (envelope, OpenAPI snapshot).
- **Proposed amendment to accepted PAT-ARCH-004, rule 1, needs human sign-off (not applied):**
  "A module also exposes `DESCRIPTION: str`, one plain-language line shown in the client tool
  picker. `GET /api/v1/intel/tools` returns it as `description` ("" if absent)." On sign-off,
  `test_pat_arch_004_tool_modules_follow_the_contract` adds `DESCRIPTION` to its required names
  and the INDEX "Mechanically enforced" row is updated.
- No new pattern: the picker has one call site (constraint 2).
