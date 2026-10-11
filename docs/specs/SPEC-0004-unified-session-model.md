---
id: SPEC-0004
requirement: REQ-0004
adr: ADR-0002
status: draft
date: 2026-10-11
---

# One Session Model: uuid Session Ids and the `SessionStore` Protocol on Every Transport

## 1. Requirement
> There MUST be exactly one session model: session ids MUST be uuid strings on REST,
> WebSocket and `/api/v1/intel/sessions/{id}/snapshot` (integer `run_id` MUST NOT
> remain); there MUST be one session-store API (the `SessionStore` Protocol) that every
> transport uses and that MUST actually persist and return entries (no silent no-ops);
> there MUST be exactly one WebSocket endpoint, and messages sent over it MUST be stored
> via the same store as REST (including REQ-0003 semantics: user message plus separate
> `role='assistant'` message with `meta.reply_to`); the `/intel` snapshot MUST read from
> that same store and reflect messages created via REST or WS; the duplicate
> `/api/v1/stream` endpoint MUST be removed; the fate of `SessionService`, `GameService`
> and duplicate in-memory repos MUST be decided and recorded (ADR-0002), unused
> duplicates SHOULD be removed; tests MUST run without network or Ollama.
> Out of scope: REQ-0005 persistence/data layer (`data/repos.py` untouched), REQ-0006
> prompts, REQ-0007 streaming/cancel/WS event protocol, REQ-0008 tools, REQ-0009
> auth/CORS, REQ-0010 schema cleanup, REQ-0012 hygiene. (REQ-0004)

Linked ADR: [ADR-0002](../adr/0002-single-session-model.md) (status: accepted), Option A.
Linked pattern: [PAT-ARCH-001](../patterns/architecture/PAT-ARCH-001-session-store-single-api.md)
(accepted).

Decisions taken from ADR-0002 that this spec implements:
- uuid string session id everywhere. WS route `/api/v1/ws/sessions/{session_id}`;
  snapshot route `/api/v1/intel/sessions/{session_id}/snapshot` (param renamed from
  `run_id`). `SessionSnapshotResp` becomes `{session_id: str, entries:
  list[MessageResp], snapshot_at: float}`. `SessionEntry` is deleted.
- Unknown session: snapshot returns 404; WS closes with code 1008 before `accept()`.
  Nothing auto-creates a session. A plain integer such as `1` is just an unknown string
  id (no int coercion).
- `app/services/session_service.py` and `app/services/game_service.py` are deleted; the
  `GameService` import and the `"game"` key are removed from `build_services`.
  `app/services/repos.py` stays the only in-memory store (names `InMemorySessionStore`,
  `DEFAULT_REPOS`, `make_default_repos`, `seed_sample_data` stay stable). Repo-root
  `data/repos.py` is NOT touched (REQ-0005). The `SessionStore` Protocol in
  `app/type_defs.py` is NOT changed.
- `@router.websocket("/stream")` (`/api/v1/stream`) is removed from `session.py`,
  together with the `Header` and `WebSocket` imports that become unused.
- One shared helper module `app/services/messages.py` is used by REST `post_message` and
  WS `user_message`. The inference worker writes the reply (REQ-0003); the WS only reads
  it back from the store. No streaming rework: the WS `token` event and the in-WS
  `cancel` action are dropped (REQ-0007).

Verified facts this spec relies on (checked against the tree on 2026-10-11):
- `app/api/v1/ws.py` currently has `router = APIRouter(prefix="/api/v1/ws", ...)`, a
  `ws_send(ws, payload)` helper that swallows every exception, and
  `@router.websocket("/sessions/{run_id}")` with `run_id: int` that builds
  `SessionService(repos={"session": session_store})` per connection and streams via
  `inference.generate_tokens`.
- `app/api/v1/intelligence.py` imports `SessionService` and has
  `@router.get("/sessions/{run_id}/snapshot", response_model=SessionSnapshotResp)` with
  `run_id: int`. Its other routes (`/tools`, `/tools/{tool_name}/invoke`, `/status`) are
  unrelated and MUST NOT change.
- `app/api/v1/session.py` imports `Annotated, Any`, `uuid4`, `APIRouter, Depends,
  Header, HTTPException, Response, WebSocket, status`, `JSONResponse`, and defines
  `MAX_INPUT_TOKENS = 1024`, `MAX_QUEUE_RETRY_AFTER = 5`. `post_message` does: session
  existence check (404), length check `len(payload.content) > MAX_INPUT_TOKENS * 4`
  (400), idempotency via `store.get_by_client_id` (200 `{"message_id", "status"}`),
  `message_id = str(uuid4())`, `store.create_message(session_id, message_id,
  payload.dict())`, `inference.enqueue(session_id=..., message_id=..., prompt=
  payload.content, store=store)`, 429 with `Retry-After` when not queued, otherwise sets
  the `Location` header and returns `{"message_id", "status": "queued",
  "queue_position"}`. `Header` and `WebSocket` are used only by `stream_ws`.
  `create_session` still needs `uuid4`.
- `app/schemas/v1.py` defines `MessageResp` (fields `id, client_message_id, role,
  content, status, meta, created_at, updated_at`), `SessionEntry` (int `id`, int
  `run_id`) and `SessionSnapshotResp` (`run_id: int`, `entries: list[SessionEntry]`,
  `snapshot_at: float`). The project runs pydantic 2.x with v1-style `Config` classes;
  leave that style alone (REQ-0010).
- `app/services/repos.py` `InMemorySessionStore`: `get_session` and `list_messages`
  return the LIVE list (or `None` / `[]` for unknown); `create_message` hard-codes
  `status="queued"` and stores `datetime` values in `created_at`/`updated_at`;
  `create_session` is `store._sessions[id] = []`.
- `app/services/inference_service.py` `OllamaInferenceService`: `enqueue(*, session_id,
  message_id, prompt, store) -> bool`; the worker sets the user message status
  `running`, calls `self.client.generate(prompt)`, calls `_append_reply` (creates a
  separate `role='assistant'` message with `meta == {"reply_to": <user id>}`, status
  `completed`) and THEN sets the user message status `completed`; on exception it sets
  the user message `error` and `meta["error"]`; a pre-cancelled job ends `cancelled`.
  Statuses are exactly `queued/running/completed/error/cancelled`. `task_done()` runs in
  a `finally`, so `svc._queue.unfinished_tasks == 0` means the worker is idle.
- `app/services/build_services.py` imports `GameService` and returns `{"session",
  "tool", "game", "inference"}`.
- `app/deps.py` getters: `get_inference_service`, `get_session_store`,
  `get_tool_service`; `require_local_token` only checks for an `Authorization` header
  starting with `Bearer ` (REST message routes use it; snapshot and WS do not and that
  does not change here).
- `tests/conftest.py` defines fixtures `app` and `client` (real `build_services`); they
  stay unchanged. `tests/test_tool_calling.py` uses `make_default_repos()` and
  `services["tool"]`. `tests/test_inference_reply.py` shows the stub pattern
  (`monkeypatch.setattr(svc.client, "generate", ...)`). `tests/__init__.py` exists, so
  `from tests.<module> import ...` works. `pyproject.toml` has `asyncio_mode = "auto"`.
- `fastapi==0.141.1`, `starlette==1.7.0`, `pydantic==2.13.5` (requirements.txt).
  `fastapi.encoders.jsonable_encoder` and `fastapi.routing.APIWebSocketRoute` exist.

## 2. Test Spec
Written before any work package. "Done" means all of the following pass with
`./venv-dnd-server/bin/python -m pytest`. No test opens a network connection or needs
Ollama: the inference service is either `OllamaInferenceService` with a monkeypatched
`client.generate` (constructing it connects to nothing) or a `FakeInference` object.

### Shared test support (created by WP-1; used by all test files)
`tests/session_helpers.py` (new, plain module, no fixtures):
- `AUTH = {"Authorization": "Bearer test"}` (REST message routes need the header).
- `make_stub_service()`: builds `OllamaInferenceService(types.SimpleNamespace(
  ollama=types.SimpleNamespace(base_url="http://127.0.0.1:1", model="stub",
  timeout_seconds=1.0)))`.
- `wait_idle(svc, timeout=5.0)`: polls `svc._queue.unfinished_tasks == 0`, sleeping
  `0.01` s, `pytest.fail(...)` on timeout.
- `FakeInference`: constructor `FakeInference(accept=True)`; `.calls` is a list of the
  keyword-arg dicts passed to `enqueue`; `enqueue(*, session_id, message_id, prompt,
  store)` appends to `.calls` and returns `self.accept` (it never touches the store and
  never changes a status, so a WS waiting on it hits the timeout); `queue_position(
  message_id)` returns `0`; `estimate_wait(message_id)` returns `0.0`; `cancel(
  message_id)` returns `True`; `validate_token(token)` returns `True`; `model_loaded =
  True`; `async def shutdown(self)` does nothing.

`tests/conftest.py` gets three ADDED fixtures (existing `app`/`client` untouched):
- `stub_svc`: `make_stub_service()` with `monkeypatch.setattr(svc.client, "generate",
  lambda prompt, **kw: "stub reply")` applied; yields it; teardown
  `asyncio.run(svc.shutdown())`.
- `session_store`: a fresh empty `InMemorySessionStore()` (no sessions).
- `stub_client`: `create_app(services={"inference": stub_svc, "session": session_store})`
  inside `with TestClient(app) as c:`; yields `c`.
Tests override the stub per test with their own `monkeypatch.setattr(stub_svc.client,
"generate", ...)`. Where a test needs a different inference object it builds its own
`create_app(...)`/`TestClient` instead of using `stub_client`.

### `tests/test_messages_helper.py` (unit tests for `app/services/messages.py`)
1. **`test_submit_creates_user_message_and_enqueues`**: store with session `s1`;
   `FakeInference()`; call `submit_user_message(store=..., inference=..., session_id=
   "s1", payload={"client_message_id": None, "role": "user", "content": "hi", "meta":
   None})`. Expect return `(msg, True, True)`; `msg["role"] == "user"`, `msg["content"]
   == "hi"`; `msg["id"]` parses with `uuid.UUID(...)`; the store holds exactly that one
   message; `inference.calls` has exactly one entry with `session_id == "s1"`,
   `message_id == msg["id"]`, `prompt == "hi"`, `store is store`.
2. **`test_submit_idempotent_on_client_message_id`**: submit twice with
   `client_message_id="c1"`. Expect first `(m1, True, True)`, second `(m2, False,
   False)` with `m2["id"] == m1["id"]`; store has 1 message; `inference.calls` has 1
   entry.
3. **`test_submit_reports_queue_full`**: `FakeInference(accept=False)`. Expect
   `(msg, True, False)`; the message IS in the store (REST behaviour is preserved: the
   record stays when the queue is full).
4. **`test_build_snapshot_returns_copies`**: session `s1` with one message whose `meta`
   is `{"k": "v"}`. `snap = build_snapshot(store, "s1")`. Expect `snap["session_id"] ==
   "s1"`, `len(snap["entries"]) == 1`, `isinstance(snap["snapshot_at"], float)`. Then
   mutate `snap["entries"][0]["content"] = "changed"` and
   `snap["entries"][0]["meta"]["k"] = "changed"`, and `snap["entries"].append({})`;
   the store's message is unchanged (content and `meta["k"]`), and
   `len(store.list_messages("s1")) == 1`.
5. **`test_build_snapshot_unknown_session_is_none`**: `build_snapshot(store, "nope")
   is None`, and `build_snapshot(store, "1") is None`; `store.get_session("nope")` is
   still `None` afterwards (no auto-create).

### `tests/test_session_rest.py` (REST regression and `/stream` removal)
6. **`test_rest_post_message_response_shape`**: `stub_client`; `POST /api/v1/sessions`
   (201), then `POST /api/v1/sessions/{sid}/messages` with `AUTH` and JSON `{"content":
   "hello"}`. Expect 202, body keys include `message_id` (uuid string), `status ==
   "queued"`, `queue_position`; header `Location ==
   f"/api/v1/sessions/{sid}/messages/{message_id}"`.
7. **`test_rest_post_message_idempotent`**: post twice with the same
   `client_message_id`. Expect first 202, second 200 with the same `message_id` and a
   `status` key; after `wait_idle(stub_svc)` the session has exactly 2 messages (1 user
   + 1 reply).
8. **`test_rest_post_message_queue_full_returns_429`**: own app with
   `FakeInference(accept=False)` and `session_store`. Expect 429, header `Retry-After
   == "5"`, body `status == "queued_full"`, `retry_after == 5`, `message_id` present.
9. **`test_rest_post_message_too_long_is_400`**: content of `1024 * 4 + 1` (4097)
   characters. Expect 400 and no message stored (`MessageCreateReq.max_length` is
   16384, so the request reaches the handler's own length check).
10. **`test_rest_post_message_unknown_session_is_404`**: `POST
    /api/v1/sessions/nope/messages` with `AUTH`. Expect 404.
11. **`test_stream_endpoint_removed`**: `stub_client.app.routes` contains no route with
    `path == "/api/v1/stream"`; and `with pytest.raises(WebSocketDisconnect): with
    stub_client.websocket_connect("/api/v1/stream"): pass`.

### `tests/test_intel_snapshot.py` (snapshot route and schema)
12. **`test_snapshot_reflects_rest_messages`**: `stub_client`; create session via
    `POST /api/v1/sessions`; `POST` a message (with `AUTH`, content `"hello"`);
    `wait_idle(stub_svc)`; `GET /api/v1/intel/sessions/{sid}/snapshot`. Expect 200,
    `body["session_id"] == sid`, `len(body["entries"]) == 2`; entry 0 has `role ==
    "user"`, `content == "hello"`, `status == "completed"`; entry 1 has `role ==
    "assistant"`, `content == "stub reply"`, `meta["reply_to"] == entry0["id"]`; every
    `id` is a string; `isinstance(body["snapshot_at"], float)`; `"run_id"` is not a key
    of `body`.
13. **`test_snapshot_matches_rest_message_list`**: same setup as 12; the `id` list of
    the snapshot entries equals the `id` list of `GET /api/v1/sessions/{sid}/messages`
    (with `AUTH`).
14. **`test_snapshot_empty_session_is_200_with_no_entries`**: new session, no messages.
    Expect 200, `entries == []`.
15. **`test_snapshot_unknown_session_is_404`**: `GET
    /api/v1/intel/sessions/does-not-exist/snapshot` and `GET
    /api/v1/intel/sessions/1/snapshot` both return 404 (an integer is NOT coerced).
16. **`test_openapi_has_no_integer_session_model`**: `schema = stub_client.get(
    "/openapi.json").json()`; the path `"/api/v1/intel/sessions/{session_id}/snapshot"`
    is in `schema["paths"]`; `"/api/v1/intel/sessions/{run_id}/snapshot"` is not;
    `"SessionEntry"` is not in `schema["components"]["schemas"]`; and the substring
    `"run_id"` does not occur in `json.dumps(schema)`.

### `tests/test_ws_session.py` (the single WebSocket)
Path used everywhere: `/api/v1/ws/sessions/{session_id}`. Sessions are created with
`POST /api/v1/sessions` unless stated.
17. **`test_ws_connect_sends_snapshot_from_store`**: create a session via REST and put
    one message in it with `session_store.create_message(sid, "m1", {"role": "user",
    "content": "hi"})` (this message has `datetime` fields). Connect; first received
    JSON has `type == "snapshot"`, `session_id == sid`, `len(entries) == 1`,
    `entries[0]["id"] == "m1"`, `isinstance(snapshot_at, float)`; it has no `run_id`
    key. (Receiving it at all proves `datetime` values are JSON-encoded.)
18. **`test_ws_user_message_is_stored_with_reply_semantics`**: connect, read the
    snapshot, send `{"action": "user_message", "text": "hello"}`. Expect the next three
    events in order: `{"type": "entry", "entry": <user>}` with `role == "user"`,
    `content == "hello"`; `{"type": "entry", "entry": <reply>}` with `role ==
    "assistant"`, `content == "stub reply"`, `meta["reply_to"] == user["id"]`;
    `{"type": "done", "message_id": user["id"], "reply_id": reply["id"]}`. Then, via
    REST `GET /api/v1/sessions/{sid}/messages` (with `AUTH`): exactly 2 items; item 0
    is the user message (`role == "user"`, `content == "hello"`, `status ==
    "completed"`); item 1 has `role == "assistant"` and `meta["reply_to"] ==
    item0["id"]`; ids equal the ids seen on the WS. Also `GET
    /api/v1/intel/sessions/{sid}/snapshot` lists the same two ids.
19. **`test_ws_sees_messages_created_via_rest`**: post a message over REST, `wait_idle`,
    then connect over WS. The snapshot event has 2 entries with the same ids as the
    REST list.
20. **`test_ws_client_message_id_is_idempotent`**: send `{"action": "user_message",
    "text": "hello", "client_message_id": "c1"}` twice on one connection, consuming
    events each time. Both rounds yield `entry` (user), `entry` (reply), `done`, and the
    user entry id and reply id are identical across rounds. The store ends with exactly
    2 messages, and the stubbed `generate` was called exactly once (use a counting
    stub that increments a list/counter and returns `"stub reply"`).
21. **`test_ws_inference_error_sends_error_event`**: stub `generate` raises
    `RuntimeError("boom")`. Send a `user_message`. Expect an `entry` event (user), then
    `{"type": "error", "message_id": <user id>, "message": "boom"}`. The store has
    exactly 1 message with `status == "error"`. The connection stays usable: sending
    `{"action": "status"}` yields an event with `type == "status"`.
22. **`test_ws_unknown_session_closes_1008`**: for session ids `"does-not-exist"` and
    `"1"`, `with pytest.raises(WebSocketDisconnect) as exc: with
    stub_client.websocket_connect(f"/api/v1/ws/sessions/{id}"): pass`; `exc.value.code
    == 1008`. Afterwards `session_store.get_session(id) is None` (no auto-create).
23. **`test_ws_bad_input_gets_error_event_and_stays_open`**: on a valid session send, in
    turn: `{"action": "nope"}`; `{"action": "user_message", "text": ""}`;
    `{"action": "user_message"}` (no text); `{"action": "user_message", "text": "x",
    "client_message_id": 5}`. Each yields an event with `type == "error"` and a
    non-empty `message`; no message is stored (`session_store.list_messages(sid) == []`);
    then `{"action": "status"}` still yields `type == "status"` on the same connection.
24. **`test_ws_reply_wait_is_bounded`**: own app with `FakeInference()` (accept=True)
    and `session_store`; `monkeypatch.setattr("app.api.v1.ws._reply_timeout_seconds",
    lambda: 0.3)`. Send a `user_message`. Expect an `entry` event (user), then an
    `error` event whose `message` contains `"Timed out"` and whose `message_id` is the
    user id, within a few seconds (the test must not hang; use the TestClient default,
    and the poll interval is 0.05 s). The user message stays in the store with status
    `queued`.
25. **`test_ws_queue_full_sends_error_event`**: own app with `FakeInference(
    accept=False)`. Send a `user_message`. Expect an `entry` event (user) then an
    `error` event whose `message` contains `"queue full"`; the user message is in the
    store.
26. **`test_ws_cancelled_job_sends_error_event`**: the message id is not known before
    the send, so wrap the real `enqueue`: `orig = stub_svc.enqueue`; define
    `def enqueue_cancelled(*, session_id, message_id, prompt, store): stub_svc.cancel(
    message_id); return orig(session_id=session_id, message_id=message_id,
    prompt=prompt, store=store)` and `monkeypatch.setattr(stub_svc, "enqueue",
    enqueue_cancelled)`; make `generate` fail the test (raise `AssertionError`) if
    called. Send a `user_message`. Expect an `entry` event (user), then `{"type":
    "error", "message_id": <user id>, "message": "cancelled"}`; the store has 1
    message with `status == "cancelled"`.
26a. **`test_exactly_one_ws_route`**: the paths of all
    `fastapi.routing.APIWebSocketRoute` instances in `stub_client.app.routes` are
    exactly `["/api/v1/ws/sessions/{session_id}"]`.
27. **`test_ws_send_does_not_swallow_non_disconnect_errors`** (unit test of the
    helper): `from app.api.v1.ws import ws_send`; with a fake socket object whose
    `send_json` is `async` and raises `ValueError("boom")`, `await ws_send(fake,
    {"a": 1})` raises `ValueError`. With a fake `send_json` that records its argument,
    `await ws_send(fake, {"t": datetime(2026, 1, 1)})` passes a payload whose value is
    a `str` (ISO format), proving `jsonable_encoder` is applied.

### `tests/test_single_session_model.py` (deletions and structure)
28. **`test_build_services_has_no_game_key`**: `services = build_services(
    make_default_repos(), enable_tool_discovery=False)`; `set(services) == {"session",
    "tool", "inference"}`; then `asyncio.run(services["inference"].shutdown())`.
29. **`test_removed_modules_are_gone`**: `importlib.import_module(name)` raises
    `ModuleNotFoundError` for `"app.services.session_service"` and
    `"app.services.game_service"`; the two files do not exist on disk.
30. **`test_no_references_to_removed_symbols`**: scanning all `*.py` files under
    `app/`, none contains any of `"SessionService"`, `"GameService"`,
    `"session_service"`, `"game_service"`, `"SessionEntry"`; and none of
    `app/api/v1/*.py`, `app/schemas/v1.py`, `app/services/messages.py` contains
    `"run_id"`; and none of `app/api/v1/ws.py`, `app/api/v1/intelligence.py`,
    `app/api/v1/session.py`, `app/services/messages.py` contains `"hasattr("`
    (PAT-ARCH-001: no capability probing).
31. **`test_default_repos_names_stable`**: `from app.services.repos import
    InMemorySessionStore, DEFAULT_REPOS, make_default_repos, seed_sample_data`
    succeeds; `make_default_repos()["session"]` is an `InMemorySessionStore`;
    after `seed_sample_data(repos)` the `"demo"` session has one message (keeps
    `main.py --seed` working).
32. **`test_session_store_protocol_unchanged`**: the public method names declared on
    `app.type_defs.SessionStore` are exactly `{"get_session", "create_session",
    "create_message", "get_by_client_id", "list_messages", "update_message_status"}`
    (collect with `[n for n in vars(SessionStore) if not n.startswith("_")]`; Protocol
    classes add only underscore names, so this is the six methods).

### Whole suite
33. **Existing suite still passes**: `tests/test_app_factory.py`,
    `tests/test_backlog_schema.py`, `tests/test_inference_reply.py`,
    `tests/test_logging_consistency.py`, `tests/test_tool_calling.py` and
    `./venv-dnd-server/bin/python -m ruff check app tests` /
    `./venv-dnd-server/bin/python -m black --check app tests` are clean after each
    work package.

## 3. Work Packages
Execute in order: WP-1 first; WP-2, WP-3 and WP-4 each need only WP-1 (WP-2 and WP-3
are independent of each other and of WP-4); WP-5 needs WP-3 and WP-4 done (it deletes
code they stop importing); WP-6 can run any time after WP-5. Each package's gate: its
own new tests pass, the full `./venv-dnd-server/bin/python -m pytest` passes, and
`ruff check app tests` and `black --check app tests` report nothing new.

### WP-1: Shared helpers (`messages.py`) and shared test support
- **Files:**
  - `app/services/messages.py` (new)
  - `tests/session_helpers.py` (new)
  - `tests/conftest.py` (add three fixtures; do not change `app`/`client`)
  - `tests/test_messages_helper.py` (new)
- **Inputs:** `app/services/logger.py` provides `get_logger(name)` (PAT-CODE-001: use
  it; no `logging.getLogger`, no `print`). The store passed in implements the
  `SessionStore` Protocol (`get_session`, `create_message(session_id, message_id,
  payload) -> dict`, `get_by_client_id(session_id, client_message_id) -> dict | None`,
  `list_messages`). The inference object has `enqueue(*, session_id, message_id,
  prompt, store) -> bool`. `InMemorySessionStore.get_session` returns the live list or
  `None`. No file in `app/` is changed by this package except the new module.
- **Outputs:**
  1. `app/services/messages.py` with module-level `logger = get_logger(__name__)`, and
     exactly two public functions:
     - `def submit_user_message(*, store, inference, session_id: str, payload:
       dict[str, Any]) -> tuple[dict[str, Any], bool, bool]`. Behaviour, in order:
       (a) `cid = payload.get("client_message_id")`; if `cid` is truthy and
       `existing = store.get_by_client_id(session_id, cid)` is not `None`, return
       `(existing, False, False)` (no create, no enqueue). (b) `message_id =
       str(uuid4())`. (c) `message = store.create_message(session_id, message_id,
       payload)`. (d) `queued = bool(inference.enqueue(session_id=session_id,
       message_id=message_id, prompt=payload["content"], store=store))`. (e)
       `logger.info("message.submitted", extra={"session_id": session_id,
       "message_id": message_id, "queued": queued})` (never use `"message"` as an
       `extra` key). (f) return `(message, True, queued)`. It does NOT check that the
       session exists, does NOT validate length, and does NOT catch exceptions;
       callers own those. Docstring (one short paragraph) states the return tuple
       meaning: `created` is False for an idempotent hit (then `queued` is False and
       meaningless); `queued` False means the inference queue was full.
     - `def build_snapshot(store, session_id: str) -> dict[str, Any] | None`. Returns
       `None` if `store.get_session(session_id) is None`. Otherwise returns
       `{"session_id": session_id, "entries": copy.deepcopy(list(messages)),
       "snapshot_at": time.time()}` where `messages` is what `store.get_session`
       returned. Must never return the live list or live dicts. Never creates a
       session.
  2. `tests/session_helpers.py` exactly as described in Test Spec "Shared test
     support" (`AUTH`, `make_stub_service`, `wait_idle`, `FakeInference`).
  3. `tests/conftest.py`: add the fixtures `stub_svc`, `session_store`, `stub_client`
     exactly as described in Test Spec "Shared test support". Add the needed imports
     at the top (`asyncio`, `from app.services.repos import InMemorySessionStore` next
     to the existing `make_default_repos` import, `from tests.session_helpers import
     make_stub_service`); keep import ordering ruff-clean. The existing `app` and
     `client` fixtures and their imports stay as they are.
  4. `tests/test_messages_helper.py` implementing Test Spec items 1-5 with those names
     and assertions.
- **Acceptance criteria:** `submit_user_message` returns `(message, True, True)` after
  creating one user message with a uuid-string id and enqueueing exactly one job with
  `session_id`, `message_id` (the new id), `prompt` (the payload content) and the
  store; for a repeated truthy `client_message_id` it returns `(existing, False,
  False)` and neither creates nor enqueues; when `enqueue` returns a falsy value it
  returns `(message, True, False)` and the message stays in the store.
  `build_snapshot` returns `None` for any unknown id (including `"1"`) without
  creating a session; for a known session it returns a dict with exactly the keys
  `session_id`, `entries`, `snapshot_at` (a `float`), and mutating the returned
  entries (including nested `meta`) or appending to the returned list never changes
  the store. The module has no `hasattr(`, no `print(`, no `logging.getLogger`. Items
  1-5 pass, and the existing tests (`app`/`client` fixtures included) still pass.
- **Patterns used/created:** PAT-ARCH-001 (accepted; "shared write function used by
  REST and WS", "copies not live list"), PAT-CODE-001 (accepted).

### WP-2: REST `post_message` uses the helper; remove `/api/v1/stream`
- **Files:**
  - `app/api/v1/session.py`
  - `tests/test_session_rest.py` (new)
- **Inputs:** WP-1 is complete, so `from app.services.messages import
  submit_user_message` works with the signature `submit_user_message(*, store,
  inference, session_id, payload) -> (message, created, queued)` (`created` False for
  an idempotent hit; `queued` False means queue full). `tests/session_helpers.py`
  (`AUTH`, `wait_idle`, `FakeInference`) and the `stub_svc`, `session_store`,
  `stub_client` fixtures in `tests/conftest.py` exist. In `session.py`, `post_message`
  currently contains inline: idempotency lookup via `store.get_by_client_id`,
  `message_id = str(uuid4())`, `store.create_message(session_id, message_id,
  payload.dict())` and `inference.enqueue(...)`; the file also defines
  `@router.websocket("/stream") async def stream_ws(...)` as the last function; and
  imports `Header` and `WebSocket` from `fastapi` only for that function.
- **Outputs:**
  1. In `post_message`, keep, in this order: the session-existence 404 check, then the
     length check (`len(payload.content) > MAX_INPUT_TOKENS * 4` -> 400, same detail
     text). Replace the inline idempotency block, `message_id = str(uuid4())`,
     `create_message` and `enqueue` with one call: `message, created, queued =
     submit_user_message(store=store, inference=inference, session_id=session_id,
     payload=payload.dict())`. Then: if `not created`, return `JSONResponse(
     status_code=200, content={"message_id": message["id"], "status":
     message["status"]})`. If `not queued`, return the existing 429 `JSONResponse`
     (same body `{"status": "queued_full", "retry_after": MAX_QUEUE_RETRY_AFTER,
     "message_id": message["id"]}` and `Retry-After` header). Otherwise `queue_pos =
     inference.queue_position(message["id"])`, set the `Location` header to
     `f"/api/v1/sessions/{session_id}/messages/{message['id']}"` and return
     `{"message_id": message["id"], "status": "queued", "queue_position": queue_pos}`.
     Response codes and bodies are identical to today.
  2. Delete the whole `@router.websocket("/stream")` function `stream_ws`.
  3. Remove `Header` and `WebSocket` from the `from fastapi import ...` line. Keep
     `uuid4` (still used by `create_session`), `Response`, `status`, `JSONResponse`,
     `HTTPException`, `Depends`, `APIRouter`. Add the `submit_user_message` import
     (ruff import order).
  4. Do not change any other route, `MAX_INPUT_TOKENS`, `MAX_QUEUE_RETRY_AFTER`, the
     auth dependency, or the duplicated `router = APIRouter(...)` line (REQ-0012).
  5. `tests/test_session_rest.py` implementing Test Spec items 6-11 with those names
     and assertions.
- **Acceptance criteria:** `POST /api/v1/sessions/{sid}/messages` still returns 404 for
  an unknown session, 400 for content longer than `MAX_INPUT_TOKENS * 4` characters (and
  stores nothing), 200 `{"message_id", "status"}` for a repeated `client_message_id`
  (no second message), 429 with `Retry-After: 5` and body `status ==
  "queued_full"` when the queue is full (the user message stays stored), and 202 with
  `message_id`, `status == "queued"`, `queue_position` and the `Location` header
  otherwise. The route `/api/v1/stream` no longer exists:   `session.py` contains no
  `websocket` decorator, no `stream_ws`, no `Header`, no `WebSocket` import. Tests 6-11
  pass; the existing suite still passes. (The "exactly one WS route" check is test 26a
  in WP-4, because it only holds once the WS rewrite is done.)
- **Patterns used/created:** PAT-ARCH-001 (accepted; thin adapters, shared write
  function), PAT-CODE-001 (accepted).

### WP-3: Snapshot reads the shared store; uuid snapshot schema
- **Files:**
  - `app/schemas/v1.py`
  - `app/api/v1/intelligence.py`
  - `tests/test_intel_snapshot.py` (new)
- **Inputs:** WP-1 is complete, so `from app.services.messages import build_snapshot`
  gives `build_snapshot(store, session_id) -> {"session_id", "entries", "snapshot_at"}
  | None` (`None` for an unknown session; entries are deep copies of the store's
  message dicts). `MessageResp` already exists in `app/schemas/v1.py` (above the
  snapshot models). `schemas/v1.py` currently ends with `class SessionEntry(BaseModel)`
  (int `id`, int `run_id`, `timestamp`, `role`, `text`, `meta`) followed by `class
  SessionSnapshotResp(BaseModel)` with `run_id: int`, `entries: list[SessionEntry]`,
  `snapshot_at: float` and a `schema_extra` example containing `"run_id": 7`.
  `intelligence.py` currently imports `SessionService` and implements
  `@router.get("/sessions/{run_id}/snapshot", response_model=SessionSnapshotResp)` with
  parameter `run_id: int`. Fixtures `stub_svc`, `session_store`, `stub_client` and
  helpers `AUTH`, `wait_idle` exist.
- **Outputs:**
  1. `app/schemas/v1.py`: delete `class SessionEntry` entirely. Change
     `SessionSnapshotResp` to fields `session_id: str`, `entries: list[MessageResp]`,
     `snapshot_at: float`; docstring "Snapshot of a session (same message shape as the
     REST list)."; its `schema_extra` example becomes `{"session_id": "b3f1c2d4-...",
     "entries": [], "snapshot_at": 1695841234.567}`. Do not alter any other model.
  2. `app/api/v1/intelligence.py`: remove the `SessionService` import; add
     `from app.services.messages import build_snapshot`. Replace the snapshot route
     with `@router.get("/sessions/{session_id}/snapshot",
     response_model=SessionSnapshotResp)` and function `snapshot_session(session_id:
     str, session_store=Depends(get_session_store))` that calls
     `build_snapshot(session_store, session_id)`; if the result is `None` raise
     `HTTPException(status_code=404, detail="Session not found")`; otherwise return
     `SessionSnapshotResp(**snapshot)`. Update the comment above it to say the snapshot
     reads the shared session store. Do not touch the `/tools`, `/tools/{tool_name}/
     invoke` or `/status` routes. `HTTPException` is already imported.
  3. `tests/test_intel_snapshot.py` implementing Test Spec items 12-16 with those names
     and assertions.
- **Acceptance criteria:** `GET /api/v1/intel/sessions/{session_id}/snapshot` returns
  200 `{"session_id": <the uuid string>, "entries": [<MessageResp-shaped dicts>],
  "snapshot_at": <float>}` for a session created via `POST /api/v1/sessions`; after a
  REST message round-trip the entries are the user message (status `completed`) then
  the separate `role == "assistant"` reply with `meta.reply_to` equal to the user
  message's id, with ids equal to those of `GET /api/v1/sessions/{sid}/messages`; an
  empty session yields `entries == []`; unknown ids, including `"1"`, return 404 (no
  integer coercion, no auto-create). The OpenAPI document contains the path with
  `{session_id}`, no `{run_id}` path, no `SessionEntry` component and no `run_id`
  anywhere. `app/api/v1/intelligence.py` and `app/schemas/v1.py` contain neither
  `SessionService` nor `SessionEntry` nor `run_id`. Tests 12-16 pass; the existing
  suite still passes.
- **Patterns used/created:** PAT-ARCH-001 (accepted; thin adapter, session exists iff
  `get_session` is not `None`, 404 on unknown).

### WP-4: Rewrite the WebSocket onto the store and the shared helper
- **Files:**
  - `app/api/v1/ws.py` (full rewrite of the module contents)
  - `tests/test_ws_session.py` (new)
- **Inputs:** WP-1 is complete: `submit_user_message(*, store, inference, session_id,
  payload) -> (message, created, queued)` and `build_snapshot(store, session_id) ->
  dict | None` exist in `app/services/messages.py`. `app.config.get_settings()` returns
  settings with `.ollama.timeout_seconds` (float, default 30.0). `app.deps` provides
  `get_inference_service` and `get_session_store`. `app/services/logger.py` provides
  `get_logger`. Stored messages are dicts with keys `id, client_message_id, role,
  content, status, meta, created_at (datetime), updated_at (datetime)`. The worker
  (`OllamaInferenceService`) sets the user message status to `running`, creates the
  reply message (role `assistant`, `meta == {"reply_to": <user id>}`) and only after
  that sets the user message status `completed`; on failure it sets `error` and
  `meta["error"]`; if cancelled before start, `cancelled`. `app/factory.py` already
  includes `ws.router` (no change needed there). Fixtures `stub_svc`,
  `session_store`, `stub_client` and helpers `AUTH`, `wait_idle`, `FakeInference` exist.
  Starlette's `TestClient.websocket_connect(url)` is a context manager exposing
  `send_json`, `receive_json`; a close before accept raises `WebSocketDisconnect` with
  `.code`.
- **Outputs:** `app/api/v1/ws.py` containing, and nothing else of substance:
  1. Imports: `asyncio`, `contextlib`, `copy`, `time`, `typing.Any`, `fastapi`
     (`APIRouter, Depends, WebSocket, WebSocketDisconnect`),
     `fastapi.encoders.jsonable_encoder`, `app.config.get_settings`, `app.deps`
     getters, `app.services.logger.get_logger`, `app.services.messages`
     (`build_snapshot`, `submit_user_message`). `from __future__ import annotations`
     stays. `logger = get_logger(__name__)`. No import of `SessionService`.
  2. `router = APIRouter(prefix="/api/v1/ws", tags=["websocket"])`.
  3. Module constants: `TERMINAL_STATUSES = {"completed", "error", "cancelled"}`,
     `WS_POLL_INTERVAL_SECONDS = 0.05`, `WS_REPLY_MARGIN_SECONDS = 10.0`.
  4. `def _reply_timeout_seconds() -> float: return
     float(get_settings().ollama.timeout_seconds) + WS_REPLY_MARGIN_SECONDS`
     (a function so tests can monkeypatch `app.api.v1.ws._reply_timeout_seconds`).
  5. `async def ws_send(ws, payload: dict[str, Any]) -> None:` that does `await
     ws.send_json(jsonable_encoder(copy.deepcopy(payload)))`. It has NO `try/except`:
     disconnects propagate to the handler's single outer `except WebSocketDisconnect`,
     and any other exception is a real bug and propagates too.
  6. `async def _wait_for_terminal(store, session_id, message_id, timeout: float) ->
     dict | None`: loop until `time.monotonic()` passes the deadline; each iteration
     scans `store.list_messages(session_id)` for the message with `id == message_id`
     and returns a deep copy once its `status` is in `TERMINAL_STATUSES`; otherwise
     `await asyncio.sleep(WS_POLL_INTERVAL_SECONDS)`; return `None` on timeout.
  7. `def _find_reply(store, session_id, user_message_id) -> dict | None`: the first
     message in `store.list_messages(session_id)` with `role == "assistant"` and
     `(m.get("meta") or {}).get("reply_to") == user_message_id`, as a deep copy.
  8. The endpoint `@router.websocket("/sessions/{session_id}") async def ws_session(ws:
     WebSocket, session_id: str, session_store=Depends(get_session_store),
     inference=Depends(get_inference_service))` with this behaviour:
     - If `session_store.get_session(session_id) is None`: `await ws.close(code=1008)`
       and return, BEFORE `ws.accept()`. Never create a session.
     - `await ws.accept()`, then send `{"type": "snapshot", **snapshot}` where
       `snapshot = build_snapshot(session_store, session_id)` (keys `session_id`,
       `entries`, `snapshot_at`; no `run_id`).
     - Inside one `try:` loop `while True: data = await ws.receive_json()`:
       - if `data` is not a `dict`: send `{"type": "error", "message": "Expected a JSON
         object"}` and continue.
       - `action = data.get("action")`.
       - `action == "user_message"`: validate first (nothing is stored on a validation
         failure; each failure sends `{"type": "error", "message": <text>}` and
         continues the loop): `inference is None` -> "Inference service unavailable";
         `text` (from `data.get("text")`) not a non-blank `str` -> "text is required";
         `client_message_id` (from `data.get("client_message_id")`) present and not a
         `str` -> "client_message_id must be a string". Then `message, created, queued
         = submit_user_message(store=session_store, inference=inference,
         session_id=session_id, payload={"client_message_id": cid, "role": "user",
         "content": text, "meta": None})`. Send `{"type": "entry", "entry": message}`.
         If `created and not queued`: send `{"type": "error", "message_id":
         message["id"], "message": "Inference queue full; try again later"}` and
         continue. Otherwise `final = await _wait_for_terminal(session_store,
         session_id, message["id"], _reply_timeout_seconds())`. If `final is None`:
         send `{"type": "error", "message_id": message["id"], "message": "Timed out
         waiting for reply"}`. If `final["status"] == "completed"`: `reply =
         _find_reply(...)`; if found send `{"type": "entry", "entry": reply}` then
         `{"type": "done", "message_id": message["id"], "reply_id": reply["id"]}`; if
         not found `logger.error(...)` and send an `error` event "Reply not found". If
         `final["status"] == "error"`: send `{"type": "error", "message_id":
         message["id"], "message": (final.get("meta") or {}).get("error") or
         "Inference failed"}`. If `final["status"] == "cancelled"`: send `{"type":
         "error", "message_id": message["id"], "message": "cancelled"}`.
       - `action == "status"`: as today: `{"type": "status", "queue_position":
         inference.queue_position(None), "estimated_wait_seconds":
         inference.estimate_wait(None)}` (both `None` when `inference` is `None`).
       - any other action: `{"type": "error", "message": f"Unknown action: {action}"}`.
     - Outer handling: `except WebSocketDisconnect: return` (the only silent
       swallow). `except Exception:` -> `logger.exception("ws.session.failed",
       extra={"session_id": session_id})`, then `with contextlib.suppress(RuntimeError,
       WebSocketDisconnect): await ws.close(code=1011)`, then return. Do not catch
       `Exception` anywhere else in the module; do not use `hasattr`.
  9. Not in this module any more: `generate_tokens` calls, the `token` event, the
     `cancel` action, `SessionService`, integer ids, `run_id`.
  10. `tests/test_ws_session.py` implementing Test Spec items 17-27 (including 26a)
      with those names and assertions. Items 24 and 25 build their own app: `create_app(services=
      {"inference": FakeInference(...), "session": session_store})` in `with
      TestClient(app) as c:`; item 27 uses `asyncio.run(...)` or an `async def` test
      (`asyncio_mode = "auto"`).
- **Acceptance criteria:** There is exactly one WebSocket route in the app,
  `/api/v1/ws/sessions/{session_id}` (a `str` param). Connecting with an unknown id
  (including `"1"`) is closed with code 1008 and creates nothing. Connecting to a known
  session first yields `{"type": "snapshot", "session_id", "entries", "snapshot_at"}`
  read from the same store REST uses (so messages created via REST appear), with
  `datetime` values serialized (no exception). Sending `{"action": "user_message",
  "text": "hello"}` yields, in order, an `entry` for the stored `role == "user"`
  message, an `entry` for the worker-written separate `role == "assistant"` message
  whose `meta.reply_to` is the user message's id, and `{"type": "done", "message_id":
  <user id>, "reply_id": <reply id>}`; afterwards `GET /api/v1/sessions/{sid}/messages`
  and `GET /api/v1/intel/sessions/{sid}/snapshot` both show exactly those two messages.
  A repeated `client_message_id` does not create a second user message or call
  `generate` again. Inference failure yields an `error` event carrying the failure
  text (for example `boom`) and the connection remains usable; a full queue, a
  cancelled job and a wait longer than `_reply_timeout_seconds()` each yield an
  `error` event ("queue full" / "cancelled" / "Timed out") instead of hanging.
  Invalid actions or fields yield `error` events, store nothing, and keep the socket
  open. `ws_send` re-raises any non-disconnect exception and applies
  `jsonable_encoder`. `ws.py` contains no `SessionService`, `run_id`, `hasattr(`,
  `generate_tokens`, or bare `except Exception: pass`. Tests 17-27 and 26a pass; the
  existing suite still passes.
- **Patterns used/created:** PAT-ARCH-001 (accepted; WS as a thin adapter reading
  replies from the store, bounded wait, `jsonable_encoder`, 1008 on unknown), PAT-CODE-001
  (accepted).

### WP-5: Delete `SessionService` and `GameService`; slim `build_services`
- **Files:**
  - `app/services/session_service.py` (delete)
  - `app/services/game_service.py` (delete)
  - `app/services/build_services.py`
  - `tests/test_single_session_model.py` (new)
- **Inputs:** WP-3 and WP-4 are complete, so no module imports `SessionService` any
  more. Before deleting, confirm by searching the repository (excluding
  `venv-dnd-server/`, `docs/` and `.git/`) for `session_service`, `game_service`,
  `SessionService` and `GameService`; the only expected hits are the two files
  themselves and `app/services/build_services.py` (which imports `GameService`). If any
  other code outside `docs/` still imports them, stop and report instead of deleting.
  `build_services(repos, enable_tool_discovery=True)` currently builds
  `game_service = GameService()` and returns `{"session": session_store, "tool":
  tool_service, "game": game_service, "inference": inference}`. `data/repos.py` at the
  repo root is NOT to be touched. `tests/test_tool_calling.py` depends on
  `make_default_repos` and `services["tool"]` and
  `services["tool"].default_context["inference"]`, which must keep working.
- **Outputs:**
  1. Delete `app/services/session_service.py` and `app/services/game_service.py`
     (also remove stale `app/services/__pycache__/*session_service*` and
     `*game_service*` `.pyc` files if present, so the import test cannot be fooled).
  2. `app/services/build_services.py`: remove `from app.services.game_service import
     GameService`, the `game_service = GameService()` line, and the `"game"` entry of
     the returned dict. The result is exactly `{"session": session_store, "tool":
     tool_service, "inference": inference}`. Change nothing else (no signature change).
  3. Do NOT modify `app/services/repos.py`, `app/type_defs.py`, `data/`, `app/main.py`.
  4. `tests/test_single_session_model.py` implementing Test Spec items 28-32 with those
     names and assertions.
- **Acceptance criteria:** `import app.services.session_service` and `import
  app.services.game_service` raise `ModuleNotFoundError`; the two files are gone; no
  `.py` file under `app/` mentions `SessionService`, `GameService`, `session_service`,
  `game_service` or `SessionEntry`; `build_services(...)` returns a dict whose keys are
  exactly `session`, `tool`, `inference`; `app.services.repos` still exports
  `InMemorySessionStore`, `DEFAULT_REPOS`, `make_default_repos`, `seed_sample_data`
  unchanged and `seed_sample_data` still seeds session `"demo"`; the `SessionStore`
  Protocol still declares exactly its six methods; `data/` has no diff. Tests 28-32
  pass; the full suite (including `tests/test_tool_calling.py`) passes; `ruff check`
  and `black --check` are clean.
- **Patterns used/created:** PAT-ARCH-001 (accepted; "no private stores / no hasattr
  fallbacks").

### WP-6: Refresh the agent instructions doc
- **Files:** `.github/copilot-instructions.md` (only this file).
- **Inputs:** WP-5 is complete. The file's "Architecture" list currently contains: (a)
  the line "`app/services/build_services.py` — Constructs the services dict (`session`,
  `tool`, `game`, `inference`) from repos + settings."; (b) the line
  "`app/services/repos.py` — **Active** in-memory repo layer (`InMemorySessionStore`,
  `DEFAULT_REPOS`). This is what's actually wired up today."; (c) the line describing
  `app/api/v1/*` routers: "`session.py` (REST session/message CRUD), `ws.py` (live
  session WebSocket), `intelligence.py` (tool/inference endpoints)".
- **Outputs:**
  1. Edit (a) to list `session`, `tool`, `inference` (drop `game`).
  2. Edit (b) to additionally say that `InMemorySessionStore` is the only in-memory
     session store, it implements the `SessionStore` Protocol in `app/type_defs.py`,
     and every transport (REST, the single WebSocket, `/intel` snapshot) uses it via
     `get_session_store()`; session ids are uuid strings.
  3. Edit (c) to say `ws.py` is the only WebSocket (`/api/v1/ws/sessions/{session_id}`)
     and `intelligence.py` also serves `/api/v1/intel/sessions/{session_id}/snapshot`;
     add one short sentence that `app/services/messages.py` holds the shared
     "submit user message" and "snapshot" helpers used by REST and WS.
  4. Do not edit anything else (no ADR, pattern, LOG.md or BACKLOG.json changes;
     the orchestrator owns those).
- **Acceptance criteria:** The three lines above are updated as described; the word
  `game` no longer appears in the `build_services` line; the file mentions no
  `SessionService`, `GameService`, `run_id` or `/api/v1/stream`; no other lines of the
  file change. The full test suite still passes (docs-only change).
- **Patterns used/created:** none.

## 4. Other Details
- **Risks:**
  - *WS JSON serialization (accepted risk from ADR-0002).* Stored messages contain
    `datetime` values; `ws.send_json` alone would raise, and the old `ws_send` hid it.
    Mitigated by `jsonable_encoder` in `ws_send`, no blanket `except` around sends, and
    tests 17, 18 and 27.
  - *Live-list coupling.* `inference_service._update_message_status` mutates the dicts
    returned by `store.get_session(...)`, which only works because
    `InMemorySessionStore` returns live data. Unchanged here, and REQ-0005 must keep it
    or add update methods to the Protocol. Snapshot and WS output are deep copies, never
    the live list (tests 4, 12).
  - *Thread safety.* The worker thread mutates the store while the event loop reads it;
    `InMemorySessionStore` has no lock. Same exposure REST has today; deep copies reduce
    "changed size during iteration" risk on the WS/snapshot read path but do not
    eliminate it. Not fixed here.
  - *Bounded wait vs. a long queue.* The WS waits at most `ollama.timeout_seconds` +
    10 s per message. With several jobs queued ahead the WS can time out and send an
    `error` event while the job later completes; the REST status endpoint and a fresh
    snapshot still show the truth. Accepted; REQ-0007 reworks the protocol.
  - *WS handler is serial.* While waiting for one reply it cannot read another client
    action (for example `status`). Accepted per ADR-0002.
  - *Breaking JSON changes* on `/intel/.../snapshot` (`run_id` -> `session_id`, entry
    shape), the WS (`token` event and in-WS `cancel` removed; `entry`/`done`
    semantics changed) and the snapshot of an unknown session (now 404). No frontend
    exists in this repo yet (REQ-0016/0017). Accepted per ADR-0002.
  - *No WS auth anywhere after `/stream` is removed.* `ws.py` never had it; exposure is
    unchanged. REQ-0009 owns WS auth. `inference.validate_token` becomes unused until
    then.
  - *Test 26 wraps `enqueue` to cancel before the worker dequeues.* It depends on the
    worker checking `job.message_id in self._cancelled` right after dequeue; if that
    changes, revisit the test.
  - `tests/conftest.py` is modified additively (three new fixtures). Existing fixtures
    and tests are unaffected.
- **Rollback plan:** All state is in memory, so there is no data migration. Revert the
  work packages in reverse order with `git revert` (WP-6, WP-5, WP-4, WP-3, WP-2, WP-1)
  or reset the branch; the deleted `session_service.py` and `game_service.py` are
  restored from git history. No new dependency was added.
- **Patterns applied/created:**
  - PAT-ARCH-001 "One session store API; transports are thin adapters" (architecture,
    `accepted`): applied in WP-1 to WP-5. Created by the architect with ADR-0002;
    accepted by the human on 2026-10-11.
  - PAT-CODE-001 "Centralized logging via app.services.logger" (code, `accepted`):
    applied in `messages.py` and `ws.py` (`get_logger(__name__)`).
  - New patterns created by this spec: none. (The `tests/session_helpers.py` +
    `stub_client` fixture arrangement is a one-spec convenience; if a later spec reuses
    it, record it as a proposed `spec`/`code` pattern then.)
- **Non-goals:**
  - REQ-0005: no persistent store, no change to repo-root `data/` (including
    `data/repos.py`) or its ORM layer; no extension of the `SessionStore` Protocol; no
    update methods or locking for `InMemorySessionStore`.
  - REQ-0006: no prompt/history/system-prompt changes; the prompt remains the raw
    message content.
  - REQ-0007: no token streaming, no `generate_tokens` rework (it stays in
    `inference_service.py`, uncalled by any transport), no WS event-protocol document,
    no in-WS cancel, no concurrent reply handling on one socket.
  - REQ-0008: no tool or slash-command dispatch (the old
    `SessionService.invoke_tool_and_record` idea is not ported).
  - REQ-0009: no auth or CORS changes (including WS auth).
  - REQ-0010: no schema/contract cleanup beyond the snapshot response and deleting
    `SessionEntry`; leave pydantic v1-style `Config` classes, the status-description
    text in `MessageResp`, and the `MessageListResp` model as they are.
  - REQ-0012: no hygiene cleanup (the duplicated `router = APIRouter(...)` line in
    `session.py`, `app/tst.py`, `.pyc` clutter other than the two deleted modules').
  - No `ConversationService` class (ADR-0002 Option E); promote the helper only if
    REQ-0006/0007 need it.
  - No change to ADR/pattern status, `docs/requirements/LOG.md` or `BACKLOG.json`.
