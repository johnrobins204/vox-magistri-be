---
id: ADR-0002
status: accepted
date: 2026-10-11
requirement: REQ-0004
supersedes: null
superseded_by: null
---

# One session model: uuid session ids and the `SessionStore` Protocol for every transport

## Context
REQ-0004 (see [docs/requirements/LOG.md](../requirements/LOG.md)) requires exactly one
session model: uuid-string ids on REST, WebSocket and `/api/v1/intel/.../snapshot`, one
store API that really persists and returns entries, one WebSocket endpoint, and a
recorded decision on `SessionService`, `GameService` and the duplicate in-memory repos.
Two session models coexist today. Facts below were verified against the tree on 2026-10-11.

**Model 1 - REST (live and correct).** [app/api/v1/session.py](../../app/api/v1/session.py)
creates `str(uuid4())` sessions in `InMemorySessionStore`
([app/services/repos.py](../../app/services/repos.py)) through the `SessionStore` Protocol
in [app/type_defs.py](../../app/type_defs.py). `post_message` stores a user message, calls
`inference.enqueue(...)`, and the worker thread
([inference_service.py](../../app/services/inference_service.py), `_append_reply`) stores
the reply as a separate `role='assistant'` message with `meta.reply_to` (REQ-0003, done).

**Model 2 - WS and `/intel` (broken).** [ws.py](../../app/api/v1/ws.py)
(`/api/v1/ws/sessions/{run_id: int}`) and [intelligence.py](../../app/api/v1/intelligence.py)
(`/api/v1/intel/sessions/{run_id: int}/snapshot`) build
`SessionService(repos={"session": session_store})` per call.
[session_service.py](../../app/services/session_service.py) probes the store with
`hasattr(repo, "append_entry")` / `hasattr(repo, "list_entries")`.
`InMemorySessionStore` has neither, so `append_entry` falls through to a *private*
`_InMemorySessionRepo` that exists only on that short-lived `SessionService` instance.
Result: WS entries are never persisted and every snapshot is empty. This is a silent
no-op by construction, not a one-line bug. The snapshot schema also bakes in the int
model: `SessionEntry.id/run_id: int` and `SessionSnapshotResp.run_id: int`
([app/schemas/v1.py](../../app/schemas/v1.py)).

**Second WebSocket.** `session.py` defines `@router.websocket("/stream")`
(`/api/v1/stream`), which duplicates `ws.py`. It calls `generate_tokens` directly,
bypassing the FIFO queue and the REQ-0003 reply storage.

**Duplicate in-memory repos.** Verified inventory (the brief listed `app/data/repos.py`;
the file is actually repo-root `data/repos.py`, a different package from `app/`):

| # | Location | Shape | Reachable from running app? |
|---|---|---|---|
| 1 | `app/services/repos.py` `InMemorySessionStore` | uuid str -> message list; implements the Protocol | Yes - the only live store (`DEFAULT_REPOS`, `make_default_repos`, tests) |
| 2 | `app/services/session_service.py` `_InMemorySessionRepo` | int run ids, `append_entry/list_entries` | Only as the silent fallback described above |
| 3 | `app/services/game_service.py` `_InMemorySessionRepo` (+ `_InMemoryGameRepo`) | int run ids, game CRUD | No. `GameService()` is constructed in `build_services` and stored under `services["game"]`; no router, dependency getter or test reads it |
| 4 | `data/repos.py` `InMemorySessionRepo` (+ Character/Quest/Game repos) | int ids | No. Nothing under `app/` imports `data`, and `data/__init__.py` uses `from ...data import` so `import data` fails (REQ-0005 territory) |

Related patterns: [PAT-CODE-001](../patterns/code/PAT-CODE-001-centralized-logging.md)
(accepted; new code uses `get_logger(__name__)`). No `accepted` architecture pattern is
affected. The service-locator DI in [deps.py](../../app/deps.py) is used as-is. New
proposed pattern: [PAT-ARCH-001](../patterns/architecture/PAT-ARCH-001-session-store-single-api.md).

Scope guard (from the requirement): persistence is REQ-0005, prompt pipeline REQ-0006,
streaming rework REQ-0007, tools REQ-0008, auth/CORS REQ-0009, schema/contract cleanup
REQ-0010, repo hygiene REQ-0012. This decision does not do those.

## Decision Drivers
| Dimension | Weight | Why it matters here |
|---|---|---|
| Simplicity / smallest-edit fit | High (3) | constraints.md standing constraint 1; solo, part-time |
| Reversibility | High (3) | Low stakes. All state is in memory, so there is no data migration either way |
| Maintainability for one part-time person | High (3) | The dual model already produced a silent failure that went unnoticed |
| Reuse of existing patterns/dependencies | Medium (2) | The Protocol, the REQ-0003 worker path and service-locator DI already exist |
| Fun / learning value | Medium (2) | constraints.md standing constraint 5 |
| Performance / scalability | Low (1) | Explicitly de-prioritized; one user, in-memory |
| Security hardening beyond sane defaults | Low (1) | No production intent; auth is REQ-0009 |
| **Requirement compliance** (added) | High (3) | REQ-0004 is explicit about the MUSTs: uuid everywhere, one store API, one WS, no silent no-ops. Constraint 1 permits a broader change when it *is* the requirement |
| **Forward fit with REQ-0005 / REQ-0007** (added) | Medium (2) | REQ-0005 will put another store behind the Protocol and REQ-0007 will rework streaming. Options that widen the Protocol or add parallel APIs make that harder. Not High because those REQs will re-decide anyway |

## Considered Options
1. **A - Delete the second model; port WS and `/intel` to the existing Protocol; add one
   small shared "submit a user message" helper used by REST and WS.** The Protocol is
   *not* extended: `create_message`, `get_session`, `list_messages` already persist and
   return everything needed.
2. **B - Keep `SessionService` as a facade over the store**, rewritten to use uuid
   session ids and to translate entries to and from messages. Keep `GameService`.
3. **C - Status quo plus minimal patch**: add `append_entry`/`list_entries` to
   `InMemorySessionStore`, keep integer `run_id` on WS and `/intel`, keep `/stream`.
4. **D - Extend the `SessionStore` Protocol with `append_entry`/`list_entries`** (the
   brief's literal option A), switch WS and `/intel` to uuid ids, and delete
   `SessionService`/`GameService`. REST keeps `create_message`.
5. **E - Like A, but the shared logic lives in a new `ConversationService` class** wired
   through `build_services` and a `deps.py` getter.

## Rubric Scoring
Scores are 1 (poor) to 5 (strong). Weighted total = sum of (score x weight). Maximum is 100.

| Option | Simplicity (3) | Reversibility (3) | Maintainability (3) | Reuse (2) | Fun / learning (2) | Performance (1) | Security / hygiene (1) | Requirement compliance (3) | Forward fit REQ-0005/0007 (2) | Weighted Total |
|---|---|---|---|---|---|---|---|---|---|---|
| **A** - Delete model 2, port to existing Protocol, shared helper | 4: net deletion of roughly 350 lines (`session_service.py`, `game_service.py`); `ws.py` rewrite, about 10 lines in `intelligence.py`, a schema tweak and one small helper; no Protocol change | 4: deletions recoverable from git; nothing persisted yet, so no migration | 5: one id type, one store API, one WS; transports become thin adapters | 5: uses the six existing Protocol methods, the REQ-0003 worker and service-locator DI unchanged | 3: some async/WS learning, no new design to play with | 3: 0.25 s poll in WS is irrelevant at this scale | 3: neutral; auth stays REQ-0009 | 5: meets every MUST, and removes unused duplicates (SHOULD) | 5: Protocol surface unchanged, so REQ-0005 implements the same six methods | **86** |
| **B** - `SessionService` facade, uuid ids | 3: no deletions; the class must be rewritten, and `ensure_active`/`end_run`/`get_active` (game/run semantics) have no meaning for uuid sessions | 4: easy to revert | 2: a second vocabulary (`append_entry`, `snapshot_run`) over `create_message`/`list_messages` plus an entry<->message translator, which is the layer that already failed silently | 3: reuses the class but not the Protocol directly | 2: keeps old code alive | 3: neutral | 3: neutral | 3: can satisfy the MUSTs, but "one store API" is arguable and duplicates stay (SHOULD missed) | 3: REQ-0005 unaffected if the facade only calls the Protocol, but the facade must be maintained | **58** |
| **C** - Minimal patch, keep int `run_id` | 5: about 20 lines | 5: trivial | 1: int and uuid keys mixed in one dict, two entry shapes, two WS endpoints, `SessionService` still wraps the store | 2: keeps the divergence | 1: no learning | 3: neutral | 3: neutral | 1: violates the uuid MUST and the one-WS MUST; REST-created sessions are invisible to WS and `/intel`, so the "reflect REST messages" MUST fails | 1: REQ-0005 would have to persist two id models and widen the Protocol | **50** (non-compliant) |
| **D** - Extend Protocol with `append_entry`/`list_entries` | 3: Protocol, `InMemorySessionStore` and an entry<->message mapping all change, plus the same deletions as A | 3: every future Protocol implementer (REQ-0005) inherits the extra methods | 2: two write APIs on one store with different shapes (`create_message` vs `append_entry`); someone must choose the canonical shape | 3: reuses the Protocol idea but grows it | 2: little new | 3: neutral | 3: neutral | 4: meets the MUSTs, though "one store API" is muddied | 2: REQ-0005 must implement and persist both entry APIs | **56** |
| **E** - Delete model 2, new `ConversationService` class | 3: A plus a class, a `deps.py` getter, a `build_services` key and fixture changes for a single orchestration function | 4: reversible | 4: one orchestration home, but an extra layer for one person | 4: uses the Protocol, follows service-locator DI, adds plumbing | 4: nice design exercise | 3: neutral | 3: neutral | 5: meets every MUST | 4: gives REQ-0006/0007 a natural home, but speculative today | **78** |

Totals check (weights 3,3,3,2,2,1,1,3,2):
A = 12+12+15+10+6+3+3+15+10 = 86; E = 9+12+12+8+8+3+3+15+8 = 78;
B = 9+12+6+6+4+3+3+9+6 = 58; D = 9+9+6+6+4+3+3+12+4 = 56; C = 15+15+3+4+2+3+3+3+2 = 50.

Option A wins (86, versus 78 for E, 58 for B, 56 for D and 50 for C). A and E differ
only by function versus class; the extra layer in E is not justified yet (see Traded away).

## Decision Outcome
Choose **Option A**.

**1. One session model.** A session id is a uuid string everywhere.
- REST is unchanged.
- WebSocket: `/api/v1/ws/sessions/{session_id}` (path param is `str`). The route stays
  in `ws.py`.
- Snapshot: `GET /api/v1/intel/sessions/{session_id}/snapshot`. The **URL path param is
  renamed** from `run_id` to `session_id`. The wire URL shape is unchanged; only the
  FastAPI parameter name and the generated OpenAPI change. The response field
  `run_id: int` is renamed to `session_id: str`.
- Unknown session: both transports use REST's rule (`store.get_session(id) is None`).
  Snapshot returns 404; the WS closes with code 1008 before `accept()`. Sessions are
  created only through `POST /api/v1/sessions` (and `seed_sample_data`). Neither
  transport auto-creates a session (the old WS implicitly "created" any integer).

**2. One store API: the existing `SessionStore` Protocol, unchanged.** No
`append_entry`/`list_entries`. The "persist and return entries" MUST is met by
`create_message`/`get_session`/`list_messages`, which already work (REST proves it). The
silent no-op came from `SessionService`'s `hasattr` probing, so removing that layer
removes the failure mode. Nothing may probe the store with `hasattr`/`try-except` to
fall back to a private store (see PAT-ARCH-001).

**3. Fate of each component** (REQ-0012 and REQ-0005 depend on this table):

| Component | Decision | Reason |
|---|---|---|
| `app/services/session_service.py` (`SessionService` and its `_InMemorySessionRepo`) | **Delete** | Sole cause of the silent no-op; int run/game semantics (`ensure_active`, `end_run`, `snapshot_run`) have no meaning with uuid sessions; only callers are `ws.py` and `intelligence.py`, which are ported. Its `invoke_tool_and_record` idea belongs to REQ-0008 (slash-command dispatch) and should be rebuilt on the store there |
| `app/services/game_service.py` (`GameService`, `_InMemoryGameRepo`, `_InMemorySessionRepo`) | **Delete**, and remove its import and the `"game"` key from `build_services` | No router, dependency getter or test uses it. The campaign/game domain is REQ-0015, which will design what it needs against REQ-0005 storage. Recoverable from git |
| `app/services/repos.py` `InMemorySessionStore` (+ `DEFAULT_REPOS`, `make_default_repos`, `seed_sample_data`) | **Survives as the only in-memory session store** | It implements the Protocol and is what REST, tests and `main.py` use. REQ-0005 may replace the implementation behind the same Protocol; the module's public names should not change in this REQ |
| `data/repos.py` (repo-root, not `app/data/`) | **Not touched by REQ-0004; decision deferred to REQ-0005** | It sits inside the `data/` package REQ-0005 owns (the package does not import today), nothing in `app/` imports it, and the requirement forbids changing the persistence/data layer here. It is not part of the live session model. REQ-0012 MAY delete it only after REQ-0005 decides the fate of `data/` |

So after REQ-0004 the only in-memory session repo wired into the app is
`app/services/repos.py`. REQ-0012 should not count the other three as survivors.

**4. One WebSocket endpoint.** Keep `ws.py`. **Remove** `@router.websocket("/stream")`
from `session.py` (and its now-unused `Header`/`WebSocket` imports). It is removed, not
merged, because `ws.py` already has the richer action set and `/stream`'s only unique
parts are its Authorization-header check (REQ-0009 owns WS auth) and `cancel` (see
Consequences).

**5. WS message handling reuses the REST path (store plus worker) without the REQ-0007
rework.**
- Add one small shared helper (proposed home `app/services/messages.py`, name for the
  spec writer to finalize) that, given `store`, `inference`, `session_id` and a payload
  dict, does what `post_message` does after its HTTP-only checks: apply
  `client_message_id` idempotency via `get_by_client_id`, create the user message with a
  `str(uuid4())` id, call `inference.enqueue(...)`, and return `(message, created,
  queued)`. It has two concrete call sites on day one (REST `post_message`, WS
  `user_message`), which meets constraint 2. REST keeps its HTTP-specific concerns
  (length check, 202/200/429 mapping, `Location` header).
- WS `user_message` calls that helper. Because the existing worker produces the reply,
  the WS automatically gets REQ-0003 semantics (user message, then a separate
  `role='assistant'` message with `meta.reply_to`) with no duplicated reply logic. WS
  also goes through the FIFO queue, which ends the REST-vs-WS concurrent-Ollama race
  that `generate_tokens` caused.
- The WS handler then sends `{"type":"entry","entry":<user message>}`, waits for the
  worker by polling the user message's `status` in the store (`asyncio.sleep`, short
  interval, bounded) until `completed`/`error`/`cancelled`, then sends the reply
  message as `{"type":"entry",...}` followed by `{"type":"done","message_id":<user id>,
  "reply_id":<reply id>}`; on `error` it sends `{"type":"error",...}` with
  `meta.error`. On connect it still sends `{"type":"snapshot","session_id","entries",
  "snapshot_at"}`, now read from the store. The `status` action stays.
- Out of scope, and left alone: real token streaming and `generate_tokens` (still in
  `inference_service.py` but no longer called by any transport), the WS event protocol
  document, cancel mid-stream, and non-blocking I/O. These stay with REQ-0007.

**6. Snapshot schema (minimum change, REQ-0010 owns the cleanup).**
`SessionSnapshotResp` becomes `{session_id: str, entries: list[MessageResp],
snapshot_at: float}`. Entries are the same message shape REST returns, so REST, WS and
`/intel` show one entry shape. `SessionEntry` (int `id`/`run_id`) is deleted.

Traded away:
- A `ConversationService` class (Option E). If REQ-0006 (history window, system
  prompt) or REQ-0007 needs a richer orchestrator, promote the helper then; the helper
  has a single signature, so that move is cheap.
- The WS `token` event and in-WS `cancel` action. The reply arrives as one `entry` plus
  `done`. There is no frontend in this repo yet (REQ-0016/0017), so nothing consumes the
  old events.
- The snapshot JSON field `run_id` and the lenient "unknown int id returns an empty
  snapshot" behavior. Both were part of the broken model.

## Consequences
- Positive: one id type, one store API, one WS endpoint; the snapshot reflects REST and
  WS messages because everything reads the same store; roughly 350 lines of dead,
  misleading code removed; REQ-0005 only has to satisfy the six existing Protocol
  methods; `build_services` and the Protocol get simpler.
- Negative: breaking JSON change on `/intel/.../snapshot` (`run_id` -> `session_id`,
  entry shape) and on the WS (`token` removed, `entry`/`done` semantics changed). The
  snapshot of an unknown session is now 404 instead of 200 empty. In-WS cancel is lost.
  The WS handler waits for the worker inline, so it cannot read another client action
  (for example `status`) while one reply is pending.
- Follow-up work or risks accepted (feed these to the spec writer):
  - **WS JSON serialization.** Store messages carry `datetime` `created_at/updated_at`
    ([repos.py](../../app/services/repos.py)); `ws.send_json` will raise on them, and
    the current `ws_send` swallows every exception with `pass`. That would recreate the
    same silent failure class as this REQ. Use `fastapi.encoders.jsonable_encoder` for
    payloads, and limit the swallow to disconnects; log other failures through
    `get_logger`.
  - **Live-list coupling.** `inference_service._update_message_status` mutates the dicts
    returned by `store.get_session(...)`; correctness relies on that list being live.
    This works for `InMemorySessionStore` but is an implicit contract REQ-0005 must
    keep or replace (for example with `update_message_status`/`update_message_meta`
    store methods). Snapshot/WS should return copies, not the live list.
  - **Thread safety.** The worker thread mutates the store while async handlers read
    it. `InMemorySessionStore` has no lock; this is the same exposure REST has today
    (CPython list append/dict set are atomic), so no new risk, but it is not fixed here.
  - **Bounded wait.** The WS poll MUST have a timeout (settings `ollama.timeout_seconds`
    plus margin) so a dead worker cannot hang a connection forever.
  - **Auth.** After `/stream` is removed, no WS checks `Authorization`. `ws.py` never
    did, so exposure is unchanged. REQ-0009 designs WS auth; `inference.validate_token`
    becomes unused until then.
  - **Docs.** [.github/copilot-instructions.md](../../.github/copilot-instructions.md)
    still lists `game` in `build_services` and describes `repos.py` as the active layer;
    the cleanup/REQ-0014 step should refresh it. Do not touch `data/` or the ORM layer.
  - **Tests** (no network/Ollama): reuse the `OllamaInferenceService` + monkeypatched
    `client.generate` pattern from `tests/test_inference_reply.py`; build the app with
    `create_app(services={"inference": svc, "session": store})`. Cover: REST post ->
    snapshot shows user and reply; WS send -> REST list shows user and assistant with
    `meta.reply_to`; unknown id (including a plain integer such as `1`) -> 404 / WS
    close, with no int coercion; `/api/v1/stream` no longer connects; `build_services`
    has no `game` key; `SessionService`/`GameService` are not importable.
    `test_tool_calling.py` keeps using `make_default_repos` and `services["tool"]`, so
    those must not change.

## Pattern Impact
- Creates: [PAT-ARCH-001](../patterns/architecture/PAT-ARCH-001-session-store-single-api.md)
  (architecture, `status: accepted`): "One session store API; transports are thin
  adapters". Accepted by the human on 2026-10-11.
- Uses: PAT-CODE-001 (accepted) for logging. No change requested.
- Changes to accepted patterns: none.
