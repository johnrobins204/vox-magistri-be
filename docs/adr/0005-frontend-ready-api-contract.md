---
id: ADR-0005
status: proposed
date: 2026-10-11
requirement: REQ-0010
supersedes: null
superseded_by: null
---

# Frontend-ready API contract: FastAPI-default errors, explicit envelopes, UTC at the edge, session list/get/delete via a widened Protocol

## Context
REQ-0010 ([LOG](../requirements/LOG.md)) requires the REST, `/intel` and WS contract to be
ready for a frontend. That means: pydantic v2 idioms; one message-status enum that uses the
REQ-0003 vocabulary; session list, get and delete endpoints; an explicit, documented
list-messages shape; one error-body shape, with the dead 429 path removed or made reachable;
aware-UTC datetimes in the API while storage stays naive UTC; one shared user-message length
limit; a documented WS event contract without streaming; and a checked-in `openapi.json` with
a drift test and no new dependency. No frontend exists yet (constraints.md; the React client
is a separate, not-yet-written repo, per `.github/copilot-instructions.md`), so breaking JSON
changes are cheap now and expensive later.

Patterns consulted: PAT-ARCH-001, -002, -003 and -004, and PAT-CODE-001 (all accepted).

**ADR triggers (docs/adr/README.md):**
- *Changes a cross-cutting convention.* **Fired.** The error-body convention (named
  explicitly in the README) changes across every router. The API-wide datetime
  serialization and the collection-response shape also change, and so does the `SessionStore`
  Protocol, which every backend implements (PAT-ARCH-001).
- *Deviates from or supersedes an accepted entry.* **Fired.** Accepted ADR-0004 item 7 and
  PAT-ARCH-004 rule 5 put tool-invoke errors in `ToolInvokeResp.error`. REQ-0010 (5) requires
  a shared shape, so that rule must change (flagged below, not applied).
- *Two or more viable approaches.* **Fired.** There are real alternatives for the error shape
  (3 options), the list shape (3), the 429 path (2 viable), the limit value and its location
  (3), and the delete semantics (3).
- *Costly or hard to reverse.* **Borderline.** Nothing in storage changes, and with no consumer
  every JSON change is reversible now. The checked-in `openapi.json` does freeze a contract
  that a frontend will build against.
- *New dependency.* **Not fired.** The snapshot test uses `app.openapi()` and stdlib `json`.

The backlog's guess ("ADR likely: no") is overturned on the first two triggers. "No consumer
yet, so keep it simple" still decides most of the sub-decisions below. It is a scoring input,
not a reason to skip the ADR.

**Verified facts (tree on 2026-10-11):**

| # | Fact | Where |
|---|---|---|
| F1 | Nine models use v1 `class Config` + `schema_extra`, and `MessageResp` also has `orm_mode = True`. `constr`/`ContentStr` are imported or defined but unused. Status descriptions say `queued\|in_progress\|done\|error\|cancelled`, and the examples use `"done"` | `app/schemas/v1.py:6,19,25,38,54,59-61,77,82,99` |
| F2 | The code emits only `queued/running/completed/error/cancelled`. `enqueue` writes `queued`. The worker writes `running`, `completed`, `error` and `cancelled`. WS `TERMINAL_STATUSES` and restart recovery use the same words. The store returns `str` | `inference_service.py:85-111,131-260`, `ws.py:28`, `repos.py:74-88` |
| F3 | `GET .../messages` returns a bare list (`response_model=list[MessageResp]`). `MessageListResp` is imported nowhere. `get_message_status` and `post_message` have no `response_model`, and `MessageStatusResp` is unused | `session.py:9,39`, `v1.py:94`, `intelligence.py:13-19` |
| F4 | The only session route is `POST /api/v1/sessions`. There are no list, get or delete routes | `session.py:25` |
| F5 | The Protocol has six methods. A guard test asserts that exact name set | `type_defs.py:6-18`, `tests/test_single_session_model.py::test_session_store_protocol_unchanged` |
| F6 | There are three error bodies. `HTTPException` gives `{"detail": str}` (routes and `deps.require_local_token` 401). The 429 is a `JSONResponse` with `{status: "queued_full", retry_after, message_id}`. Tool-invoke errors are `{text: null, meta: null, error, detail?}` | `session.py:189-199`, `intelligence.py:30-34,57-65`, `deps.py` |
| F7 | `Queue()` is unbounded, so `put_nowait` never raises `Full`. `enqueue` returns `False` only from its broad `except` (unexpected bug). The 429 is reachable only through the test double `FakeInference(accept=False)` | `inference_service.py:63,109-111`, `tests/session_helpers.py` |
| F8 | The store writes `datetime.utcnow()` (deprecated since Python 3.12; the project runs 3.13) as naive ISO TEXT. REST serializes naive values through `MessageResp`. WS sends raw store dicts through `jsonable_encoder`. `snapshot_at` is a `float` from `time.time()` | `repos.py:16-17`, `ws.py:36-40,99`, `messages.py:57-61`, `pyproject.toml` |
| F9 | REST rejects content longer than `MAX_INPUT_TOKENS*4 = 4096` chars with 400, but the schema allows 16384, so 4097-16384 gives 400 and anything longer gives 422. WS has no limit. The worker sends the current user message untruncated (PAT-ARCH-003 rule 2 truncates only history), and `OllamaClient.chat` sets no `num_ctx`, so Ollama's default context window applies | `session.py:19,172-176`, `v1.py:34`, `ws.py:72-87`, `client.py:56-66` |
| F10 | Deprecated calls in files that might be touched: `payload.dict()` (session.py:180); `ns.dict()` (config.py:174); `@app.on_event` (factory.py, a known gap) | as listed |
| F11 | `messages.session_id REFERENCES sessions(id)` has no `ON DELETE CASCADE`, and `PRAGMA foreign_keys = ON`. A session cannot be deleted before its messages | `repos.py:44-63` |
| F12 | Versions: FastAPI 0.141.1, pydantic 2.13.5, Python 3.13. `enum.StrEnum`, `datetime.UTC`, `app.openapi()` and `AfterValidator` are all available with no new dependency | `requirements.txt`, `pyproject.toml` |

Out of scope (requirement guard): streaming (REQ-0007), auth/CORS (REQ-0009; `POST /sessions`
stays without a token), campaign domain (REQ-0015), general hygiene (REQ-0012; `config.py`
`.dict()` and `factory.py` `on_event` are left alone because this design does not touch those
files), persistence design (REQ-0005), and `/invoke` context semantics.

## Decision Drivers
Weights: High = 3, Medium = 2, Low = 1. Scores are 1 (poor) to 5 (strong). Weighted total =
sum of (score x weight). The maximum is 100.

| Dimension | Weight | Why it matters here |
|---|---|---|
| Simplicity / smallest-edit fit (Simp) | High (3) | constraints.md 1; one part-time developer |
| Reversibility (Rev) | High (3) | Cheap now; once a frontend exists, every break costs two repos |
| Maintainability (Maint) | High (3) | Custom layers and two sources of truth are what produced F1/F6/F9 |
| Reuse of existing patterns/deps (Reuse) | Medium (2) | FastAPI defaults, the Protocol, the shared helper, stdlib |
| Fun / learning (Fun) | Medium (2) | constraints.md 5 |
| Performance (Perf) | Low (1) | One household |
| Security beyond sane defaults (Sec) | Low (1) | No production intent |
| **Frontend contract clarity (FC)** (added) | High (3) | This is the point of REQ-0010: a frontend can be built from `openapi.json` and `websocket.md` alone, with uniform shapes and nothing advertised that does not exist |
| **Accepted-decision fit (Fit)** (added) | Medium (2) | Each edit to an accepted ADR or pattern costs a sign-off round. Not High, because REQ-0010 (5) already forces one such edit (ADR-0004 item 7) |

Gate: an option that fails a REQ-0010 MUST is disqualified, whatever its total.

## Considered Options and Rubric Scoring

### A - How the session list, get and delete endpoints reach the store
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | FC (3) | Fit (2) | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| **A1 Widen the Protocol with `list_sessions()` and `delete_session(id)`** | 4: two ~10-line methods in `repos.py`, two Protocol lines, one guard-test update | 4: additive, and there is one backend | 5: still one session API (PAT-ARCH-001 rule 2) | 5: follows PAT-ARCH-002 (lock, one transaction, `KeyError`) | 3: some SQL | 3: GET-one scans a list of tens of rows | 3: neutral | 4: the endpoints get `created_at`; GET-one derives it from the list | 5: PAT-ARCH-001 says "adding capability means extending the one Protocol". The pattern text is unchanged | **83** |
| A2 A non-Protocol helper that runs SQL on `SqliteSessionStore._conn` | 4: same amount of code | 3: a hidden second API to unwind | 2: a parallel session API that bypasses the store lock | 1: breaks PAT-ARCH-001 rule 2 and PAT-ARCH-002 rule 1 | 2 | 3 | 3 | 4: same JSON | 1: would need an amendment to accepted PAT-ARCH-001 | **53** |
| A3 Widen with three methods (`list_sessions`, `get_session_info`, `delete_session`) | 3: a third method plus a test | 4 | 4: every future backend implements one extra method for a single route | 5 | 3 | 4: PK lookup | 3 | 4: same JSON | 4: allowed, but against "keep it small" | **76** |

There is no "derive from existing methods" option. No existing method can enumerate or delete
sessions (F4, F5). "Do nothing" fails REQ-0010 (3).

### B - List-messages response shape
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | FC (3) | Fit (2) | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| B1 Bare list (status quo), delete `MessageListResp` | 5: delete one class | 2: adding pagination later breaks the frontend | 4 | 4 | 2 | 3 | 3 | 3: an array cannot carry metadata | 5 | **70** |
| B2 Full envelope `{messages, next_cursor, total}` | 4: response model and route change; tests that index the list change | 4 | 3: `next_cursor` is always null, a speculative field (constraint 2) | 4: uses the class as it is | 3 | 3 | 3 | 3: advertises pagination that does not exist | 5 | **72** |
| **B3 Minimal envelope `{messages: [MessageResp]}`** (trim `MessageListResp`) | 4: same edit as B2 | 5: adding `next_cursor`/`total` later does not break clients | 5: no dead fields | 4 | 3 | 3 | 3 | 5: explicit, named and documented | 5 | **87** |

### C - Error-body shape for REST and `/intel`
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | FC (3) | Fit (2) | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| **C1 FastAPI default `{"detail": str}` everywhere; 422 keeps FastAPI's list** | 5: replace `_tool_error` with `HTTPException` at 4 sites and delete the 429 `JSONResponse`; no handlers, and `factory.py` is untouched | 5: adding `code` later does not break clients | 5: nothing custom to maintain | 5: already used by every `HTTPException` and by `require_local_token` | 2 | 3 | 3 | 3: one top-level key, but no machine-readable code, and 422 `detail` is a list | 3: amends ADR-0004 item 7 / PAT-ARCH-004 rule 5 (all options do) | **80** |
| C2 `{"detail": str, "code": str}` via custom handlers for `HTTPException` and `RequestValidationError` | 3: new module, two handlers, a `code` at about 12 raise sites. Registering them touches `factory.py`, which brings in the `on_event` deprecation migration (F10, REQ-0010 (1)) | 4: removing `code` once used is a break | 3: handlers must track Starlette/FastAPI exception types | 3: keeps `detail` | 4 | 3 | 3 | 5: string `detail` everywhere plus a code | 3 | **71** |
| C3 `{"error": {"code", "message"}}` envelope | 2: C2's handlers plus every test assertion on `detail` rewritten | 3 | 3 | 2: departs from the shape FastAPI and its docs use | 4 | 3 | 3 | 5 | 3 | **63** |

Sensitivity: C2 overtakes C1 only if FC is weighted 8 or more, out of a scale that tops out at 3.

### D - Where the message-status vocabulary is defined
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | FC (3) | Fit (2) | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| **D1 `class MessageStatus(StrEnum)` in `app/type_defs.py`** | 4: one class and about 6 import sites. `StrEnum == str`, so SQL, stored TEXT, comparisons and the Protocol's `status: str` do not change | 5 | 5: a typo is an `AttributeError` | 4: `type_defs.py` is already the shared contract module | 4 | 3 | 3 | 5: OpenAPI emits a named `MessageStatus` component for frontend codegen | 5: vocabulary unchanged (REQ-0003) | **89** |
| D2 `Literal[...]` alias in `type_defs.py` | 5: one line | 5 | 4: string literals stay unchecked at runtime | 4 | 2 | 3 | 3 | 4: enum inlined per field, with no named component | 5 | **82** |
| D3 `StrEnum` in `app/schemas/v1.py` | 4 | 4 | 3: the service and worker would import the API schema module (layer inversion) | 2 | 3 | 3 | 3 | 5 | 5 | **74** |

### E - API datetimes vs storage
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | FC (3) | Fit (2) | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| **E1 API edge only: `UtcDatetime` in schemas; WS payloads go through the same models; storage unchanged** | 4: one `Annotated` type plus 3 WS serialization sites | 5: no data touched | 4: one serializer path for REST, `/intel` and WS | 5: pydantic only; PAT-ARCH-001 rule 7 (`jsonable_encoder`) still applies | 3 | 3 | 3 | 5: identical item shapes and UTC strings on every transport | 5: ADR-0003 and PAT-ARCH-002 untouched | **86** |
| E2 The store returns aware datetimes but keeps writing naive TEXT | 4 | 4 | 3: aware reads next to naive writes is a mixed-comparison hazard in store code | 3 | 3 | 3 | 3 | 4: WS still sends raw dicts, with `+00:00` | 4: changes the store-dict contract that PAT-ARCH-003 builders consume | **71** |
| E3 Store aware ISO TEXT (`+00:00`) | 2: existing rows are naive, so reads need a migration or mixed parsing | 2: on-disk format change | 3 | 2 | 3 | 3 | 3 | 4 | 1: supersedes accepted ADR-0003 / PAT-ARCH-002 naive-UTC storage | **51** |

### F - One user-message length limit: value and location
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | FC (3) | Fit (2) | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| **F1 4096 chars, `MAX_MESSAGE_CHARS` in `app/services/messages.py`; helper enforces it; schema `max_length` references it** | 5: keeps today's effective REST limit; one constant | 5: change one line and regenerate the snapshot | 5: one definition | 4: the shared helper is PAT-ARCH-001 rule 4's single write path | 2 | 4: about 1k tokens fits next to the system prompt and 6x240-char history inside Ollama's default context (no `num_ctx` is sent, F9) | 3 | 5: `maxLength: 4096` appears in OpenAPI | 5 | **89** |
| F2 16384 chars, same location | 5 | 5 | 4: about 4k tokens can exceed Ollama's default context, which silently drops the start of the prompt (the system message), a confusing failure | 4 | 2 | 2 | 3 | 5 | 5 | **84** |
| F3 Setting `app.max_message_chars` read at runtime | 3: touches `config.py`, `settings.json`, and `config.py:174` `.dict()` (F10) | 4 | 3: the schema cannot see a runtime setting, so there are two sources | 3 | 3 | 4 | 3 | 2: OpenAPI either omits the limit or varies with env, so the drift test depends on the environment | 5 | **65** |

### G - The dead 429 `queued_full` path
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | FC (3) | Fit (2) | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| **G1 Remove it. `queued=False` (unexpected enqueue failure) makes the helper mark the message `error` (`meta.error`); REST returns 503 `{"detail"}`; WS sends its error event** | 4: delete about 15 lines, add about 4 | 5 | 5: no dead branch or constant | 4: existing `update_message_status` | 2 | 3 | 3 | 4: 503 honestly reports that the server could not queue the message, and no message is left `queued` forever | 5 | **82** |
| G2 Make it reachable with `Queue(maxsize=N)` | 2: a new setting (`config.py`, plus its `.dict()` fix), and `Full` lands in the broad `except` with a stack trace | 4 | 3 | 3 | 4: backpressure is nice to learn | 4 | 3 | 4: standard 429 + Retry-After | 5 | **70** |
| G3 Keep the dead path | 5 | 5 | 2 | 4 | 1 | 3 | 3 | 2: documents an error that never happens | 5 | 68, **disqualified** (fails REQ-0010 (5)) |

### H - Session delete semantics
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | FC (3) | Fit (2) | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| **H1 Hard delete; delete messages then the session in one transaction; allowed at any time; 204** | 5: no schema change (F11 handled by statement order) | 3: data is gone (copying the `.db` file is the backup) | 5 | 5: PAT-ARCH-002 one transaction, `KeyError` on unknown | 3 | 3 | 3 | 4 | 5 | **83** |
| H2 Soft delete (`deleted_at` column) | 2: `user_version` 2, an `ALTER`, and every read filters | 5 | 2: every query must remember the filter | 3 | 3 | 3 | 3 | 4 | 3: reopens the ADR-0003 schema (REQ-0005 is done) | **63** |
| H3 Hard delete, but 409 while any message is `queued`/`running` | 4 | 3 | 4 | 5 | 3 | 3 | 3 | 3: the frontend must handle 409 and retry, which is poor UX for a child | 5 | **74** |

## Decision Outcome
Choose **A1 + B3 + C1 + D1 + E1 + F1 + G1 + H1**. Each won its table on the weighted rubric
(83, 87, 80, 89, 86, 89, 82, 83). The overall theme is to use framework defaults and one
definition per concept, and to add nothing speculative.

1. **Pydantic v2.** In `app/schemas/v1.py`, every `class Config` becomes `model_config =
   ConfigDict(json_schema_extra={"examples": [...]})`. Examples use the real vocabulary and
   `Z` timestamps. `constr`/`ContentStr` are deleted. `orm_mode` is dropped and
   `from_attributes` is not added, because the store returns dicts (`repos.py:20-30`). In
   `session.py`, `payload.dict()` becomes `payload.model_dump()`. In `repos.py`, `_now()` becomes
   `datetime.now(UTC).replace(tzinfo=None)`, which stores identical text and removes the
   `utcnow` deprecation. Touched files must import and run with no `DeprecationWarning`.
2. **Status.** `MessageStatus(StrEnum)` lives in `app/type_defs.py` with members `QUEUED="queued"`,
   `RUNNING="running"`, `COMPLETED="completed"`, `ERROR="error"`, `CANCELLED="cancelled"`.
   `MessageResp.status`, `MessageStatusResp.status` and the new `MessageAcceptedResp.status`
   use it. `inference_service.py` and `ws.py` (`TERMINAL_STATUSES`) use its members. The
   Protocol keeps `status: str`. SQL literals in `repos.py` and `"completed"` in
   `prompt_builders.py` MAY stay, because the values are equal. A test pins the value set.
3. **Sessions.** The Protocol gains `list_sessions() -> list[dict]`, which returns
   `[{"id", "created_at"}]` with naive-UTC `datetime`s, newest first (`ORDER BY created_at
   DESC, rowid DESC`). It also gains `delete_session(session_id) -> None`, which deletes
   messages then the session in one transaction and raises `KeyError` if the session is
   unknown. The routes, all with `require_local_token` like the message routes:
   - `GET /api/v1/sessions` returns 200 `{"sessions": [SessionResp]}`.
   - `GET /api/v1/sessions/{session_id}` returns 200 `SessionResp`.
   - `DELETE /api/v1/sessions/{session_id}` returns 204 with an empty body.
   `SessionResp` is `{session_id: str, created_at: UtcDatetime}`. Existence is checked with
   `store.get_session(id) is None`, which gives 404 `{"detail": "Session not found"}`
   (PAT-ARCH-001 rule 5). GET-one reads `created_at` from `list_sessions()`. Path parameters
   stay `str`, so any unknown or malformed id gives 404, not 422 (matches existing tests).
   `test_session_store_protocol_unchanged` is updated to eight names. After a delete, worker
   writes for that session's in-flight jobs raise `KeyError`. The worker's existing
   `try`/`logger.exception` logs them (fail loudly, PAT-ARCH-001 rule 6). An open WS on a
   deleted session closes with 1011 at its next `user_message`.
4. **List messages.** `GET .../messages` returns `{"messages": [MessageResp]}`.
   `MessageListResp` is trimmed to `messages` only. The routes `post_message` (202, and 200 on
   an idempotent replay) and `get_message_status` get response models:
   `MessageAcceptedResp{message_id, status, queue_position: int | None}` and the existing
   `MessageStatusResp`.
5. **Errors.** Every non-2xx REST or `/intel` body is `{"detail": "<string>"}`, raised through
   `HTTPException`. The exception is request validation (422), which keeps FastAPI's
   `{"detail": [{loc, msg, type, ...}]}`. `ErrorResp{detail: str}` is declared through
   `responses=` for OpenAPI. `/intel/tools/{name}/invoke` keeps its status codes (404, 400,
   502, 500) but returns `{"detail": msg}`. `_tool_error` is deleted. `ToolInvokeResp`
   becomes `{text: str, meta: dict}` (`error` removed). The 429 branch,
   `MAX_QUEUE_RETRY_AFTER`, `MAX_INPUT_TOKENS` and the duplicate `router =` (session.py:22)
   are deleted. On `queued=False`, `submit_user_message` sets the message to `error` with
   `meta.error = "enqueue failed"` and returns the updated copy. REST then returns 503
   `{"detail": "Inference queue unavailable"}`, and WS sends
   `{"type": "error", "message": "Inference queue unavailable", "message_id"}`.
6. **Datetimes.** `UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]` lives in
   `app/schemas/v1.py`. It attaches `UTC` to naive values and converts aware values to UTC.
   Pydantic v2 emits ISO 8601 with offset 0 (`2026-10-11T23:20:20.924000Z`). It is used for
   `MessageResp.created_at` and `updated_at` (now required; both columns are NOT NULL),
   `SessionResp.created_at`, and `SessionSnapshotResp.snapshot_at`. `snapshot_at` becomes a
   UTC datetime instead of an epoch float, and `build_snapshot` uses `datetime.now(UTC)`. WS
   `entry` and `snapshot` events are built from `MessageResp` / `SessionSnapshotResp`
   `.model_dump(mode="json")` and then passed to `ws_send` (which still applies
   `jsonable_encoder`, PAT-ARCH-001 rule 7). Storage stays naive-UTC ISO TEXT (ADR-0003).
7. **Length limit.** `MAX_MESSAGE_CHARS = 4096` lives in `app/services/messages.py`.
   `submit_user_message` raises `MessageTooLongError(ValueError)` before any idempotency
   lookup, write or enqueue. `MessageCreateReq.content` uses `Field(min_length=1,
   max_length=MAX_MESSAGE_CHARS)`, so REST answers 422 and OpenAPI shows `maxLength: 4096`.
   WS catches `MessageTooLongError` and sends `{"type": "error", "message": "Message too long
   (max 4096 characters)"}`. Nothing is stored and the socket stays open.
8. **WS contract.** It is documented in `docs/api/websocket.md`, with no code models:
   - Connect: `/api/v1/ws/sessions/{session_id}`. An unknown session closes with 1008 before
     accept; a server error closes with 1011.
   - Client sends `{"action": "user_message", "text": str (1..4096), "client_message_id"?:
     str}` or `{"action": "status"}`.
   - Server sends `snapshot{type, session_id, entries: [MessageResp], snapshot_at}`,
     `entry{type, entry: MessageResp}`, `done{type, message_id, reply_id}`,
     `status{type, queue_position, estimated_wait_seconds}` and
     `error{type, message, message_id?}`.
   - It records the order `entry`(user) -> `entry`(reply) -> `done` or `error`, and states
     that there is no token streaming (REQ-0007).
9. **OpenAPI snapshot.** `docs/api/openapi.json` is written as `json.dumps(app.openapi(),
   indent=2, sort_keys=True) + "\n"`. `tests/test_openapi_snapshot.py` builds the app with
   `FakeInference` and `SqliteSessionStore(":memory:")` and asserts
   `json.loads(file) == json.loads(json.dumps(app.openapi()))`. Regenerate with
   `UPDATE_OPENAPI_SNAPSHOT=1 ./venv-dnd-server/bin/python -m pytest
   tests/test_openapi_snapshot.py`, which rewrites the file and passes. This command is
   documented in `docs/api/websocket.md`'s header and in `.github/copilot-instructions.md` Dev
   workflow. No new dependency.

Traded away: a machine-readable error `code` (C2/C3); a string-only 422 `detail`;
pagination fields; 429 backpressure (G2); recoverable deletes (H2); a runtime-configurable
limit (F3); and 16 KB messages (F2).

## Consequences
- Positive: one error key, one item shape and one timestamp format on every transport. The
  list endpoints are extensible without breaking clients. The status vocabulary is named in
  OpenAPI. There is one limit, which WS now enforces too. Contract drift fails CI. No
  dependency and no storage change. `config.py` and `factory.py` are untouched.
- Negative (breaking now, while no consumer exists): list-messages wraps its list; tool-invoke
  errors lose `error`/`text`/`meta`; the REST too-long error moves from 400 to 422;
  `snapshot_at` changes from float to string; 429 becomes 503. Existing tests in
  `test_session_rest.py`, `test_ws_session.py`, `test_intel_snapshot.py`,
  `test_messages_helper.py`, `test_tool_calling.py` and `test_single_session_model.py` change.
- Risks accepted: unhandled exceptions still return Starlette's plain-text 500. Deleting a
  session with in-flight jobs logs worker `KeyError`s. A message that fails `enqueue` cannot be
  retried with the same `client_message_id`, because the idempotent replay returns the `error`
  message. The seed session id `"demo"` is not a uuid (PAT-ARCH-001 rule 1); that belongs to
  REQ-0012. `SessionCreateResp.capabilities.streaming` still says `true` (gate).

## Pattern Impact
- **Creates** [PAT-ARCH-005](../patterns/architecture/PAT-ARCH-005-http-api-contract.md)
  (`proposed`): the API contract conventions above.
- **Uses without change:** PAT-ARCH-001 (Protocol extension is what its Consequences
  prescribe; rules 5 and 7 are kept), PAT-ARCH-002 (naive ISO TEXT, `KeyError`, one
  transaction), PAT-ARCH-003 (store dicts unchanged), PAT-CODE-001, ADR-0002, ADR-0003.
- **Requires human sign-off (flagged, not applied):**
  1. PAT-ARCH-004 rule 5, last sentence: replace "The error message goes in
     `ToolInvokeResp.error`." with "The error body is `{"detail": msg}` (PAT-ARCH-005);
     `ToolInvokeResp` is `{text, meta}`."
  2. ADR-0004 Decision Outcome item 7: the body shape "Each error status carries
     `ToolInvokeResp(error=msg)`" is superseded by ADR-0005 item 5. The status codes are kept.
     Proposed handling: when ADR-0005 is accepted, add a one-line note to ADR-0004 that
     item 7's body shape is superseded by ADR-0005. Do not set `superseded_by`, because the
     rest of ADR-0004 stands.
- Informational (no sign-off needed): ADR-0003 section 2 says the Protocol "keeps its six
  method names". That described REQ-0005's change, not a standing rule. Widening the
  Protocol now is this ADR's decision, and the guard test is updated with it.
