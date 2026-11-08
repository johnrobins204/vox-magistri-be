---
id: SPEC-0021
requirement: REQ-0035
adr: ADR-0015
status: accepted
date: 2026-11-08
---

# Narrative vs admin messages: server-owned `meta.kind`, collapsible admin cards, narrative-only toggle

## 1. Requirement
REQ-0035; restatement in [`docs/requirements/LOG.md`](../requirements/LOG.md) (row REQ-0035).
ADR: [ADR-0015](../adr/0015-narrative-admin-message-kind.md) (status **accepted**). Pattern:
[PAT-ARCH-013](../patterns/architecture/PAT-ARCH-013-server-owned-message-kind.md) (**accepted**).
- `meta.kind` (`narrative`|`admin`) is server-only, set once at creation (user row in `submit_user_message`, reply in the worker) from one `NARRATIVE_TOOLS` set via `message_kind(tool_name)` in `tool_handler.py` (the user's slash line is classified with `detect_tool`, the dispatch parse); clients cannot set it; no migration; missing = narrative.
- `narrative_only`: optional bool on WS `user_message` and REST `MessageCreateReq`, saved as server-only `meta.narrative_only` on the user row; the pure `build_chat_messages` drops admin rows when it is set, before the `max_turns` slice; the toggle persists per browser.
- Readers use `meta.kind` only, never `content`; client message-text `startsWith('/')` checks are removed (`lib/slash.ts` works on the composer draft and stays).

**Decisions** (owner, 2026-11-08):

| Q | Decision |
|---|---|
| Q1 | `NARRATIVE_TOOLS = {"narrate","attack","roll"}`; `rules`, `monster` admin. World mining stays on `{"narrate"}` only (PAT-ARCH-012 unchanged); it MUST NOT reuse `NARRATIVE_TOOLS` |
| Q2 | Admin cards expanded by default; collapse state per card, not saved |
| Q3 | Toggle persists in `localStorage` only |
| Q4 | Narrator and `/narrate` replies are narrative; filter only while the toggle is on |
| Q5 | Player's slash line is the header of its admin card (one card per command); failed/unknown too |
| Q6 | Future, unknown, help and failed tools are admin |
| Q7 | No backfill; old rows count as narrative |
| Q8 | `/roll`, `/attack` show a compact command echo; diary omits admin entries and roll results |

## 2. Test Spec
Backend: pytest from the repo root, `./venv-dnd-server/bin/python -m pytest -q`; existing tests MUST keep passing in every package. Helpers: `session_store` (`tests/conftest.py`), `make_stub_service`/`wait_idle` (`tests/session_helpers.py`); copy `slash_env` from `tests/test_slash_dispatch.py`.
Frontend has no test runner (out of scope): verify with `cd frontend && npm run build` plus the M-n manual rows (backend on `http://127.0.0.1:5000`, token `dev`, `npm run dev`).

### WP-1
All in `tests/test_message_kind.py` unless noted.
| Id | Exercises | Expected outcome |
|---|---|---|
| T-1 | `message_kind` over `None`, `"narrate"`, `"rules"`, `"monster"`, `"help"`, `"zzz"` | `None`, `"narrate"` narrative; the rest `MessageKind.ADMIN`; every name in `NARRATIVE_TOOLS` is narrative |
| T-2 | `NARRATIVE_TOOLS` | equals `frozenset({"narrate","attack","roll"})`; `message_kind` of `"attack"`, `"roll"` is narrative |
| T-3 | `submit_user_message` with `/rules grapple`, `hello`, `/narrate x`, `/nope`; and `hello` with `payload["meta"] = {"kind": "admin"}` | stored user `meta["kind"]`: admin, narrative, narrative, admin; client-sent value stripped (narrative) |
| T-4 | `slash_env` REST `/rules x` (stub tool), `/narrate a storm`, plain chat, `/nope hi` | user/reply kinds: admin/admin, narrative/narrative, chat reply narrative; `/nope` user row status `error`, kind admin, no reply |
| T-5 | `regenerate_reply` on a `/rules` reply | reply keeps `meta["kind"] == "admin"` and `meta["tool"] == "rules"` |
| T-6 | `"kind" in RESERVED_META_KEYS` (file `tests/test_patterns.py`) | true |
| T-7 | exact-meta assertions in existing tests | `test_slash_dispatch.py` T-38 now expects `{"tool": "narrate", "reply_to": ..., "kind": "narrative"}`; fix any other exact meta equality likewise |

### WP-2
All in `tests/test_message_kind.py`.
| Id | Exercises | Expected outcome |
|---|---|---|
| T-10 | `submit_user_message` payload `{"content": "hi", "narrative_only": True}` | stored `meta["narrative_only"] is True`; absent or `False` leaves the key out |
| T-11 | payload `meta = {"narrative_only": True}`, no top-level flag | stored meta has no `narrative_only` |
| T-12 | WS `user_message` with `narrative_only` true / false / absent / `"yes"` | stored flag true / absent / absent; `"yes"` gives an `error` event `narrative_only must be a boolean`, nothing stored |
| T-13 | REST POST `{"content": "hi", "narrative_only": true}` | 202; stored meta has the flag; `/openapi.json` `MessageCreateReq` has boolean `narrative_only`, default false |

### WP-3
All in `tests/test_narrative_only_prompt.py` unless noted.
| Id | Exercises | Expected outcome |
|---|---|---|
| T-14 | `build_chat_messages`, literal dicts, flag omitted/False | admin rows still included (today's output) |
| T-15 | `narrative_only=True`; narrative user+reply, admin user+reply, all `completed` | `[system, narrative user, narrative reply, current]` |
| T-16 | `narrative_only=True`; rows with no `kind` key; a narrative row with `canon=False` | missing-kind rows kept; non-canon row skipped |
| T-17 | `narrative_only=True`, `max_turns=2`, history n1, n2, then four admin rows | prior is exactly `[n1, n2]` (filter before the slice) |
| T-18 | worker, recording `client.chat`: stored admin rows, then `submit_user_message(..., narrative_only=True)`; then again without it | flagged call excludes the admin rows, unflagged includes them |
| T-19 | `regenerate_reply` on the T-18 flagged reply | second chat call's messages equal the first |
| T-20 | `tests/test_world_detection_worker.py`: a `/roll`, an `/attack` and a `/rules` turn | none mined; chat and `/narrate` still mined (mining stays `{"narrate"}`; existing tests unchanged) |

### WP-4
Manual rows; files: `AdminCard.tsx`, `NarrativeLog.tsx`.
| Id | Exercises | Expected outcome |
|---|---|---|
| M-1 | `/rules grapple`, `/monster goblin`; collapse one card | each is ONE card visually distinct from bubbles (header = command, body = reply); only that card collapses |
| M-3 | `/nope`; then `grep -rn "startsWith('/')" frontend/src/components` | one admin card: command header and error text, no reply body; grep has no hits |
| M-4 | `/roll 1d20`, then a plain message | roll card with compact command echo; plain message a normal bubble |

### WP-5
Manual rows; files: `NarrativeLog.tsx`, `lib/preferences.ts`, `lib/ws.ts`.
| Id | Exercises | Expected outcome |
|---|---|---|
| M-6 | tick "Narrative only"; untick | admin cards vanish, bubbles and roll cards stay; untick restores them |
| M-7 | tick, reload; second browser profile | still ticked; other profile unticked |
| M-8 | send ticked / unticked; ask a follow-up to a `/rules` answer while ticked | WS frame has `"narrative_only": true` / `false`; admin rows stay in the DB but not in the model prompt |

### WP-6
| Id | Exercises | Expected outcome |
|---|---|---|
| T-21 | `tests/test_patterns.py::test_pat_arch_013_no_slash_text_sniffing`: scan `frontend/src/**/*.{ts,tsx}` for `startsWith('/')`, skipping `lib/slash.ts` | no hits |
| M-9 | `DiaryModal.tsx`: Game Diary after `/rules x`, `/roll 1d20`, `hello` | only narrative entries (no admin rows, roll result or `/roll` command) |
| M-10 | `npm run build` | passes |

### WP-7
Pattern edits are reviewed by diff only; `tests/test_patterns.py` must stay green.

## 3. Work Packages
Backend WP-1..WP-3 first, then frontend WP-4..WP-6, then WP-7 (docs).

### WP-1: Classification and `meta.kind` storage
- **Files:** `app/type_defs.py`, `app/intelligence/tool_handler.py`, `app/services/messages.py`, `app/services/inference_service.py`, `tests/test_message_kind.py` (new), `tests/test_patterns.py`, `tests/test_slash_dispatch.py`.
- **Inputs:** `detect_tool(payload) -> (name|None, args)` is in `tool_handler.py`. `messages.py` has `RESERVED_META_KEYS`, `_clean_user_payload`, `submit_user_message`. In `inference_service.py` the worker has `name` from `detect_tool(job.prompt)`; the slash branch calls `_append_reply(..., meta={**result["meta"], "tool": name})`, the chat branch `_append_reply(job.store, job.session_id, job.message_id, text)` (which merges meta on regenerate).
- **Outputs:** (1) `class MessageKind(StrEnum)` (`NARRATIVE = "narrative"`, `ADMIN = "admin"`) in `app/type_defs.py`. (2) In `tool_handler.py`: `NARRATIVE_TOOLS: frozenset[str] = frozenset({"narrate", "attack", "roll"})`, and `message_kind(tool_name: str | None) -> MessageKind` (None or in set: narrative; else admin). (3) `"kind"` in `RESERVED_META_KEYS`; `submit_user_message` sets `meta["kind"] = message_kind(detect_tool(content)[0])` after cleaning, before `create_message`. (4) Worker: slash reply meta adds `"kind": message_kind(name)`; chat reply passes `meta={"kind": MessageKind.NARRATIVE}` (regenerate refreshes it via the meta merge). (T-1..T-7)
- **Acceptance criteria:** every user row and reply written afterwards has `meta.kind`; the user row is classified once at save time from the slash parse; client-sent `meta.kind` is discarded; unknown/failed commands give an admin user row; no migration; T-1..T-7 and the full suite pass. Verify: `./venv-dnd-server/bin/python -m pytest tests/test_message_kind.py tests/test_slash_dispatch.py tests/test_patterns.py -q`.
- **Patterns used/created:** PAT-ARCH-013, PAT-ARCH-004, PAT-ARCH-005 (StrEnum).

### WP-2: `narrative_only` request flag (WS and REST), saved on the user row
- **Files:** `app/schemas/v1.py`, `app/api/v1/ws.py`, `app/services/messages.py`, `tests/test_message_kind.py`.
- **Inputs:** `MessageCreateReq` in `schemas/v1.py`; `_handle_user_message` in `ws.py` calls `submit_user_message` with `payload={"client_message_id", "role", "content", "meta": None}`; REST passes `payload.dict()`. `messages.py` has `RESERVED_META_KEYS`, `_clean_user_payload`, `submit_user_message` (it may already set `meta["kind"]`; keep that).
- **Outputs:** `narrative_only: bool = Field(False, description=...)` on `MessageCreateReq`; WS reads `data.get("narrative_only", False)` and, if not a `bool`, sends error `narrative_only must be a boolean` before storing anything; both transports pass it as top-level `payload["narrative_only"]`. `"narrative_only"` added to `RESERVED_META_KEYS`; `submit_user_message` sets `meta["narrative_only"] = True` only when `payload.get("narrative_only") is True`. Document the field in the `_handle_user_message` docstring. Tests T-10..T-13.
- **Acceptance criteria:** optional, default false, stored only as server-set `meta.narrative_only` on the user row; an idempotent replay (same `client_message_id`) changes and enqueues nothing; a non-bool WS value is rejected without storing; OpenAPI shows the field. Verify: `./venv-dnd-server/bin/python -m pytest tests/test_message_kind.py tests/test_ws_session.py -q`.
- **Patterns used/created:** PAT-ARCH-005, PAT-ARCH-013.

### WP-3: Context filter in `build_chat_messages`; mining guard unchanged
- **Files:** `app/intelligence/prompt_builders.py`, `app/services/inference_service.py`, `tests/test_narrative_only_prompt.py` (new), `tests/test_world_detection_worker.py`.
- **Inputs:** `build_chat_messages(system, history, current_message_id, current_text, *, max_turns, max_field_len)` is pure: it keeps a prior row when `status == "completed"`, role user/assistant and `canon is not False`, then `prior[-max_turns:]`. Rows may carry `meta.kind`; the current user row may carry `meta.narrative_only`. In `inference_service.py` the chat branch calls it and the mining guard is `if name in (None, "narrate"):` and MUST stay as is (PAT-ARCH-012: chat and `/narrate` only).
- **Outputs:** keyword `narrative_only: bool = False` on `build_chat_messages`; when true, a row with `(row.get("meta") or {}).get("kind") == "admin"` is skipped in the loop (before the slice); stays pure (update docstring). Worker chat branch: `current = job.store.get_message(job.session_id, job.message_id)`; pass `narrative_only=bool(current and (current.get("meta") or {}).get("narrative_only") is True)`. Do not touch the mining guard or import `NARRATIVE_TOOLS` there. Tests T-14..T-20.
- **Acceptance criteria:** flag off: prompts identical to today; on: admin command and reply rows absent and `max_turns` counts only surviving rows; regenerate/restart read the flag from the stored user row; mining still runs for chat and `/narrate` only, never `/roll`, `/attack`. Verify: `./venv-dnd-server/bin/python -m pytest tests/test_narrative_only_prompt.py tests/test_world_detection_worker.py tests/test_canon_prompt.py -q`.
- **Patterns used/created:** PAT-ARCH-003 (amended, WP-7), -010, -012 (unchanged), -013.

### WP-4: Frontend admin card (collapsible, distinct) and kind-based log rendering
- **Files:** `frontend/src/types.ts`, `frontend/src/lib/kind.ts` (new), `frontend/src/components/AdminCard.tsx` (new), `frontend/src/components/NarrativeLog.tsx`, `frontend/src/App.css`.
- **Inputs:** The server writes `meta.kind` (`'narrative'|'admin'`, absent = narrative) on user and reply rows, plus `meta.reply_to` (user id) and `meta.tool` on tool replies. `NarrativeLog.tsx` uses `content.startsWith('/')` (turn counting, `command-echo`) and `RollCard` for `meta.tool === 'roll'`; reusable: `toClock`, `CanonToggle`, `Bubble`, `RollCard`.
- **Outputs:** `types.ts`: `export type MessageKind = 'narrative' | 'admin'`. `lib/kind.ts`: `isAdmin(m)` (true only when `meta.kind === 'admin'`), `replyIndex(messages): Map<string, Message>` (user id to its reply via `meta.reply_to`). `AdminCard.tsx`: props `{command: Message | null, reply: Message | null, onToggleCanon}`; `<article className="admin-card">` with a header (command text, else tool name; collapse button with `aria-expanded`; `CanonToggle`) and a body (reply content, or `meta.error` if only a failed command exists); collapse is per-card `useState(false)`, expanded by default. `NarrativeLog.tsx`: an admin user row renders one `AdminCard` with its reply (that reply is not rendered again); an admin reply without its command renders alone; a user row whose reply has `meta.tool` and is not admin renders the compact `command-echo`; all else as before. A turn starts only at a user row that is not admin and has no tool reply. Remove every `startsWith('/')` here. `App.css`: `.admin-card`, visually distinct (own border/background).
- **Acceptance criteria:** M-1, M-3, M-4 pass; `cd frontend && npm run build` passes; classification uses only `meta.kind`, `meta.reply_to`, `meta.tool`, never text.
- **Patterns used/created:** PAT-ARCH-013.

### WP-5: "Narrative only" toggle, localStorage persistence, flag on every send, hide admin cards
- **Files:** `frontend/src/lib/preferences.ts` (new), `frontend/src/lib/ws.ts`, `frontend/src/App.tsx`, `frontend/src/components/NarrativeLog.tsx`, `frontend/src/App.css`.
- **Inputs:** `ws.ts` `sendUserMessage(text, clientMessageId)` sends `{action: 'user_message', text, client_message_id}`; `App.tsx` calls it in `sendText`. `lib/kind.ts` (`isAdmin`) and `AdminCard` exist (WP-4). The server accepts optional boolean `narrative_only`.
- **Outputs:** `preferences.ts`: `loadNarrativeOnly(): boolean`, `saveNarrativeOnly(v: boolean): void`, key `vox.narrative_only` (`'1'`/`'0'`; storage errors give false). `ws.ts`: `sendUserMessage(text, clientMessageId, narrativeOnly: boolean)` adds `narrative_only` to the frame (update `SessionSocket`). `App.tsx`: state from `loadNarrativeOnly()`, a labelled checkbox "Narrative only" above the log, saved on change, passed to `sendUserMessage` (add to `useCallback` deps) and to `NarrativeLog`. `NarrativeLog.tsx`: prop `narrativeOnly`; when true, admin user rows and admin replies are filtered out before turn slicing and rendering (display only).
- **Acceptance criteria:** M-6..M-8 pass; the flag is sent on every message, dice-tray rolls included; `npm run build` passes.
- **Patterns used/created:** PAT-ARCH-013.

### WP-6: Diary uses kind; mechanical check; final build and checklist
- **Files:** `frontend/src/components/DiaryModal.tsx`, `tests/test_patterns.py`.
- **Inputs:** `DiaryModal.tsx` filters with `isRollResult` (`meta.tool === 'roll'`) and `isSlashCommand` (`role === 'user' && content.startsWith('/')`). `lib/kind.ts` exports `isAdmin`, `replyIndex(messages)` (WP-4). `lib/slash.ts` uses `startsWith('/')` on the composer draft and stays. `tests/test_patterns.py` has `ROOT` and `_py` helpers.
- **Outputs:** in `DiaryModal.tsx` delete `isSlashCommand`; keep entries that are not roll results, not `isAdmin`, and not a user row whose reply (via `replyIndex`) has `meta.tool`. `tests/test_patterns.py`: `test_pat_arch_013_no_slash_text_sniffing` (scan `frontend/src` `*.ts`, `*.tsx`, skip `lib/slash.ts`, fail naming files containing `startsWith('/')`) and the T-6 check if WP-1 did not add it.
- **Acceptance criteria:** T-21, M-9, M-10 pass; walk M-1..M-10 once. Verify: `./venv-dnd-server/bin/python -m pytest tests/test_patterns.py -q` and `cd frontend && npm run build`.
- **Patterns used/created:** PAT-ARCH-013.

### WP-7: Pattern amendments (accepted by the owner)
- **Files:** `docs/patterns/architecture/PAT-ARCH-003-prompt-pipeline-in-worker.md`, `PAT-ARCH-004-slash-tools-in-worker.md`, `docs/patterns/INDEX.md` (summaries only).
- **Inputs:** ADR-0015 "Pattern Impact"; the patterns are `accepted` and stay so. PAT-ARCH-012 is NOT amended.
- **Outputs:** (a) PAT-ARCH-003 rule 2 gains "When the current user message has `meta.narrative_only` true, prior messages with `meta.kind` admin are also skipped, before the `max_turns` slice (ADR-0015)." (b) PAT-ARCH-004 rule 3 gains "replies also carry `meta.kind` (PAT-ARCH-013)." INDEX summaries match.
- **Acceptance criteria:** no `status` changes; `./venv-dnd-server/bin/python -m pytest tests/test_patterns.py -q` passes.
- **Patterns used/created:** amends PAT-ARCH-003, -004.

## 4. Other Details
- **Risks:** old rows lack `kind` and stay narrative (no backfill); narrative-tool user rows show as a bubble until their reply lands (Q8).
- **Rollback plan:** no migration; revert the commits; stored `meta.kind`/`meta.narrative_only` keys are inert.
- **Patterns:** PAT-ARCH-013 applied; PAT-ARCH-003/004 amended (WP-7); 005/010/012 unchanged; none created.
- **Non-goals:** DB column or migration; backend toggle persistence; backfill script; `docs/api/websocket.md`; a frontend test runner; editing `.github/BACKLOG.json` or `docs/requirements/LOG.md`.
