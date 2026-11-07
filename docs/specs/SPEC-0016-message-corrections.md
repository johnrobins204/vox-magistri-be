---
id: SPEC-0016
requirement: REQ-0027
adr: ADR-0011
status: accepted
date: 2026-11-07
---

# SPEC-0016: Message corrections (edit, regenerate, mark not canon)

## 1. Requirement
REQ-0027; restatement in [docs/requirements/LOG.md](../requirements/LOG.md) (not copied). ADR:
[ADR-0011](../adr/0011-message-corrections-canon-edit-regenerate.md) (**accepted** 2026-11-07, option B); pattern
[PAT-ARCH-010](../patterns/architecture/PAT-ARCH-010-non-destructive-message-corrections.md) (accepted). Decisions the packages use:
- **Gate:** cleared 2026-11-07: ADR-0011, PAT-ARCH-010 and the PAT-ARCH-001 rule 4 and PAT-ARCH-003 rule 2 wording changes were accepted and applied to the pattern files. Do not edit `docs/adr/` or `docs/patterns/`.
- Ladder v4 adds nullable `messages.canon` (NULL = canon); dicts and `MessageResp` carry `canon: bool`; clients cannot set it on create; statuses unchanged.
- One store write `update_message`; a content change appends `{content, replaced_at, reason}` to reserved `meta.revisions`; nothing is deleted.
- Regenerate re-enqueues the reply's user message; the worker revises its one reply in place. Edit: assistant replies only (400), 409 while the user message is queued/running. No canon cascade.
- `build_chat_messages` skips `canon` false; world selection inherits. No world extraction exists yet.

## 2. Test Spec (written first)
`pytest -q`, **no network, no Ollama**; `:memory:` SQLite (`session_store`, `stub_client`, `stub_svc` in `tests/conftest.py`) except file-DB tests in `tmp_path`.
Chat is stubbed (`monkeypatch.setattr(svc.client, "chat", ...)`); worker tests use `make_stub_service`, `wait_idle`; REST tests without a worker use
`create_app(services={"inference": FakeInference(), "session": session_store})` (`tests/session_helpers.py`, with `AUTH`).
Backend gate: `pytest -q` and `ruff check app tests scripts` green. Frontend gate: WP-8 and WP-9.

### WP-1
Files `tests/test_store_migration.py`, `tests/test_sqlite_store.py`, `tests/test_messages_helper.py`, `tests/test_session_rest.py`.
- T-01 `test_fresh_store_has_canon_column`: `:memory:` store has `messages.canon`, `user_version == 4`; all message dicts have `canon is True`.
- T-02 `test_v1_v2_v3_files_upgrade` (parametrized; add `_make_v3_db`): a file DB with a message row opens at 4, row kept, `canon is True`; reopen is a no-op.
- T-03 `test_null_and_zero_canon_read_back`: raw NULL reads `True`, 0 reads `False`.
- T-04 every `== 3` / `.to == 3` meaning "ladder head" in `tests/test_store_migration.py` and `tests/test_sqlite_store.py` becomes 4 (read `test_t05` first); `test_pat_arch_008_*` passes unchanged.
- T-05 `test_create_payload_cannot_set_canon_or_revisions` (helper file): `submit_user_message` payload `{"canon": False, "meta": {"revisions": ["x"]}}` stores `canon True`, no `revisions`.
- T-06 `test_message_resp_exposes_canon`: REST GET one and GET list return `"canon": true`.

### WP-2
File `tests/test_message_corrections_store.py`; assistant message "A", `meta {"reply_to": "u1"}`.
- T-10 `test_edit_appends_revision`: `update_message(sid, mid, content="B")` returns the fresh dict; `meta.revisions == [{"content": "A", "replaced_at": <ISO str>, "reason": "edit"}]`; a second edit appends, `revisions[0]` stays "A"; the same content adds none.
- T-11 `test_canon_toggle_only`: `canon=False` changes only `canon` (persisted in `get_message`/`list_messages`), no revision; `True` restores.
- T-12 `test_content_canon_meta_together`: `meta={"tool": "roll"}`, `reason="regenerate"`: meta merged (keeps `reply_to`), revision reason `regenerate`.
- T-13 `test_invalid_calls_write_nothing`: unknown ids `KeyError`; meta key `revisions`, bad reason, or nothing to change `ValueError`; non-JSON meta `TypeError`; row unchanged.
- T-14 `test_fresh_dicts_and_persistence`: mutating a result changes nothing; a `tmp_path` store keeps revisions and `canon False` on reopen; `SessionStore` has `update_message`.

### WP-3
Files `tests/test_prompt_builders.py` (T-20..T-22; its `_m` helper gains `canon=`), `tests/test_canon_prompt.py` (T-23, T-24).
- T-20 `test_non_canon_skipped`: a `canon False` completed message is absent, order kept; `True`, `None`, missing key stay.
- T-21 `test_max_turns_counts_only_canon`: 4 canon + 1 non-canon between, `max_turns=3`: the last 3 canon.
- T-22 existing T-07..T-17 and `test_pat_arch_003_*` pass (current text stays the last user message).
- T-23 `test_worker_prompt_omits_non_canon`: real store, turn-one reply set `canon False`, turn two via `submit_user_message`: recorded `client.chat` messages lack it, keep the rest.
- T-24 `test_world_selection_ignores_non_canon`: `make_stub_service(world_store=store, world=WorldSettings(entity_budget_chars=200))`; canon entities "Mira" (older) and "Zorblax" (newer), 120-char notes so only one fits; Zorblax named only in a non-canon prior message, current text names Mira: the world section holds Mira and not Zorblax (Zorblax would win the score-3 tie on recency if the non-canon mention counted; zero-score recency fill, T-35, is unchanged).

### WP-4
File `tests/test_messages_corrections.py`; `session_store`, `FakeInference`; errors are `CorrectionError(status_code, detail)`.
- T-30 `test_find_reply`: deep copy of the assistant message with `meta.reply_to == user id`, else `None`.
- T-31 `test_correct_edit_and_canon`: reply edit returns the dict with one `edit` revision; canon-only works on a user message, even while a regenerate is queued/running.
- T-32 `test_correct_rejects` (nothing written): content on a user message 400 "Only assistant replies can be edited"; blank or over `MAX_INPUT_CHARS` 400; no fields 400 "Nothing to update"; 404 "Session not found" / "Message not found"; content while the user message is queued/running 409 "Reply is being regenerated".
- T-33 `test_regenerate_enqueues_user_message`: returns `(user_message, True)`; one `FakeInference.calls` entry (user id, user content, store); no other write.
- T-34 `test_regenerate_rejects`: 404 unknown; user message id 400 "Only assistant replies can be regenerated"; no `reply_to` or missing user message 400 "Reply has no source message"; queued/running 409; `accept=False` returns `(user, False)`.

### WP-5
File `tests/test_message_corrections_api.py` (FakeInference app, `AUTH`).
- T-40 PATCH and POST regenerate return 401 without a token.
- T-41 PATCH `{"content": "B"}` on a reply: 200 `MessageResp`, `canon true`, `meta.revisions[0].content == "A"`; PATCH `{"canon": false}` on a user message: 200, GET one and list agree.
- T-42 PATCH errors: 404 session/message; content on a user message 400; `{}` 400; `""` 422; extra field 422; over `MAX_INPUT_CHARS` 400; user message queued 409.
- T-43 POST `.../messages/{reply_id}/regenerate`: 202 `{"message_id": <user id>, "status": "queued", "queue_position": 0}`, `Location`, one `FakeInference` call.
- T-44 regenerate errors: 404, 400 (user id), 409 (running), `accept=False` 429 `{"status": "queued_full", "retry_after": 5, "message_id": <user id>}` plus `Retry-After`.
- T-45 `/openapi.json` has both routes and boolean `MessageResp.canon` (no `docs/api/openapi.json` exists: n/a).

### WP-6
File `tests/test_regenerate_worker.py`; real `:memory:` store, `make_stub_service`, `wait_idle`, `chat` stub with mutable text, turn one via `submit_user_message`.
- T-50 `test_regenerate_revises_in_place`: reply "v1", chat -> "v2", `regenerate_reply`, `wait_idle`: 2 messages, same reply id, "v2", `revisions == [{content "v1", reason "regenerate"}]`, `reply_to` kept, both `completed`; after an operator edit "E", revisions are "v1" (edit), "E" (regenerate).
- T-51 `test_regenerate_prompt_is_prior_turns_only`: recorded chat ends with the user's content; the old reply and earlier non-canon messages are absent.
- T-52 `test_failed_regenerate_keeps_text`: chat raises: user `error` with `meta.error`, reply unchanged, no revisions; a later regenerate succeeds.
- T-53 `test_tool_reply_regenerated`: stub `tool_service` (see `tests/test_slash_dispatch.py`), `/roll 1d4` total 3 then 4: reply revised in place, `meta.total == 4`, `meta.tool == "roll"`.
- T-54 a `canon False` reply stays False; `_append_reply` for an answered user id returns the existing reply id; `tests/test_inference_reply.py` passes unchanged.

### WP-7
File `tests/test_ws_session.py` (append; `stub_client`, `stub_svc`, `session_store`).
- T-60 `test_ws_regenerate`: after one turn, `{"action": "regenerate", "message_id": <reply id>}`, chat -> "v2": `entry` (user message; status not asserted), `entry` (same reply id, "v2", `meta.revisions` length 1, `canon true`), `done` with the user id and the same reply id.
- T-61 `test_ws_regenerate_errors_keep_socket`: bad `message_id` "message_id is required"; unknown "Message not found"; user id: error mentioning assistant; `FakeInference(accept=False)`: "queue full" with the user id; `status` still answers.
- T-62 `test_ws_failed_regenerate`: chat raises: `error` with the user id, reply unchanged.
- T-63 after a REST PATCH edit, a new connection's snapshot entry has `canon` and `meta.revisions`; existing WS tests pass.

### WP-8
No frontend runner exists (`frontend/package.json`: `dev`, `build`, placeholder `lint`, `preview`); none is added. In `frontend/`:
- T-70 `npm ci && npm run build` exits 0 (`tsc -b` strict plus `vite build`; `npm ci` needs network once).
- T-71 `npm run lint` exits 0 (placeholder `echo`).

### WP-9
- T-72 `npm run build` exits 0 (new `NarrativeLog` props are required, so a missed call site fails `tsc -b`).
- T-73 diff inspection: Edit/Regenerate render only when `canCorrect(m)`; every row kind has a canon toggle; non-canon rows have class `non-canon`; badge only when `isEdited(m)`. Non-gating manual smoke: `./restart.sh` (needs Ollama).

## 3. Work Packages
Nothing blocks any package (sign-offs cleared 2026-11-07).

### WP-1: v4 `canon` column, `canon` on dicts and `MessageResp`
- **Files:** `app/services/repos.py`, `app/services/messages.py`, `app/schemas/v1.py`, the test files of Test Spec WP-1
- **Inputs:** `_MIGRATIONS` head is v3; `_message_from_row` and `create_message` build message dicts; `RESERVED_META_KEYS` is a frozenset in `messages.py`.
- **Outputs:** append `(4, "messages", "canon", "ALTER TABLE messages ADD COLUMN canon INTEGER DEFAULT 1")`; `_message_from_row` adds `"canon": row["canon"] is None or bool(row["canon"])`; `create_message` returns `"canon": True` and its INSERT omits `canon`; add `"revisions"` to `RESERVED_META_KEYS`; `MessageResp.canon: bool = Field(True, ...)`; version asserts moved (T-04); tests comparing whole message dicts gain `canon`.
- **Acceptance criteria:** T-01..T-06 pass; v1, v2, v3 file DBs upgrade in place keeping every row.
- **Patterns used/created:** PAT-ARCH-008, PAT-ARCH-010 rule 1.

### WP-2: Store write `update_message`
- **Files:** `app/services/repos.py`, `app/type_defs.py`, `tests/test_message_corrections_store.py` (new)
- **Inputs:** WP-1 done; `update_message_status` models the lock, transaction and `KeyError`.
- **Outputs:** `update_message(session_id, message_id, *, content: str | None = None, canon: bool | None = None, meta: dict | None = None, reason: str = "edit") -> dict` on `SqliteSessionStore` and the `SessionStore` Protocol. Validate first (`ValueError`: nothing to change, `reason` not `edit`/`regenerate`, meta key `revisions`). One transaction: unknown ids `KeyError`; a differing `content` appends `{"content": old, "replaced_at": now ISO, "reason": reason}` to `meta.revisions` and is stored; `canon` stored 1/0; `meta` merged over existing; `updated_at` bumped; meta serialized before the UPDATE; status unchanged. Returns the fresh dict.
- **Acceptance criteria:** T-10..T-14 pass; existing store tests pass.
- **Patterns used/created:** PAT-ARCH-002, PAT-ARCH-010 rules 2-3.

### WP-3: Canon filter in `build_chat_messages`
- **Files:** `app/intelligence/prompt_builders.py`, `tests/test_prompt_builders.py`, `tests/test_canon_prompt.py` (new)
- **Inputs:** WP-1, WP-2 done. `build_chat_messages(system, history, current_message_id, current_text, *, max_turns, max_field_len)` keeps completed user/assistant messages before the current id; the worker's `_inject_world` reads its output.
- **Outputs:** the prior-message loop also skips messages whose `canon` is `False` (`None`/missing = canon), before the `max_turns` slice; docstring updated; no new imports.
- **Acceptance criteria:** T-20..T-24 pass; existing prompt and world tests pass.
- **Patterns used/created:** PAT-ARCH-003, PAT-ARCH-010 rule 5.

### WP-4: Shared correction helper, `find_reply` move
- **Files:** `app/services/messages.py`, `app/api/v1/ws.py`, `tests/test_messages_corrections.py` (new)
- **Inputs:** WP-1, WP-2 done. `ws._find_reply(store, session_id, user_message_id)` returns a deep copy of the assistant message whose `meta.reply_to` matches; `messages.py` has `MAX_INPUT_CHARS`.
- **Outputs:** in `messages.py`: `CorrectionError(Exception)` with `status_code`, `detail`; `find_reply` (moved verbatim; ws imports it); `correct_message(*, store, session_id, message_id, content=None, canon=None) -> dict` (`update_message(..., reason="edit")`); `regenerate_reply(*, store, inference, session_id, reply_id) -> tuple[dict, bool]` (enqueues `message_id=<user id>`, `prompt=<user content>`, `store`; returns the user message and the enqueue result). Codes and texts are the T-32 and T-34 strings. Log `message.corrected` and `message.regenerate_requested` with ids and flags only, never text.
- **Acceptance criteria:** T-30..T-34 pass; `tests/test_ws_session.py` and `test_pat_arch_001_*` pass.
- **Patterns used/created:** PAT-ARCH-001, PAT-ARCH-005, PAT-ARCH-010 rules 3-4.

### WP-5: REST PATCH and regenerate routes
- **Files:** `app/api/v1/session.py`, `app/schemas/v1.py`, `tests/test_message_corrections_api.py` (new)
- **Inputs:** WP-4 helper. `post_message` shows the 202/429 shapes (`MAX_QUEUE_RETRY_AFTER`, `Location`). Routers never import `repos`.
- **Outputs:** `MessageUpdateReq` (`content: str | None` with `min_length=1`, `canon: bool | None`, `extra="forbid"` via `ConfigDict`); `PATCH /api/v1/sessions/{session_id}/messages/{message_id}` (`response_model=MessageResp`, `require_local_token`) via `correct_message`; `POST .../messages/{message_id}/regenerate` (202, `require_local_token`) via `regenerate_reply`: body `{"message_id": user id, "status": "queued", "queue_position": ...}` plus `Location`, or the 429 body and `Retry-After` when not queued. `CorrectionError` becomes `HTTPException(status_code, detail)`.
- **Acceptance criteria:** T-40..T-45 pass.
- **Patterns used/created:** PAT-ARCH-005, PAT-ARCH-001.

### WP-6: Worker regenerates in place
- **Files:** `app/services/inference_service.py`, `tests/test_regenerate_worker.py` (new)
- **Inputs:** WP-2, WP-4 done. `_append_reply(store, session_id, user_message_id, text, meta=None)` always creates an assistant message with `meta.reply_to`; the worker then sets the user message `completed`, or `error` on any exception.
- **Outputs:** `_append_reply` first calls `find_reply` (from `app.services.messages`); if a reply exists it calls `store.update_message(session_id, reply["id"], content=text, meta=meta, reason="regenerate")`, logs `reply.revised` (`session_id`, `message_id`, `reply_id`) and returns the existing id; else unchanged. Exceptions propagate; canon, `reply_to` and the `InferenceService` Protocol are untouched.
- **Acceptance criteria:** T-50..T-54 pass; `test_inference_reply.py`, `test_slash_dispatch.py`, `test_queue_bounds.py` pass.
- **Patterns used/created:** PAT-ARCH-001 rule 4, PAT-ARCH-010 rule 4.

### WP-7: WebSocket `regenerate` action
- **Files:** `app/api/v1/ws.py`, `tests/test_ws_session.py`
- **Inputs:** WP-4, WP-6 done. `_handle_user_message` submits, sends `entry` for the user message, waits via `_wait_for_terminal(...)`, then sends `entry` (from `find_reply`) and `done`, or `error`. `_send_error(ws, message, message_id=None)`.
- **Outputs:** move that wait-and-reply tail into `_await_reply(ws, store, inference, session_id, user_message)` used by both handlers (`user_message` behaviour unchanged); `_handle_regenerate`: no inference -> "Inference service unavailable"; `message_id` not a non-empty string -> "message_id is required"; `regenerate_reply`, a `CorrectionError` -> `_send_error(detail)`; not queued -> "Inference queue full; try again later" with the user id; else `entry` of the fresh user message, then `_await_reply`. Dispatch `action == "regenerate"` in `ws_session`; no new event type.
- **Acceptance criteria:** T-60..T-63 pass.
- **Patterns used/created:** PAT-ARCH-001, PAT-ARCH-005.

### WP-8: Frontend types, calls, correction helpers
- **Files:** `frontend/src/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/lib/ws.ts`, `frontend/src/lib/corrections.ts` (new)
- **Inputs:** `Message` lacks `canon`; `api.ts` has `authHeaders()`, `parseJson<T>()`; `SessionSocket` has `sendUserMessage`, `sendStatus`, `close`.
- **Outputs:** `types.ts`: `Message.canon: boolean`, `MessageRevision { content: string; replaced_at: string; reason: 'edit' | 'regenerate' }`. `api.ts`: `updateMessage(sessionId, messageId, changes: { content?: string; canon?: boolean }): Promise<Message>` (PATCH `/api/v1/sessions/{id}/messages/{mid}`, `authHeaders()`, `parseJson`). `ws.ts`: `sendRegenerate(messageId)` sends `{action: 'regenerate', message_id}`. `corrections.ts` (pure): `isCanon(m)` = `m.canon !== false`; `revisionsOf(m)` = `meta.revisions` if an array else `[]`; `isEdited(m)` = non-empty revisions; `canCorrect(m)` = assistant and `completed`.
- **Acceptance criteria:** T-70, T-71 pass. No new dependency or test framework.
- **Patterns used/created:** none.

### WP-9: Frontend UI: Edit, Regenerate, canon toggle, dimmed rows, edited badge
- **Files:** `frontend/src/components/NarrativeLog.tsx`, `frontend/src/App.tsx`, `frontend/src/App.css`
- **Inputs:** WP-8 exports. `NarrativeLog({ messages, isSending })` renders `RollCard`, a `command-echo` paragraph and a `bubble` article. `App.tsx` has `upsertMessage`, `setErrorText`, `setIsSending`, `socketRef`, `socketStatus`.
- **Outputs:** `NarrativeLog` gets required props `onToggleCanon(message)`, `onEdit(message, text)`, `onRegenerate(message)`. A `CanonToggle` button ("Canon"/"Not canon") on all three row kinds; `!isCanon(m)` rows get class `non-canon`; a DM bubble with `canCorrect(m)` gets Edit (inline textarea, Save disabled when blank, Cancel) and Regenerate, disabled while `isSending`; `edited` badge (class `edited-badge`) when `isEdited(m)`. `App.tsx`: toggle and edit call `updateMessage`, then `upsertMessage` the result, errors to `setErrorText`; regenerate clears the error, `setIsSending(true)`, calls `sendRegenerate(message.id)` only when `socketStatus === 'open'`. `App.css`: `.non-canon` dimmed (opacity ~.55), `.edited-badge`, button styles.
- **Acceptance criteria:** T-72, T-73 pass; other rows behave as before apart from the toggle.
- **Patterns used/created:** none.

## 4. Other Details
- **Risks:** regenerating a tool reply re-runs it (ADR-0011); a failed regenerate leaves the user message `error`, so that turn leaves history until retried; the frontend gate needs `npm ci` once (`node_modules` absent).
- **Rollback plan:** revert the commits; the nullable `canon` column and `user_version 4` stay in `dnd.db`, inert (older code only logs `store.schema_newer_than_code`). Back up `dnd.db` first.
- **Patterns applied/created:** PAT-ARCH-001, 002, 003, 005, 008 (accepted); PAT-ARCH-010 (accepted; none authored here).
- **Non-goals:** world extraction; canon cascade; hide-and-reveal, whispers, revision-history UI or restore; WS edit/canon actions; a frontend test runner or linter.
