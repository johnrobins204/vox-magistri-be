---
id: SPEC-0005
requirement: REQ-0005
adr: ADR-0003
status: draft
date: 2026-10-11
---

# Durable Sessions: a stdlib `sqlite3` `SessionStore`, `database.url` Wired In, `data/` Removed

## 1. Requirement
> Sessions and their messages MUST survive a server restart: the single `SessionStore`
> Protocol implementation MUST persist to durable local storage while keeping the
> REQ-0004 uuid session-id model and its no-silent-no-op contract; the persistence
> technology choice MUST be recorded in an ADR and any new runtime dependency MUST be
> justified per docs/constraints.md; the unimportable `data/` layer MUST be resolved
> (deleted, quarantined, or kept as recorded WIP); `settings.json` `database.url` MUST be
> honoured or explicitly removed; the inference worker's in-place mutation of
> store-returned dicts MUST keep working or be ported to explicit update methods; tests
> MUST run without network or Ollama. Campaign/character/quest domain (REQ-0015), prompt
> pipeline (REQ-0006), streaming (REQ-0007), tools (REQ-0008), auth/CORS (REQ-0009), API
> contract (REQ-0010) and repo hygiene (REQ-0012) MUST NOT be changed under this
> requirement. (REQ-0005)

Linked ADR: [ADR-0003](../adr/0003-sqlite-session-persistence.md) (**status: accepted**),
Option A (stdlib `sqlite3`, rubric A 78 / B 67 / D 64 / C 34).
Linked patterns: [PAT-ARCH-001](../patterns/architecture/PAT-ARCH-001-session-store-single-api.md)
(accepted, applied, NOT modified), [PAT-CODE-001](../patterns/code/PAT-CODE-001-centralized-logging.md)
(accepted, applied, NOT modified),
[PAT-ARCH-002](../patterns/architecture/PAT-ARCH-002-stdlib-sqlite-store.md) (accepted).

> **Gates resolved 2026-10-11:** the human accepted ADR-0003, PAT-ARCH-002 and gates
> G-1..G-12 in section 4.4; implementation may proceed.

### Decisions this spec implements (from ADR-0003 and the architect)
- `SqliteSessionStore(path: str)` in `app/services/repos.py` replaces
  `InMemorySessionStore`. Two tables `sessions` and `messages` (schema in WP-2). One
  `sqlite3` connection opened with `check_same_thread=False`, every public method under
  one `threading.Lock`, every write committed immediately. Datetimes stored as ISO-8601
  TEXT; `meta` stored as JSON TEXT. Reads return fresh dicts.
- Writes to an unknown session or message raise `KeyError` (no silent no-op). `get_session`
  still returns `None` for an unknown session and `[]` for an existing empty one.
- The `SessionStore` Protocol keeps its six method names. Only
  `update_message_status(session_id, message_id, status, meta: dict | None = None)` widens;
  it sets `status`, shallow-merges `meta`, bumps `updated_at`, in one transaction.
  `_update_message_meta` in the worker is deleted.
- Restart recovery: when a store is opened, messages left `queued` or `running` become
  `error` with `meta.error = "interrupted by server restart"`.
- `database.url` honoured: `make_default_repos(database_url: str = "sqlite:///:memory:")`;
  only `sqlite:///<path>` (relative to the CWD; `sqlite:////abs/path` for absolute) and
  `sqlite:///:memory:` are accepted, anything else raises `ValueError`. `app/main.py` calls
  `make_default_repos(get_settings().database.url)`. `DEFAULT_REPOS` is removed.
  `seed_sample_data` skips an existing `demo` session.
- `database.echo` stays unwired (PII risk, PAT-CODE-001); removal is REQ-0012's.
- `data/` is deleted (all four files). No new runtime dependency (`sqlite3`, `json`,
  `threading` are stdlib).

### Verified facts (checked against the tree on 2026-10-11)
- `app/services/repos.py` has `InMemorySessionStore` (`_sessions: dict[str, list[dict]]`;
  `get_session`/`list_messages` return LIVE lists; `update_message_status` silently
  no-ops on unknown ids and bumps `updated_at`; `create_message` stores
  `datetime.utcnow()` naive-UTC values and `status="queued"`), `DEFAULT_REPOS` (built at
  import), `make_default_repos()` (no args) and `seed_sample_data(repos)` (creates
  session `demo` with message `msg-1`, content `"Hello world!"`).
- `app/type_defs.py` `SessionStore.update_message_status(self, session_id: str,
  message_id: str, status: str) -> None` (no `meta`).
- `app/services/inference_service.py`: `enqueue` calls `put_nowait(job)` THEN
  `self._update_message_status(store, session_id, message_id, "queued")`;
  `_update_message_status(self, store, session_id, message_id, status)` mutates the dict
  returned by `store.get_session` (`status`, `meta["updated_by"] = "inference_worker"`);
  `_update_message_meta(self, store, session_id, message_id, meta)` mutates `meta`; the
  worker's `except Exception` path calls `_update_message_status(..., "error")` and then
  `_update_message_meta(..., {"error": str(exc)})`; `_append_reply` already uses only
  `store.create_message` and `store.update_message_status(session_id, reply_id,
  "completed")`.
- `app/main.py` imports `DEFAULT_REPOS, make_default_repos, seed_sample_data` and does
  `try: repos = DEFAULT_REPOS if DEFAULT_REPOS else make_default_repos() / except
  Exception: logger.exception(...); repos = make_default_repos()`. It does not import
  `get_settings`.
- `app/config.py` `DatabaseSettings.url` defaults to `"sqlite:///./dnd.db"` (same as
  `settings.json`); `echo` is read nowhere. `get_settings()` is `lru_cache`d and reads
  `settings.json` relative to the CWD.
- `ws.py`, `messages.py`, `session.py`, `intelligence.py` only READ store data
  (deep-copy or return it) and use only Protocol methods; none depends on live-dict
  identity. No change needed there.
- `data/` contains `__init__.py` (`from ...data import models, repos`, so `import data`
  fails), `models.py`, `repos.py`, `migrations.py` and an untracked `__pycache__`.
  Nothing in `app/` or `tests/` imports it. `requirements.txt` has no `sqlalchemy`.
- Test files that name `InMemorySessionStore`/`DEFAULT_REPOS`: `tests/conftest.py`,
  `tests/test_inference_reply.py`, `tests/test_messages_helper.py`,
  `tests/test_single_session_model.py`. `tests/test_tool_calling.py` calls
  `make_default_repos()` with no args (stays valid).
- Guard tests that scan `app/` text: `test_single_session_model.test_no_references_to_removed_symbols`
  (new code in `app/` MUST NOT contain `SessionService`, `GameService`, `session_service`,
  `game_service`, `SessionEntry`; and `run_id`/`hasattr(` in the files it lists) and
  `test_logging_consistency` (no `logging.getLogger(` outside `logger.py`; no `print(` in
  `tool_service.py`).
- Tooling: Python 3.13, `ruff check app tests`, `black --check app tests` (line length 100),
  `pytest` with `asyncio_mode = "auto"`. Run with `./venv-dnd-server/bin/python -m pytest -q`.

### Discrepancies between the architect output and the code (and how this spec resolves them)
1. **Work-package order.** The architect's WP-2 removes `InMemorySessionStore` and WP-3
   wires `main.py`, but `app/main.py` imports `DEFAULT_REPOS` (which instantiates
   `InMemorySessionStore` at import). Removing the class in WP-2 would break `main.py`
   (and `import app.main`) until WP-3. This spec re-slices the work (WP-2..WP-5 below):
   add the new class alongside the old one, switch `make_default_repos` and the tests,
   and only then remove the old class, `DEFAULT_REPOS` and the `main.py` import
   together.
2. **`main.py` silent fallback.** The architect says an unsupported URL "raises
   `ValueError` at startup", but `main.py` wraps repo creation in `try/except Exception`
   and falls back to `make_default_repos()`. Left as is, the `ValueError` would be
   swallowed and the server would silently run on a non-persistent store (the kind of
   silent fallback PAT-ARCH-001 item 6 forbids). WP-5 removes that `try/except`.
3. **Latent enqueue race (not mentioned by the architect).** `enqueue` puts the job on
   the queue before writing status `queued`. With the in-memory store this was benign in
   practice; with a store that releases the GIL on I/O, the worker can write `running` or
   even `completed` first and the late `queued` write would then overwrite it. WP-1 moves
   the `queued` write before `put_nowait`. (Observable behaviour is unchanged otherwise.)
4. **Undefined behaviour in the architect's text** for `create_session` on an existing id
   and for the `close()` needed by restart tests. See gates G-9 and G-10.
5. The architect's file list matches the code (no other file references
   `InMemorySessionStore`/`DEFAULT_REPOS`; `.github/copilot-instructions.md` describes
   `InMemorySessionStore`, `DEFAULT_REPOS`, `data/` and a lint exclusion for `data/`).
   `.github/instructions/tests.instructions.md` says "in-memory repos", which stays
   true (`:memory:`), so it is not edited.

## 2. Test Spec
Written before any work package. "Done" means every test below exists, passes with
`./venv-dnd-server/bin/python -m pytest -q`, and the rest of the existing suite still
passes. No test opens a network connection, needs Ollama, or touches `./dnd.db`: stores
are `SqliteSessionStore(":memory:")` or a file under pytest's `tmp_path`. The inference
service is `OllamaInferenceService` with a monkeypatched `client.generate` (constructing it
connects to nothing) or `FakeInference` from `tests/session_helpers.py`.

Terminology: "reopen" means `store.close()` then `SqliteSessionStore(same_path)`.

### `tests/test_sqlite_store.py` (new; store contract, WP-2 and WP-3)
All tests use `SqliteSessionStore`. Datetimes below are naive-UTC `datetime` objects.

- **T-01 `test_empty_and_unknown_sessions`**: on a `:memory:` store, `get_session("x")` is
  `None` and `list_messages("x") == []` for an unknown id; after `create_session("x")`
  `get_session("x") == []` (not `None`) and `list_messages("x") == []`.
- **T-02 `test_create_message_and_reads`**: `create_message("s", "m1", {"client_message_id":
  "c1", "role": "user", "content": "hi", "meta": {"k": 1}})` returns a dict whose keys are
  exactly `id, client_message_id, role, content, status, meta, created_at, updated_at`,
  with `status == "queued"`, `meta == {"k": 1}`, `created_at`/`updated_at` instances of
  `datetime`. Payload `{}` yields `role == "user"`, `content is None`,
  `client_message_id is None`, `meta == {}`; payload `{"meta": None}` yields `meta == {}`.
  `list_messages` and `get_session` return the messages in insertion order and equal to
  what `create_message` returned.
- **T-03 `test_reads_return_fresh_dicts`**: mutate a dict from `get_session`, one from
  `list_messages` (including `["meta"]["k"]`), and one returned by `create_message`; a
  later `list_messages` shows the original unchanged values and a fresh list each call.
- **T-04 `test_get_by_client_id`**: returns the matching message dict; `None` for an unknown
  client id, an unknown session, or a message whose `client_message_id` is `None`.
- **T-05 `test_unknown_writes_raise_keyerror`**: `create_message` on an unknown session,
  `update_message_status` on an unknown session, and `update_message_status` on an unknown
  message of a real session each raise `KeyError`; afterwards `get_session` shows no
  changes (and the unknown session was not auto-created).
- **T-06 `test_duplicate_session_and_message_ids_raise_integrityerror`**: `create_session`
  twice with the same id raises `sqlite3.IntegrityError` and the first session's messages
  are untouched; `create_message` twice with the same (session, message id) raises
  `sqlite3.IntegrityError` and only one message is stored. (Gate G-9.)
- **T-07 `test_update_message_status_merges_meta_and_bumps_updated_at`**: message with
  `meta {"a": 1}`; `update_message_status("s", "m1", "running")` sets status `running`,
  leaves `meta == {"a": 1}`, and `updated_at >=` the old value;
  `update_message_status("s", "m1", "error", meta={"error": "boom", "a": 2})` gives status
  `error`, `meta == {"a": 2, "error": "boom"}` (shallow merge), `created_at` unchanged.
  `meta=None` and omitting `meta` behave the same.
- **T-08 `test_update_status_and_meta_are_atomic`**: calling `update_message_status("s",
  "m1", "error", meta={"bad": object()})` raises `TypeError` and afterwards the message's
  `status` and `meta` are both unchanged (status did not move without its meta). A
  successful `update_message_status(..., "error", meta={"error": "boom"})` is observed by
  a reader (`list_messages`) with status and meta changed together (never `error` without
  `meta["error"]`).
- **T-09 `test_datetimes_and_meta_round_trip`**: file store at `tmp_path / "t.db"`; create a
  message with `meta {"a": [1, 2, {"b": None}], "s": "é", "f": 1.5, "t": True}`; capture
  the returned dict; reopen; `get_session` returns a dict equal (`==`) to the captured one,
  including `created_at`/`updated_at` as equal naive `datetime` values with microseconds,
  and `meta` equal to the original.
- **T-10 `test_restart_round_trip_file`**: file store at `tmp_path / "r.db"`; create session
  `s`, user message `u1` (client id `c1`), assistant message `a1` (`meta {"reply_to":
  "u1"}`), set `u1` status `completed` with `meta {"updated_by": "inference_worker"}`; also
  create an empty session `e`; reopen; `get_session("s")` returns both messages in order
  with the same ids, roles, content, statuses and metas; `get_session("e") == []`;
  `get_session("nope") is None`; `get_by_client_id("s", "c1")` returns `u1`; a new
  `create_message("s", "m3", ...)` after reopen appends after `a1`.
- **T-11 `test_schema_created_on_open`**: opening a new file store creates tables
  `sessions` and `messages` and `PRAGMA user_version == 1` (checked with a separate
  `sqlite3.connect` to the file); reopening the same file does not error and does not
  remove existing rows.
- **T-12 `test_store_is_usable_across_threads`**: a `:memory:` store created on the main
  thread: a `threading.Thread` creates a session and a message, and the main thread reads
  them (no `sqlite3.ProgrammingError`). Then 8 threads each create 10 messages in one
  session; afterwards `list_messages` returns 80 messages with unique ids and no thread
  reported an exception.
- **T-13 `test_restart_marks_interrupted_messages_as_error`** (WP-3): file store with
  messages in statuses `queued` (with `meta {"x": 1}`), `running`, `completed`, `error`
  (with `meta {"error": "old"}`), `cancelled`; reopen. `queued` and `running` messages are
  now `error` with `meta["error"] == "interrupted by server restart"` (the `queued` one
  still has `x == 1`) and a bumped `updated_at`; the other three are byte-for-byte
  unchanged (status, meta, `updated_at`); content, role and order of all messages are
  unchanged.
- **T-14 `test_restart_recovery_is_idempotent_and_memory_safe`** (WP-3): reopening a second
  time after T-13's setup changes nothing further; opening `":memory:"` and an empty file
  store do not error.

### `tests/test_repos_factory.py` (new; `database.url` parsing and seeding, WP-4)
- **T-15 `test_make_default_repos_defaults_to_independent_memory_stores`**:
  `make_default_repos()` returns a dict whose `"session"` is a `SqliteSessionStore`; two
  calls give stores that do not share sessions (create `s` in one; `get_session("s")` is
  `None` in the other); no file is created in the CWD (`monkeypatch.chdir(tmp_path)`,
  `tmp_path` stays empty).
- **T-16 `test_make_default_repos_honours_file_urls`** (parametrized relative/absolute):
  relative: `monkeypatch.chdir(tmp_path)`, `make_default_repos("sqlite:///./x.db")`;
  absolute: `make_default_repos(f"sqlite:///{tmp_path}/y.db")` (four slashes in total
  because `tmp_path` starts with `/`). The file exists at the expected path after the
  first write, a session written through the store is visible after reopening that path
  with `SqliteSessionStore`, and `make_default_repos("sqlite:///:memory:")` creates no file.
- **T-17 `test_make_default_repos_rejects_unsupported_urls`** (parametrized over
  `"postgresql://u:secret@h/db"`, `"mysql://h/db"`, `"sqlite://"`, `"sqlite:///"`,
  `"http://x"`, `""`): `pytest.raises(ValueError)`; the exception message does not contain
  `secret` (the URL is not echoed).
- **T-18 `test_seed_sample_data_is_idempotent`**: on a file-backed `repos`, calling
  `seed_sample_data(repos)` twice does not raise and `list_messages("demo")` has exactly 1
  message (`id == "msg-1"`, content `"Hello world!"`); after reopening the file and seeding
  again it is still 1.

### `tests/test_main_wiring.py` (new; `app/main.py` honours `database.url`, WP-5)
Both tests monkeypatch, on `app.main`: `init_logging` (no-op lambda, avoids writing
`logs/`), `get_settings` (returns `types.SimpleNamespace(database=types.SimpleNamespace(
url=<url>))`) and `_run_uvicorn` (an `async def` that returns `None`).
- **T-19 `test_main_honours_database_url_and_seed_persists`**: url
  `f"sqlite:///{tmp_path}/m.db"`. `main(["--no-tools", "--seed"])` returns `0`; the file
  exists; opening it with `SqliteSessionStore` shows session `demo` with 1 message. A
  second `main(["--no-tools", "--seed"])` also returns `0` and `demo` still has 1 message
  (restart with seed does not collide).
- **T-20 `test_main_rejects_non_sqlite_url`**: url `"postgresql://h/db"`;
  `pytest.raises(ValueError): main(["--no-tools"])`; `build_services` and `_run_uvicorn`
  are not reached (monkeypatch both to functions that fail the test if called).

### `tests/test_inference_reply.py` (existing file; worker port, WP-1 and WP-4)
The existing tests keep their assertions. In WP-1 the `store` fixture becomes a
read-copying test store (so the old in-place mutation would no longer work); in WP-4 it is
`SqliteSessionStore(":memory:")`. A `_SpyStore` test double records every
`update_message_status(session_id, message_id, status, meta)` call as a tuple, in order,
then delegates.
- **T-21 `test_worker_writes_status_via_update_message_status`**: success path with the
  spy store. For message `u1` the recorded statuses are exactly `["queued", "running",
  "completed"]` in that order (queued is first: see discrepancy 3), and each call's `meta`
  has `updated_by == "inference_worker"`. The reply is created via `create_message` and
  finished by a call `(s1, <reply id>, "completed", None)` (no meta). Final store state:
  `u1` status `completed` with `meta["updated_by"] == "inference_worker"`; reply `meta ==
  {"reply_to": "u1"}`.
- **T-22 `test_error_status_and_meta_written_in_one_call`**: `generate` raises
  `RuntimeError("boom")`. Exactly one recorded call for `u1` has status `error`, and that
  same call's `meta` contains `error == "boom"` and `updated_by == "inference_worker"`;
  no recorded call for `u1` follows it. `OllamaInferenceService` has no attribute
  `_update_message_meta`. Final `u1`: status `error`, `meta["error"] == "boom"`.
- **T-23 `test_unknown_message_write_is_logged_and_worker_survives`** (WP-4; needs the
  real store that raises): `caplog` at ERROR; `svc.enqueue(session_id="s1",
  message_id="ghost", ...)` for a message that does not exist; after `wait_idle(svc)` an
  ERROR record whose message is `"update_message_status failed"` exists (the store's
  `KeyError` was logged, not silent), `svc._worker.is_alive()` is true, and a following
  normal enqueue for `u1` still reaches `completed`.

### `tests/test_single_session_model.py` (existing file; guards, WP-4 to WP-6)
- **T-24 `test_make_default_repos_returns_sqlite_store`** (replaces
  `test_default_repos_names_stable`): `make_default_repos()["session"]` is a
  `SqliteSessionStore`; after `seed_sample_data(repos)`, `list_messages("demo")` has 1
  message. (Until WP-5 it also still asserts `DEFAULT_REPOS` is a dict; WP-5 removes that
  line.)
- **T-25 `test_session_store_protocol_unchanged`** (existing, unchanged): the Protocol's
  public method-name set is still the six names.
- **T-26 `test_protocol_update_message_status_has_optional_meta`** (WP-1): via
  `inspect.signature(SessionStore.update_message_status)`, parameters are `self,
  session_id, message_id, status, meta` and `meta.default is None`; the same holds for
  `SqliteSessionStore.update_message_status` (WP-2 adds that second assertion).
- **T-27 `test_in_memory_store_and_default_repos_removed`** (WP-5): `app.services.repos`
  has no attribute `InMemorySessionStore` and none named `DEFAULT_REPOS`; the text of
  `app/main.py` contains neither name; it does contain `database.url`.
- **T-28 `test_data_layer_removed`** (WP-6): none of `data/__init__.py`, `data/models.py`,
  `data/repos.py`, `data/migrations.py` exists under the repo root; no `.py` file in `app/`
  matches the regex `^\s*(from|import)\s+data\b`. (Do NOT use `import data` as the check:
  a leftover empty `data/` directory would import as a namespace package.)
- **T-29 `test_no_new_runtime_dependency`** (WP-6): `requirements.txt` (lower-cased) does
  not contain `sqlalchemy`.

### Regression gate
The whole existing suite (`tests/test_ws_session.py`, `test_session_rest.py`,
`test_intel_snapshot.py`, `test_messages_helper.py`, `test_tool_calling.py`,
`test_app_factory.py`, `test_logging_consistency.py`, etc.) passes unchanged in behaviour
after every work package; `ruff check app tests` and `black --check app tests` pass.
Total new/changed named tests: 28 (T-01..T-29 except the retained guard T-25).

## 3. Work Packages
Do WPs strictly in order; each leaves the full suite, ruff and black green. Before WP-1
run `./venv-dnd-server/bin/python -m pytest -q` once and note the baseline pass count.
Every WP assumes the open gates in section 4.4 have been accepted by the human.
Formatting: black, line length 100; use `get_logger(__name__)` from
`app.services.logger` if logging (PAT-CODE-001); never log message content or full URLs.

### WP-1: Widen `update_message_status`, port the worker to explicit writes
- **Prerequisites:** none (baseline suite green).
- **Files:**
  - `app/type_defs.py`
  - `app/services/repos.py` (only `InMemorySessionStore.update_message_status`)
  - `app/services/inference_service.py`
  - `tests/test_inference_reply.py`
  - `tests/test_single_session_model.py` (add T-26 first assertion only)
- **Inputs:** the current code described under "Verified facts". The in-memory store still
  exists and is still what everything uses. `tests/test_inference_reply.py` has fixtures
  `svc` and `store` (store = `InMemorySessionStore()` with session `s1` and user message
  `u1` content `hello`) and the helper `wait_idle`.
- **Outputs:**
  1. `app/type_defs.py`: in `class SessionStore(Protocol)` change the method to
     `def update_message_status(self, session_id: str, message_id: str, status: str, meta:
     dict[str, Any] | None = None) -> None: ...` (wrap over lines for black). No other
     Protocol change; the six method names stay.
  2. `app/services/repos.py`: `InMemorySessionStore.update_message_status(self, session_id,
     message_id, status, meta=None)`: same loop as today, additionally `if meta:
     m["meta"] = {**(m.get("meta") or {}), **meta}`. Still a silent no-op for unknown ids
     (this class is removed in WP-5; do not change that behaviour here).
  3. `app/services/inference_service.py`:
     - `_update_message_status(self, store, session_id: str, message_id: str, status: str,
       meta: dict | None = None) -> None`: inside the existing `try/except Exception:
       logger.exception(...)` (keep the same log message `"update_message_status failed"`
       and `extra`) call `store.update_message_status(session_id, message_id, status,
       meta={"updated_by": "inference_worker", **(meta or {})})`. It must NOT call
       `store.get_session` and must NOT mutate any returned dict.
     - Delete `_update_message_meta` entirely.
     - Worker `except Exception as exc:` path: replace the two calls with ONE call
       `self._update_message_status(job.store, job.session_id, job.message_id, "error",
       {"error": str(exc)})`.
     - `enqueue`: move the `self._update_message_status(store, session_id, message_id,
       "queued")` call to BEFORE `self._queue.put_nowait(job)` (inside the same `try`).
       Everything else in `enqueue` is unchanged.
     - `_append_reply`, `_worker_loop` structure, queueing, cancel, shutdown unchanged.
  4. `tests/test_inference_reply.py`: add test double `_CopyingStore(InMemorySessionStore)`
     whose `get_session`, `list_messages` and `get_by_client_id` return `copy.deepcopy` of
     what the parent returns (keeping `None` for an unknown session); add `_SpyStore
     (_CopyingStore)` that appends `(session_id, message_id, status, meta)` to
     `self.calls` and then delegates `update_message_status`. Change the `store` fixture to
     return a `_SpyStore` (session `s1`, message `u1` as before). Add tests T-21 and T-22 as
     specified in section 2 (filter `calls` by `message_id == "u1"`). All existing tests in
     the file keep their assertions and must pass.
  5. `tests/test_single_session_model.py`: add T-26 for the Protocol signature only.
- **Acceptance criteria (restated in full):**
  - With the copying store, a successful job leaves `u1` `completed` with `meta
    ["updated_by"] == "inference_worker"` and a separate `assistant` reply with `meta ==
    {"reply_to": "u1"}`; a failing `generate` leaves `u1` `error` with `meta["error"] ==
    "boom"` (written in one `update_message_status` call together with `updated_by`);
    a pre-cancelled job ends `cancelled`.
  - For `u1` the recorded status order is `queued, running, completed` (queued first).
  - `_update_message_meta` no longer exists; the worker never reads then mutates store
    data.
  - `SessionStore.update_message_status` has the optional `meta` parameter; the
    method-name guard test (T-25) still passes unchanged.
  - Full suite, `ruff check app tests`, `black --check app tests` pass.
- **Tests to run:** `./venv-dnd-server/bin/python -m pytest tests/test_inference_reply.py
  tests/test_single_session_model.py -q`, then the full suite.
- **Patterns used/created:** PAT-ARCH-001 (accepted; uses only Protocol methods),
  PAT-CODE-001 (accepted), PAT-ARCH-002 (accepted; copies out, explicit writes in).

### WP-2: Add `SqliteSessionStore` (additive; `InMemorySessionStore` stays for now)
- **Prerequisites:** WP-1.
- **Files:**
  - `app/services/repos.py` (add the class, imports and helpers only)
  - `tests/test_sqlite_store.py` (new)
  - `tests/test_single_session_model.py` (extend T-26 with the `SqliteSessionStore`
    assertion)
- **Inputs:** WP-1 done. `app/services/repos.py` still has `InMemorySessionStore`,
  `DEFAULT_REPOS`, `make_default_repos`, `seed_sample_data` (leave all four untouched in
  this WP). Messages are dicts with keys `id, client_message_id, role, content, status,
  meta, created_at, updated_at` (naive-UTC `datetime`s from `datetime.utcnow()`).
- **Outputs:** in `app/services/repos.py` add imports `json`, `sqlite3`, `threading` and a
  class `SqliteSessionStore`:
  - `__init__(self, path: str)`: `self._conn = sqlite3.connect(path,
    check_same_thread=False)`; `self._conn.row_factory = sqlite3.Row`; `self._lock =
    threading.Lock()`; execute `PRAGMA foreign_keys = ON`; create schema with `CREATE TABLE
    IF NOT EXISTS`:
    - `sessions(id TEXT PRIMARY KEY, created_at TEXT NOT NULL)`
    - `messages(seq INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
      id TEXT NOT NULL, client_message_id TEXT, role TEXT, content TEXT, status TEXT NOT
      NULL, meta TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      UNIQUE(session_id, id))`
    - `CREATE INDEX IF NOT EXISTS idx_messages_client ON messages(session_id,
      client_message_id)`
    - `PRAGMA user_version = 1`.
  - Private `_now()` returning `datetime.utcnow()` and a private row-to-dict helper that
    builds the message dict (`created_at`/`updated_at` via `datetime.fromisoformat`,
    `meta` via `json.loads`). Public methods MUST NOT call each other while holding the
    lock (a plain `Lock` would deadlock); use private helpers.
  - `get_session(session_id) -> list[dict] | None`: `None` if no `sessions` row, else the
    messages `ORDER BY seq` as fresh dicts (`[]` if none).
  - `create_session(session_id) -> None`: `INSERT INTO sessions` with `created_at =
    _now().isoformat()`; an existing id raises `sqlite3.IntegrityError` (propagates; never
    wipes messages). Commit via `with self._conn:`.
  - `create_message(session_id, message_id, payload) -> dict`: if the session row does not
    exist raise `KeyError(session_id)` (checked before inserting); values: `client_message_id
    = payload.get("client_message_id")`, `role = payload.get("role", "user")`, `content =
    payload.get("content")`, `status = "queued"`, `meta = payload.get("meta") or {}`
    (`json.dumps`), `created_at = updated_at = _now()` (`isoformat()`); insert in one
    transaction; return the dict built from the same values (fresh `meta` copy).
  - `get_by_client_id(session_id, client_message_id) -> dict | None`: first match by `seq`
    for that session; `None` otherwise (including unknown session).
  - `list_messages(session_id) -> list[dict]`: `ORDER BY seq`; `[]` for unknown/empty.
  - `update_message_status(self, session_id, message_id, status, meta=None) -> None`: one
    `with self._conn:` transaction under the lock: select the row's current `meta` for
    (session_id, message_id); none -> `raise KeyError(message_id)`; compute `merged =
    {**json.loads(current), **(meta or {})}` and `json.dumps(merged)` BEFORE the `UPDATE`
    (so a non-serializable meta raises `TypeError` with nothing written); `UPDATE ... SET
    status=?, meta=?, updated_at=?`.
  - `close(self) -> None`: `with self._lock: self._conn.close()`. Not part of the Protocol
    (gate G-10).
  - All SQL is parameterized (`?`), no string formatting of values; no SQL tracing/logging.
  - `tests/test_sqlite_store.py` containing T-01 .. T-12 (T-13 and T-14 are WP-3), each
    store built as `SqliteSessionStore(":memory:")` or under `tmp_path`, closed in a
    fixture/`finally`.
- **Acceptance criteria (restated in full):** `SqliteSessionStore` satisfies the six
  Protocol methods; reads return fresh dicts; unknown-session `create_message` and
  unknown session/message `update_message_status` raise `KeyError`; `get_session` is `None`
  for unknown and `[]` for an empty session; duplicate session or (session, message) ids
  raise `sqlite3.IntegrityError`; datetimes and nested `meta` round-trip exactly through a
  closed and reopened file; a non-serializable `meta` leaves status and meta unchanged;
  the store works from several threads; tables and `user_version = 1` exist after open;
  `update_message_status` signature is `(self, session_id, message_id, status, meta=None)`.
  `InMemorySessionStore`, `DEFAULT_REPOS`, `make_default_repos` and `seed_sample_data` are
  untouched. `app/services/repos.py` contains none of the banned tokens listed under
  "Verified facts". T-01..T-12 and the full suite pass; ruff and black pass.
- **Tests to run:** `./venv-dnd-server/bin/python -m pytest tests/test_sqlite_store.py
  tests/test_single_session_model.py -q`, then the full suite.
- **Patterns used/created:** PAT-ARCH-002 (accepted; this is its first use),
  PAT-ARCH-001, PAT-CODE-001.

### WP-3: Restart recovery of interrupted messages
- **Prerequisites:** WP-2.
- **Files:** `app/services/repos.py`, `tests/test_sqlite_store.py`
- **Inputs:** WP-2 done: `SqliteSessionStore.__init__` creates the schema; statuses in use
  are `queued, running, completed, error, cancelled`.
- **Outputs:**
  1. In `repos.py`: module constant `INTERRUPTED_ERROR = "interrupted by server restart"`.
  2. At the end of `SqliteSessionStore.__init__` (after schema creation, before returning
     to the caller): in ONE transaction, for every message whose `status` is `queued` or
     `running`, set `status = 'error'`, merge `{"error": INTERRUPTED_ERROR}` into its
     existing `meta` (other keys kept), set `updated_at` to now. If at least one row was
     changed, `logger.warning("store.recovered_interrupted", extra={"count": n})` using
     `get_logger(__name__)` (add the import and module-level `logger`); no message content
     or ids in the log.
  3. Tests T-13 and T-14 appended to `tests/test_sqlite_store.py`. To create the pre-restart
     state use `update_message_status` on a file store (e.g. `running`), then `close()` and
     reopen.
- **Acceptance criteria (restated in full):** opening a file store whose messages are
  `queued` or `running` turns exactly those into `error` with `meta["error"] ==
  "interrupted by server restart"`, preserving their other meta keys and bumping
  `updated_at`; `completed`, `error` and `cancelled` messages (status, meta, `updated_at`)
  and all content/role/order are unchanged; a second reopen changes nothing; opening
  `":memory:"` or an empty file works. T-01..T-14 and the full suite pass; ruff/black pass;
  `test_logging_consistency` still passes.
- **Tests to run:** `./venv-dnd-server/bin/python -m pytest tests/test_sqlite_store.py -q`,
  then the full suite.
- **Patterns used/created:** PAT-ARCH-002 (accepted), PAT-CODE-001 (accepted).

### WP-4: `database.url` parsing, `make_default_repos(url)`, idempotent seed, repoint tests
- **Prerequisites:** WP-3.
- **Files:**
  - `app/services/repos.py`
  - `tests/conftest.py`
  - `tests/test_inference_reply.py`
  - `tests/test_messages_helper.py`
  - `tests/test_single_session_model.py`
  - `tests/test_repos_factory.py` (new)
- **Inputs:** WP-3 done. `InMemorySessionStore` and `DEFAULT_REPOS` still exist and
  `app/main.py` still imports `DEFAULT_REPOS` (do NOT edit `main.py` or remove either name
  in this WP). `tests/conftest.py` fixtures: `app`, `client`, `stub_svc`, `session_store`
  (currently `InMemorySessionStore()`), `stub_client`.
- **Outputs:**
  1. `app/services/repos.py`:
     - private `_sqlite_path(database_url: str) -> str`: if the URL starts with
       `"sqlite:///"` and the remainder is non-empty, return the remainder (`":memory:"`
       stays `":memory:"`; `"./dnd.db"` stays relative to the CWD; `"/abs/p.db"` comes from
       `sqlite:////abs/p.db`); otherwise `raise ValueError("Unsupported database url; only
       sqlite:///<path> and sqlite:///:memory: are supported")` without including the URL.
     - `make_default_repos(database_url: str = "sqlite:///:memory:") -> dict[str, Any]`
       returns `{"session": SqliteSessionStore(_sqlite_path(database_url))}`.
     - `seed_sample_data(repos)`: return immediately if `store.get_session("demo") is not
       None`; otherwise unchanged behaviour.
     - `InMemorySessionStore` and `DEFAULT_REPOS` untouched.
  2. `tests/conftest.py`: import `SqliteSessionStore`; `session_store` fixture becomes a
     yield fixture: `store = SqliteSessionStore(":memory:")`, `yield store`, `store.close()`.
     Drop the unused `InMemorySessionStore` import. Other fixtures unchanged.
  3. `tests/test_inference_reply.py`: `store` fixture builds `SqliteSessionStore(":memory:")`
     (session `s1`, message `u1`) and closes it after the test; delete `_CopyingStore`;
     `_SpyStore` now subclasses `SqliteSessionStore` (its `__init__` calls
     `super().__init__(":memory:")` and sets `self.calls = []`) and is used by T-21/T-22;
     add T-23. Existing tests keep their assertions.
  4. `tests/test_messages_helper.py`: replace `InMemorySessionStore` with
     `SqliteSessionStore(":memory:")` (import and the `_store_with_session` helper/type
     hint); assertions unchanged.
  5. `tests/test_single_session_model.py`: import `SqliteSessionStore` (keep importing
     `DEFAULT_REPOS` and `InMemorySessionStore` only if still used); replace
     `test_default_repos_names_stable` with T-24 (still asserting `DEFAULT_REPOS` is a
     `dict`).
  6. `tests/test_repos_factory.py`: T-15..T-18.
- **Acceptance criteria (restated in full):** `make_default_repos()` returns a
  `SqliteSessionStore` over `:memory:` (independent per call, no file created);
  `make_default_repos("sqlite:///./x.db")` and `"sqlite:////abs/path.db"` open those files;
  any other URL (`postgresql://...`, `mysql://...`, `sqlite://`, `sqlite:///`, `http://x`,
  `""`) raises `ValueError` whose message does not contain the URL; `seed_sample_data` can
  run repeatedly (even after reopening a file) leaving exactly one `demo` message; every
  existing test that used the in-memory store now runs against `SqliteSessionStore
  (":memory:")` and passes (REST, WS and snapshot suites unchanged in assertions); T-15..T-18,
  T-21..T-24 pass; ruff and black pass; no test creates `./dnd.db`.
- **Tests to run:** full suite `./venv-dnd-server/bin/python -m pytest -q`; then, to confirm
  no stray file, check that no `dnd.db` appeared in the repo root.
- **Patterns used/created:** PAT-ARCH-002 (accepted; items 3 and 6), PAT-ARCH-001.

### WP-5: Wire `app/main.py` to `database.url`; remove `InMemorySessionStore` and `DEFAULT_REPOS`
- **Prerequisites:** WP-4.
- **Files:**
  - `app/main.py`
  - `app/services/repos.py`
  - `tests/test_single_session_model.py`
  - `tests/test_main_wiring.py` (new)
- **Inputs:** WP-4 done; nothing in `tests/` references `InMemorySessionStore` any more
  (verify by opening the four files named in "Verified facts" before deleting the class);
  `app/main.py` lines: `from app.services.repos import DEFAULT_REPOS, make_default_repos,
  seed_sample_data` and the `try: repos = DEFAULT_REPOS if DEFAULT_REPOS else
  make_default_repos() ... except Exception: ... repos = make_default_repos()` block;
  `app.config.get_settings()` returns settings with `.database.url`.
- **Outputs:**
  1. `app/main.py`: add `from app.config import get_settings` (keep imports sorted for
     ruff `I`); change the repos import to `make_default_repos, seed_sample_data`; replace
     the whole `try/except` block with `repos = make_default_repos(get_settings().database.url)`,
     NOT inside any `try/except`, so an unsupported URL or an unopenable path fails startup
     loudly (`ValueError` / `sqlite3.OperationalError` propagate out of `main`). The
     `--seed` block, `build_services`, `create_app`, uvicorn run and shutdown code stay
     as they are. Do not log the URL.
  2. `app/services/repos.py`: delete `class InMemorySessionStore` and `DEFAULT_REPOS`; remove
     any import that became unused (`datetime` and `Any` are still used by
     `SqliteSessionStore` and `make_default_repos`, so expect to keep them) and keep the
     file ruff-clean. Update the header comment that says "Repo factory functions expected
     by app/main.py" only if it is now wrong.
  3. `tests/test_single_session_model.py`: remove the `DEFAULT_REPOS` and
     `InMemorySessionStore` imports and the `DEFAULT_REPOS` assertion from T-24; add T-27.
  4. `tests/test_main_wiring.py`: T-19 and T-20.
- **Acceptance criteria (restated in full):** `python -c "import app.main"` style import
  works (covered by T-19); `main([...])` with `database.url = sqlite:///<tmp>/m.db` creates
  and uses that file and, with `--seed`, persists session `demo` (a second run does not
  fail and keeps 1 message); `main([...])` with a non-sqlite URL raises `ValueError` before
  `build_services` or uvicorn start; `app.services.repos` no longer defines
  `InMemorySessionStore` or `DEFAULT_REPOS`, and `app/main.py` mentions neither;
  `settings.json` and `app/config.py` are unchanged; `database.echo` is still unwired.
  Full suite, ruff, black pass.
- **Tests to run:** `./venv-dnd-server/bin/python -m pytest tests/test_main_wiring.py
  tests/test_single_session_model.py -q`, then the full suite.
- **Patterns used/created:** PAT-ARCH-002 (accepted; item 6: store built in `main.py`, not
  at import), PAT-ARCH-001 (item 6: no silent fallback), PAT-CODE-001.

### WP-6: Delete `data/`, record the recovery commit, refresh docs
- **Prerequisites:** WP-5.
- **Files:**
  - delete `data/__init__.py`, `data/models.py`, `data/repos.py`, `data/migrations.py`
    (and remove the leftover gitignored `data/__pycache__` and the empty `data/`
    directory)
  - `.github/copilot-instructions.md`
  - `docs/specs/SPEC-0005-persistence-sqlite-session-store.md` (section 4 commit line only)
  - `tests/test_single_session_model.py`
- **Inputs:** WP-5 done; nothing in `app/` or `tests/` imports `data` (verified
  2026-10-11).
- **Outputs:**
  1. The four `data/*.py` files are deleted. Do not move or copy them (no quarantine).
  2. `.github/copilot-instructions.md`: (a) the `app/services/repos.py` bullet now says it
     holds `SqliteSessionStore` (stdlib `sqlite3`, path from `settings.json`
     `database.url`, default `sqlite:///./dnd.db`, `:memory:` in tests) built by
     `make_default_repos(url)` in `app/main.py`, and no longer mentions `InMemorySessionStore`
     or `DEFAULT_REPOS`; (b) delete the "Known gaps" bullet about `data/` and replace it
     with one line: `data/` (the unused SQLAlchemy layer) was deleted under REQ-0005;
     recover its models for REQ-0015 with `git show <sha>:data/models.py` using the SHA
     recorded in SPEC-0005 section 4; (c) delete the sentence in the Dev workflow lint
     bullet saying `data/` is excluded from lint; (d) in the Tests bullet, say the fixtures
     use `:memory:` SQLite repos; (e) in the Dev workflow note that the first real run
     creates a gitignored `dnd.db` in the working directory and that a restart keeps
     sessions.
  3. `docs/specs/SPEC-0005-...md` section 4: confirm or update the "last commit containing
     `data/`" value (see below).
  4. `tests/test_single_session_model.py`: add T-28 and T-29.
  5. Optional, only if the human has accepted PAT-ARCH-002: fill its "Examples" with file
     references to `app/services/repos.py`. Do NOT change its status and do NOT edit
     PAT-ARCH-001 or PAT-CODE-001.
- **Acceptance criteria (restated in full):** none of the four `data/*.py` files exist;
  no file in `app/` imports `data`; `requirements.txt` has no `sqlalchemy`;
  `.github/copilot-instructions.md` no longer mentions `InMemorySessionStore`,
  `DEFAULT_REPOS`, a WIP `data/` layer, or a `data/` lint exclusion, and points to the
  recovery SHA; T-28 and T-29 pass; full suite, `ruff check app tests`,
  `black --check app tests` pass; `dupe-scan.sh` (optional) shows nothing new.
- **Tests to run:** `./venv-dnd-server/bin/python -m pytest -q`, `ruff check app tests`,
  `black --check app tests`.
- **Patterns used/created:** none new (docs and deletion).

## 4. Other Details

### 4.1 Risks and rollback
- **Risks:**
  - *Latent enqueue race* (discrepancy 3): mitigated in WP-1 and asserted by T-21.
  - *Threading:* one connection plus one non-reentrant lock; a public method calling
    another public method deadlocks. WP-2 forbids it. T-12 covers cross-thread use.
  - *Event-loop blocking:* async routes call a synchronous store; each call is
    milliseconds (accepted by ADR-0003; one household).
  - *Unclosed connections* in tests (`make_default_repos()` in fixtures never closes):
    Python 3.13 may emit `ResourceWarning`; harmless, not errors.
  - *Stray `dnd.db`:* a test or script that runs `make_default_repos(get_settings().
    database.url)` writes to the working directory. Only `tests/test_main_wiring.py`
    touches `main`, and it patches `get_settings` to a `tmp_path` URL.
  - *Persisted data outlives code:* the two-table schema and `PRAGMA user_version = 1` are
    now a commitment; a schema change needs a manual `ALTER` branch (ADR-0003).
  - *`create_session` on an existing id raises* (`sqlite3.IntegrityError`) whereas the
    in-memory store silently reset the session; REST uses fresh uuids so it never
    collides (gate G-9).
  - *Restart recovery marks in-flight user messages `error`:* a client polling after a
    restart sees `error` rather than waiting forever (gate G-4).
  - *Uncommitted deletion of `data/`:* the recovery SHA below assumes `data/` is tracked at
    that commit; this spec could not run git to confirm (see 4.2).
- **Rollback plan:** every WP is one reviewable change. Revert WP-6 (restore `data/` from
  git) / WP-5 / WP-4 / WP-3 / WP-2 / WP-1 in reverse order, or revert the whole series;
  `InMemorySessionStore` is recoverable from git. A created `dnd.db` is gitignored and can
  simply be deleted (or moved aside to start from empty). Nothing else (settings schema,
  API, dependencies) changes, so rollback needs no migration.

### 4.2 `data/` recovery record
- Resolution: **deleted** (all four files). `data/models.py` (~890 lines, ~30 SQLAlchemy
  tables, the REQ-0015 domain) stays recoverable from git.
- Last commit known to contain `data/`: `0365f2bf23789f85fef4b89595abd6056b35a1a5`
  (read from `.git/refs/heads/main` on 2026-10-11, HEAD at the time of writing; git was not
  run). Recover with `git show 0365f2bf23789f85fef4b89595abd6056b35a1a5:data/models.py`.
  WP-6 must confirm this SHA still contains `data/` (nothing else changes `data/` in
  WP-1..WP-5) or replace it with the parent of the deletion commit.

### 4.3 Patterns applied/created
| Pattern | Status | Use |
|---|---|---|
| PAT-ARCH-001 | accepted | Applied unchanged: Protocol is the only API; no silent fallbacks (drives WP-5's removal of the `try/except` fallback). Its Context/Consequences wording is now outdated; the four changes in ADR-0003 "Pattern Impact" are flagged for human sign-off (gate G-8), NOT applied here |
| PAT-CODE-001 | accepted | Applied: `get_logger`, no PII/URLs/message content in logs. Its "(and eventually `data/`...)" wording becomes outdated; change flagged (gate G-8), NOT applied |
| PAT-ARCH-002 | accepted | Created by the architect; first used in WP-2..WP-5. Acceptance is gate G-7 |

No new patterns were authored by this spec. Existing `spec/` category: none exist, so the
SPEC-0004 structure was followed as the closest format example.

### 4.4 Gates (all accepted by the human on 2026-10-11)
Implementation of any work package MUST NOT start until the human has accepted G-1..G-8;
G-9..G-12 are spec-added details that need acknowledgement before the WP that contains them.
- **G-1** ADR-0003 and Option A (stdlib `sqlite3`); ADR-0003 is `accepted`. (blocks all)
- **G-2** Deleting ALL of `data/` (not quarantine, not keep-as-WIP). (blocks WP-6)
- **G-3** Widening `SessionStore.update_message_status(..., meta: dict | None = None)`.
  (blocks WP-1)
- **G-4** Restart recovery rule: `queued`/`running` messages become `error` with
  `meta.error = "interrupted by server restart"` when a store is opened. (blocks WP-3)
- **G-5** Replacing `InMemorySessionStore` with `SqliteSessionStore` and removing
  `DEFAULT_REPOS` (names stabilised by REQ-0004 change). (blocks WP-4, WP-5)
- **G-6** Leaving `database.echo` unwired (PII concern; REQ-0012 removes it). (non-code)
- **G-7** Accepting PAT-ARCH-002 (accepted).
- **G-8** The PAT-ARCH-001 and PAT-CODE-001 wording changes listed in ADR-0003 "Pattern
  Impact" (requires architect plus human sign-off; this spec does not edit them).
- **G-9** (spec-added) `create_session` on an existing id raises `sqlite3.IntegrityError`
  instead of silently resetting or silently ignoring. (WP-2, T-06)
- **G-10** (spec-added) A `close()` method on `SqliteSessionStore`, outside the Protocol,
  used by the restart tests and fixtures (two or more call sites). (WP-2)
- **G-11** (spec-added) `enqueue` writes status `queued` before queueing the job (race fix,
  discrepancy 3). (WP-1)
- **G-12** (spec-added) Removing the `try/except` fallback around repo creation in
  `app/main.py` so a bad `database.url` stops startup (discrepancy 2). (WP-5)

### 4.5 Non-goals (out of scope under REQ-0005)
- Campaign/character/quest domain, tables or models (REQ-0015); no SQLAlchemy, no ORM, no
  Alembic or migration framework.
- Prompt pipeline (REQ-0006); streaming, the WS event protocol, WS polling design and
  `cancel` (REQ-0007); tools, including `tools/clear.py`'s `session.commit()` (REQ-0008);
  auth/CORS (REQ-0009); API contract, JSON datetime format, pydantic style (REQ-0010);
  repo hygiene, removal of the unused `database.echo` key, `.github` cleanup (REQ-0012).
- Changes to `ws.py`, `messages.py`, `session.py`, `intelligence.py`, `config.py`,
  `settings.json`, `build_services.py`, `deps.py`, `factory.py` (none needed).
- Wiring `database.echo`, SQL tracing, WAL/pragma tuning, connection pooling, backups or
  export, multi-process access, creating missing parent directories for the `.db` path,
  URL query parameters, and any production-hardening concern (docs/constraints.md).
- Re-queueing interrupted messages after a restart (they become `error`; the user may
  resend).
- Editing the accepted patterns PAT-ARCH-001 / PAT-CODE-001, ADR-0003, or the backlog and
  requirements log (done by other roles).

### 4.6 Requirement traceability
| REQ-0005 MUST | Work package(s) | Test(s) |
|---|---|---|
| Sessions and messages survive a server restart | WP-2, WP-3, WP-4, WP-5 | T-09, T-10, T-13, T-14, T-19 |
| Single Protocol implementation persists to durable local storage | WP-2, WP-5 (removes the other) | T-01..T-12, T-24, T-27 |
| Keeps the uuid session-id model | WP-2 (opaque string ids, no coercion) | T-01, T-10; existing REST/WS/snapshot suites (uuid ids, unknown id `"1"` still 404/1008) |
| Keeps the no-silent-no-op contract | WP-2 (`KeyError`), WP-1/WP-4 (worker logs, not silent) | T-05, T-06, T-08, T-23 |
| Technology choice recorded in an ADR; any new runtime dependency justified | ADR-0003 (accepted via G-1); no new dep | T-29 |
| `data/` layer resolved | WP-6 (deleted; SHA recorded in 4.2) | T-28 |
| `database.url` honoured (or removed) | WP-4, WP-5 | T-15, T-16, T-17, T-19, T-20 |
| Worker in-place mutation ported to explicit update methods | WP-1 | T-21, T-22, T-26 |
| Tests run without network or Ollama | all WPs (`:memory:` / `tmp_path`, stub `generate`, `FakeInference`) | whole suite; no test opens a socket |
| Out-of-scope domains NOT changed | section 4.5; WP file lists exclude them | regression gate; `test_single_session_model` and `test_logging_consistency` guards |
