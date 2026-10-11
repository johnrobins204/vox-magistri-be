---
id: SPEC-0003
requirement: REQ-0003
adr: null
status: draft
date: 2026-10-11
---

# Inference Worker Stores Each Reply as a New Assistant Message

## 1. Requirement
> The inference worker MUST store each generated reply as a new, separate message
> with role='assistant' and meta.reply_to set to the originating user message's id,
> and MUST NOT modify the user message's role or content;
> GET /api/v1/sessions/{id}/messages/{message_id}/status for the user's message_id
> MUST continue to report the existing status vocabulary
> (queued/running/completed/error/cancelled); error and cancellation behaviour MUST
> be preserved; tests MUST run without network or Ollama (stubbed
> OllamaClient/generate). The session id model, persistence, prompt pipeline and
> status vocabulary MUST NOT be changed (REQ-0004/0005/0006/0010). Smallest edit.
> (REQ-0003)

Linked ADR: none. The architect decided no ADR is needed: the change is confined to
one module, is reversible, adds no dependency and changes no convention.

Verified facts this spec relies on (checked against the tree on 2026-10-11):
- `app/services/inference_service.py`, `OllamaInferenceService._worker_loop`, after
  `text = self.client.generate(job.prompt)`, calls
  `self._update_message_content(job.store, job.session_id, job.message_id, text)` and
  then `self._update_message_status(..., "completed")`.
- `_update_message_content` finds the user message in `store.get_session(session_id)`
  and sets `m["role"] = "assistant"` and `m["content"] = content`. This loses the
  user's prompt. It is the defect. Nothing else calls it (the WS path,
  `generate_tokens`, does not touch the store).
- `_update_message_status(store, session_id, message_id, status)` mutates the live
  message dict (`status`, `meta["updated_by"]`). It swallows exceptions with
  `logger.exception`. `_update_message_meta(store, session_id, message_id, meta)`
  does the same for `meta`.
- `InMemorySessionStore.create_message(session_id, message_id, payload)` in
  `app/services/repos.py` builds `{"id", "client_message_id", "role", "content",
  "status": "queued", "meta", "created_at", "updated_at"}`, appends it to the
  session list, and returns it. It hard-codes `status="queued"`.
  `InMemorySessionStore.update_message_status(session_id, message_id, status)` sets
  `status` and `updated_at`. `list_messages` and `get_session` return the live list.
- `get_message_status` in `app/api/v1/session.py` reads `msg.get("status")` and
  `msg.get("meta")` from the message whose `id` equals the URL `message_id`, and
  `inference.queue_position(message_id)` / `estimate_wait(message_id)`, which key on
  `InferenceJob.message_id` (the user message id). No linkage change is needed.
- `post_message` creates ids with `str(uuid4())` and never sets a `client_message_id`
  on anything but the user message.
- `OllamaInferenceService.__init__(settings)` builds `OllamaClient(base_url=
  settings.ollama.base_url, default_model=settings.ollama.model,
  timeout_seconds=settings.ollama.timeout_seconds)`. The `OllamaClient` constructor
  only stores strings; it opens no connection. The worker thread starts in the
  constructor and polls `Queue.get(timeout=0.5)`.
- `OllamaClient.generate(self, prompt, *, model=None) -> str`.
- `tests/conftest.py` builds the real service via `build_services`; the new tests
  must not rely on it.

## 2. Test Spec
Written before any work package. "Done" means all of the following pass.
New file: `tests/test_inference_reply.py`. Do not change `tests/conftest.py`.

Shared test setup (stated once so each test below is unambiguous):
- Build the service with a stub settings object, not `get_settings()`:
  `types.SimpleNamespace(ollama=types.SimpleNamespace(base_url="http://127.0.0.1:1",
  model="stub", timeout_seconds=1.0))`, then `OllamaInferenceService(settings)`.
  Constructing it does not connect to anything.
- Replace generation with
  `monkeypatch.setattr(svc.client, "generate", lambda prompt, **kw: "stub reply")`
  (or a function that raises `RuntimeError("boom")` for the error tests). The real
  `httpx` call is therefore never made.
- Store: `store = InMemorySessionStore()`, `store.create_session("s1")`, then the user
  message `store.create_message("s1", "u1", {"role": "user", "content": "hello"})`,
  then `svc.enqueue(session_id="s1", message_id="u1", prompt="hello", store=store)`.
- Synchronization: poll `svc._queue.unfinished_tasks == 0` with a 5 second deadline
  and a short (`0.01` s) sleep between polls. No single fixed sleep. Fail the test if
  the deadline passes. (`task_done()` runs in the worker's `finally`, after every
  status and meta write, so this is race-free.)
- Teardown: a fixture yields the service and then runs `asyncio.run(svc.shutdown())`.

Tests:

1. **`test_reply_is_new_assistant_message`**
   - Exercises: the success path with the stub returning `"stub reply"`.
   - Expected: `store.list_messages("s1")` has exactly 2 entries. Entry 0 has
     `id == "u1"`. Entry 1 has `role == "assistant"`, `content == "stub reply"`,
     `id != "u1"`, and `meta["reply_to"] == "u1"`.

2. **`test_user_message_not_modified`**
   - Exercises: the same success path.
   - Expected: the message with `id == "u1"` still has `role == "user"` and
     `content == "hello"`, and its `status == "completed"`.

3. **`test_reply_message_is_completed_and_unlinked`**
   - Exercises: the reply message's own fields after the success path.
   - Expected: reply `status == "completed"`, `client_message_id is None`, and
     `meta == {"reply_to": "u1"}` (no other keys).

4. **`test_error_path_preserves_user_message`**
   - Exercises: stub `generate` raises `RuntimeError("boom")`.
   - Expected: exactly 1 message in the session (no reply is created). It has
     `role == "user"`, `content == "hello"`, `status == "error"`, and
     `meta["error"] == "boom"`.

5. **`test_store_write_failure_is_reported_as_error`**
   - Exercises: stub `generate` returns `"stub reply"`, but
     `monkeypatch.setattr(store, "create_message", <function raising
     RuntimeError("store down")>)` is applied AFTER the user message was created and
     BEFORE `enqueue`.
   - Expected: the session has exactly 1 message; it has `role == "user"`,
     `content == "hello"`, `status == "error"`, and `meta["error"] == "store down"`.
     This proves the reply write is not swallowed.

6. **`test_cancel_before_start_preserved`**
   - Exercises: call `svc.cancel("u1")` BEFORE `svc.enqueue(...)`. The worker checks
     `job.message_id in self._cancelled` right after dequeuing, so this is
     deterministic. The stub `generate` is a function that fails the test (raises
     `AssertionError`) if called.
   - Expected: exactly 1 message in the session; `status == "cancelled"`,
     `role == "user"`, `content == "hello"`.

7. **`test_status_and_messages_endpoints_after_reply`**
   - Exercises: HTTP layer over the same service. Build
     `app = create_app(services={"inference": svc, "session": store})` and use
     `with TestClient(app) as c:` with header `{"Authorization": "Bearer x"}`.
     Run the success path first (wait for idle), then call
     `GET /api/v1/sessions/s1/messages/u1/status` and
     `GET /api/v1/sessions/s1/messages`.
   - Expected: the status call returns 200 with `body["message_id"] == "u1"` and
     `body["status"] == "completed"`. The list call returns 200 with 2 items; the
     second has `role == "assistant"` and `meta["reply_to"] == "u1"` (it survives
     `MessageResp`). Because `TestClient.__exit__` calls `svc.shutdown()`, the
     teardown fixture's second shutdown call must remain harmless (it is; shutdown
     is idempotent).

8. **Existing suite still passes.**
   - Exercises: all other files in `tests/`.
   - Expected: `./venv-dnd-server/bin/python -m pytest` passes entirely. No test in
     this spec opens a network connection or needs Ollama.

## 3. Work Packages

### WP-1: Add `_append_reply` to `OllamaInferenceService`
- **Files:** `app/services/inference_service.py` (only this file).
- **Inputs:** The file defines `logger = get_logger(__name__)` at module level, `from
  uuid import ...` is NOT yet imported, and class `OllamaInferenceService` has store
  helper methods `_update_message_status`, `_update_message_content`,
  `_update_message_meta` under the comment block `# Store helpers (best-effort, ...)`.
  The store passed in jobs implements `create_message(session_id, message_id,
  payload) -> dict` and `update_message_status(session_id, message_id, status)`.
- **Outputs:**
  1. Add the import `from uuid import uuid4` among the stdlib imports (keep the
     existing import ordering style; run `ruff check` afterwards).
  2. Add this method to the class, directly after `_update_message_status` (leave
     `_update_message_content` in place for now; WP-2 removes it):
     ```
     def _append_reply(self, store, session_id: str, user_message_id: str, text: str) -> str:
     ```
     Behaviour, in order:
     - `reply_id = str(uuid4())`
     - `store.create_message(session_id, reply_id, {"role": "assistant",
       "content": text, "meta": {"reply_to": user_message_id}})`
     - `store.update_message_status(session_id, reply_id, "completed")` (because
       `create_message` hard-codes `"queued"` and the reply is never enqueued)
     - `logger.info("reply.appended", extra={"session_id": session_id,
       "message_id": user_message_id, "reply_id": reply_id})`. Do not use `"message"`
       as an `extra` key (reserved by `logging`).
     - `return reply_id`
     - Do NOT wrap the body in `try/except`. Do NOT set `client_message_id`. Do NOT
       touch the user message.
     - Add a one-line docstring: appends the reply as a new assistant message linked
       by `meta.reply_to`; exceptions propagate so the worker marks the job as error.
- **Acceptance criteria:** `_append_reply` exists with the exact signature above and
  returns the new message id as a `str`. It calls `store.create_message` once with
  the payload `{"role": "assistant", "content": text, "meta": {"reply_to":
  user_message_id}}` and `store.update_message_status(session_id, reply_id,
  "completed")` once. It contains no `try`/`except`, no `print(`, and no use of
  `logging.getLogger`. An exception from the store propagates to the caller. No
  other function in the file is modified in this package. `ruff check
  app/services/inference_service.py` reports nothing new.
- **Patterns used/created:** PAT-CODE-001 (accepted): logging via `get_logger`.

### WP-2: Use `_append_reply` in `_worker_loop` and delete the mutating helper
- **Files:** `app/services/inference_service.py` (only this file).
- **Inputs:** WP-1 is complete, so `_append_reply(store, session_id,
  user_message_id, text) -> str` exists. In `_worker_loop`, inside the `try:` block
  after `text = self.client.generate(job.prompt)`, the code is:
  ```
  # Write assistant response back into the session store
  self._update_message_content(
      job.store,
      job.session_id,
      job.message_id,
      text,
  )
  self._update_message_status(job.store, job.session_id, job.message_id, "completed")
  ```
  The method `_update_message_content(self, store, session_id, message_id, content)`
  sets `m["role"] = "assistant"` and `m["content"] = content` on the user message.
  The existing `except Exception as exc:` block sets the user message status to
  `"error"` and `meta` to `{"error": str(exc)}`.
- **Outputs:**
  1. Replace the `_update_message_content(...)` call with
     `self._append_reply(job.store, job.session_id, job.message_id, text)` (ignore the
     return value), and change its comment to
     `# Append the reply as a new assistant message; the user message is untouched`.
     Keep the following `self._update_message_status(..., "completed")` line
     immediately after it, so the reply is stored first and the user message is
     marked completed second.
  2. Delete the entire `_update_message_content` method.
  3. Update the `_worker_loop` docstring second line from "Updates message status and
     content in the session store." to "Updates message status and appends the reply
     as a new assistant message."
  4. Do not change the cancellation branch, the `running` status update, the ETA
     moving average, the `except` block, `generate_tokens`, `cancel`, `enqueue`,
     `queue_position`, `estimate_wait`, `_update_message_status` or
     `_update_message_meta`.
- **Acceptance criteria:** After a successful job the user message keeps role
  `"user"` and its original content, has status `"completed"`, and the session has
  one additional message with role `"assistant"`, the generated text as content,
  `meta == {"reply_to": <user message id>}`, and status `"completed"`. If
  `client.generate` raises, or `store.create_message` raises, the user message gets
  status `"error"` and `meta["error"]` set, keeps its role and content, and no reply
  message exists. A job cancelled before start still ends with status `"cancelled"`
  and no reply. The string `_update_message_content` no longer appears anywhere in
  the repository's `app/` directory. The status vocabulary stays exactly
  `queued/running/completed/error/cancelled`. `ruff check
  app/services/inference_service.py` reports nothing new.
- **Patterns used/created:** PAT-CODE-001 (accepted); no new logging is added here.

### WP-3: Add the reply tests
- **Files:** `tests/test_inference_reply.py` (new). Do not modify `tests/conftest.py`
  or any file under `app/`.
- **Inputs:** WP-1 and WP-2 are complete. Importable names:
  `from app.services.inference_service import OllamaInferenceService`,
  `from app.services.repos import InMemorySessionStore`,
  `from app.factory import create_app`, `from fastapi.testclient import TestClient`,
  plus stdlib `asyncio`, `time`, `types`, and `pytest`. The service constructor takes
  one settings object with `.ollama.base_url`, `.ollama.model`,
  `.ollama.timeout_seconds`. `svc.client.generate(prompt, *, model=None)` is the only
  call that would reach the network. `svc._queue` is a `queue.Queue`; its
  `unfinished_tasks` attribute is 0 when all jobs are fully processed.
  `svc.cancel(message_id)` records the id so the worker skips it at dequeue.
  `svc.shutdown()` is `async`.
- **Outputs:** Implement the seven tests from Test Spec items 1-7 with the same
  names and assertions, plus these helpers/fixtures at the top of the file:
  - `svc` fixture: builds the service from the stub settings in the shared setup,
    yields it, and in teardown runs `asyncio.run(svc.shutdown())`.
  - `store` fixture: `InMemorySessionStore()` with session `"s1"` and user message
    `"u1"` (`role="user"`, `content="hello"`) already created.
  - `wait_idle(svc, timeout=5.0)` helper: loops until `svc._queue.unfinished_tasks
    == 0`, sleeping `0.01` s between checks, and calls `pytest.fail(...)` on timeout.
  - Stubbing is done with `monkeypatch.setattr(svc.client, "generate", ...)` inside
    each test (success stub returns `"stub reply"`; error stub raises
    `RuntimeError("boom")`; cancel-test stub raises `AssertionError`).
  If constructing the service ever makes a real network call in your environment,
  additionally `monkeypatch.setattr("app.services.inference_service.OllamaClient",
  <fake class>)` before building it; this should not be necessary.
- **Acceptance criteria:** All seven tests pass with
  `./venv-dnd-server/bin/python -m pytest tests/test_inference_reply.py`, and the full
  `./venv-dnd-server/bin/python -m pytest` run passes with no failures. The tests
  assert, in full: (a) after a successful job the session has 2 messages, the user
  message still has role `user`, content `hello`, status `completed`, and the reply
  has role `assistant`, content `stub reply`, status `completed`,
  `client_message_id is None`, `meta == {"reply_to": "u1"}`; (b) a raising
  `generate` leaves 1 message, status `error`, `meta["error"] == "boom"`, content
  `hello`, role `user`; (c) a raising `store.create_message` leaves 1 message with
  status `error` and `meta["error"] == "store down"`; (d) `cancel("u1")` before
  `enqueue` leaves 1 message with status `cancelled` and `generate` never called;
  (e) via `TestClient`, `GET /api/v1/sessions/s1/messages/u1/status` returns 200
  with `status == "completed"` and `GET /api/v1/sessions/s1/messages` returns 2
  items with the second having `meta["reply_to"] == "u1"`. No test uses a fixed
  `time.sleep` as its only synchronization, none touches the network, and `ruff
  check tests` reports no new findings.
- **Patterns used/created:** none.

Dependency order: WP-1 -> WP-2 -> WP-3.

## 4. Other Details
- **Risks:**
  - Two-step write is not atomic: if the reply is appended and the subsequent
    `_update_message_status(..., "completed")` fails, it is swallowed by that helper
    (existing behaviour), leaving the user message at `running` with a reply present.
    Accepted; no change to that helper under this requirement.
  - If `create_message` succeeds but `update_message_status` on the reply raises, the
    worker marks the user message `error` while an assistant message already exists.
    Accepted for the in-memory store, where this cannot realistically fail.
  - Clients that previously read the reply from the user message's `content` now
    need to read the message with `meta.reply_to == <user id>`. This is the intended
    behaviour change. The WS path is unchanged and is not affected.
  - Test 7 uses the global `deps.set_services` via `create_app`; later tests that
    call `create_app` re-set it, so there is no leakage.
  - The sync-polling helper relies on the private `_queue.unfinished_tasks`; if the
    queue implementation changes, update the helper.
- **Rollback plan:** Revert the `inference_service.py` edit (restore
  `_update_message_content` and the call in `_worker_loop`, remove `_append_reply`
  and the `uuid4` import) and delete `tests/test_inference_reply.py`. No schema,
  persisted-data or API contract changes are involved; one git revert.
- **Patterns applied/created:**
  - PAT-CODE-001 (accepted): applied; the new log line uses the module's
    `get_logger(__name__)` logger.
  - No ADR. No new patterns created. No existing `spec/` patterns exist in
    `docs/patterns/INDEX.md`.
- **Non-goals (explicitly out of scope):**
  - The WebSocket path (`generate_tokens`, `stream_ws` placeholder message creation).
  - Any change to `app/api/v1/session.py`, `app/services/repos.py`,
    `app/type_defs.py`, `app/schemas/v1.py`, or `app/services/build_services.py`.
  - The session id model, persistence, prompt pipeline and status vocabulary
    (REQ-0004/0005/0006/0010).
  - Stale schema docstrings (`in_progress|done` vs the real `running|completed`).
  - `_update_message_status` / `_update_message_meta` mutating live dicts and
    bypassing `store.update_message_status`.
  - Cancelling an already-running job (unsupported today).
  - Conversation-history building for prompts, and pagination or filtering of reply
    messages in `GET /messages`.
