---
id: ADR-0003
status: accepted
date: 2026-10-11
requirement: REQ-0005
supersedes: null
superseded_by: null
---

# Persist sessions with a stdlib `sqlite3` implementation of the `SessionStore` Protocol

## Context
REQ-0005 (see [docs/requirements/LOG.md](../requirements/LOG.md)) requires sessions and
messages to survive a server restart. The one `SessionStore` implementation must persist
to durable local storage. The REQ-0004 uuid session-id model and its no-silent-no-op
contract must stay. The technology choice must be recorded in an ADR, and any new runtime
dependency must be justified. The unimportable `data/` layer must be resolved.
`settings.json` `database.url` must be honoured or removed. The worker's in-place
mutation of dicts returned by the store must keep working or be ported to explicit update
methods. Tests must run without network or Ollama.

Applicable patterns: [PAT-ARCH-001](../patterns/architecture/PAT-ARCH-001-session-store-single-api.md)
(accepted; "a new backend implements the Protocol; callers do not change"; its
Consequences already anticipate update methods for backends that return copies) and
[PAT-CODE-001](../patterns/code/PAT-CODE-001-centralized-logging.md) (accepted; logging,
no PII in logs).

Two ADR triggers apply: there are several viable approaches, and one of them (B) adds a
new dependency that is hard to reverse. A third trigger is borderline: the Protocol
signature and the store's live-dict contract change (cross-cutting convention).

**Verified facts (tree on 2026-10-11):**

| # | Fact | Where |
|---|---|---|
| F1 | All session state is in `InMemorySessionStore` (a dict of lists of dicts). `get_session`/`list_messages` return the **live** list. `create_message` on an unknown session raises `KeyError` (dict index). `update_message_status` silently no-ops when the id is unknown | `app/services/repos.py` |
| F2 | `DEFAULT_REPOS` is built at import time. `main.py` always uses it (`DEFAULT_REPOS if DEFAULT_REPOS else ...`, which is always truthy) | `app/services/repos.py`, `app/main.py` |
| F3 | The worker's `_update_message_status` and `_update_message_meta` call `store.get_session()` and **mutate the returned dicts** (`status`, `meta.updated_by`, `meta.error`). They do not bump `updated_at`. `_append_reply` already uses only Protocol methods (`create_message` + `update_message_status`) | `app/services/inference_service.py` |
| F4 | On error the worker writes `status="error"` and then, as a separate step, `meta.error`. `ws.py` `_wait_for_terminal` polls for a terminal status and reads `meta.error` (falling back to `"Inference failed"`). This leaves a small read-between-writes window | `inference_service.py`, `app/api/v1/ws.py` |
| F5 | Readers only read: `session.py` (list/get/status), `ws.py` (polls `list_messages`, deep-copies), `messages.py` (`build_snapshot` deep-copies, `submit_user_message` returns the created dict). None of them rely on identity or mutation | `app/api/v1/*.py`, `app/services/messages.py` |
| F6 | The store is touched from several threads: the worker thread, the event-loop thread (async routes, WS), Starlette's threadpool (sync `def` routes such as `snapshot_session`) and the test thread (tests call `session_store.create_message(...)` directly while a `TestClient` is open). By default `sqlite3` raises `ProgrammingError` when a connection is used outside its creating thread (`check_same_thread=True`) | `intelligence.py`, `tests/test_ws_session.py` |
| F7 | Messages hold naive-UTC `datetime` values (`datetime.utcnow()`), and `MessageResp` serializes them. Python 3.12+ deprecates `sqlite3`'s default datetime adapters, and `json` cannot encode `datetime` | `repos.py`, `app/schemas/v1.py` |
| F8 | `sqlalchemy` is **not** in `requirements.txt`; it is in the venv only incidentally. The declared stack is FastAPI/starlette/pydantic/httpx/uvicorn | `requirements.txt` |
| F9 | `data/__init__.py` does `from ...data import models, repos`, so `import data` fails. Nothing in `app/` or `tests/` imports `data`. CI lints only `app tests` | `data/__init__.py`, `.github/workflows/ci.yml` |
| F10 | `data/models.py` is ~890 lines and ~30 SQLAlchemy tables (campaigns, characters, quests, world...). Its session model is `SessionRun`/`SessionEntry` with **int** PKs, a NOT NULL `campaign_id` FK, and entries with no `role`/`status`/`meta`/`client_message_id`, which is incompatible with the REQ-0004 uuid message model. `.github/copilot-instructions.md` records "real undefined-name errors" in it | `data/models.py` |
| F11 | `data/repos.py` holds four more int-id in-memory repos (Character/Quest/Game/Session). It is the fourth duplicate repo that ADR-0002 deferred to this REQ. It has no consumers | `data/repos.py`, ADR-0002 table |
| F12 | `data/migrations.py` reads `DATABASE_URL` env or a nonexistent `assets.config`, defaults to `sqlite:///./dev.db` (not `dnd.db`), and offers only `create_all`/`drop_all` (no versioning) | `data/migrations.py` |
| F13 | `settings.json` `database.url = "sqlite:///./dnd.db"` and `database.echo = false` are typed in `DatabaseSettings` but read nowhere. `*.db` is gitignored. `config.py` already supports an env override such as `DATABASE__URL` | `settings.json`, `app/config.py`, `.gitignore` |
| F14 | Guard tests from REQ-0004: `test_session_store_protocol_unchanged` asserts the Protocol's **method-name set**, and `test_default_repos_names_stable` asserts `DEFAULT_REPOS` is a dict and that `make_default_repos()["session"]` is an `InMemorySessionStore`. `conftest.py`, `test_inference_reply.py` and `test_messages_helper.py` construct `InMemorySessionStore()` directly | `tests/` |

Out of scope (requirement guard): campaign/character/quest domain (REQ-0015), prompt
pipeline (REQ-0006), streaming (REQ-0007), tools (REQ-0008; `tools/clear.py`'s
`session.commit()` stays as it is), auth/CORS (REQ-0009), API contract and the JSON
datetime format (REQ-0010), repo hygiene (REQ-0012). Production hardening is a
non-goal (constraints.md).

## Decision Drivers
Weights: High = 3, Medium = 2, Low = 1 (same scale as ADR-0002). Maximum total 95.

| Dimension | Weight | Why it matters here |
|---|---|---|
| Simplicity / smallest-edit fit | High (3) | Constraint 1. Two tables' worth of data (sessions, messages) |
| Reversibility | High (3) | From now on, data outlives the code: the on-disk format becomes a commitment |
| Maintainability for one part-time person | High (3) | The store is the hub every transport and the worker thread hits |
| Reuse of existing patterns/dependencies | Medium (2) | Constraint 3: stdlib before new deps. PAT-ARCH-001's Protocol seam; existing `database.url` key |
| Fun / learning value | Medium (2) | Constraint 5 |
| Performance / scalability | Low (1) | One household, LLM calls take seconds; de-prioritized |
| Security hardening beyond sane defaults | Low (1) | Local file; parameterized queries are the sane default |
| **Requirement fidelity** (added) | High (3) | The core MUSTs: durable across restart **and crash**; exact `datetime` round-trip (F7); uuid model and no silent no-ops kept; `database.url` honoured or removed; worker writes not lost (F3); tests offline. An option that fails a MUST is disqualified, whatever its total |
| **Forward fit with REQ-0015** (added) | Low (1) | Campaign data will need storage next. Low weight because constraint 2 forbids designing for it now; tie-breaker only |

## Considered Options
- **A - stdlib `sqlite3` store.** A `SqliteSessionStore` class in `app/services/repos.py`
  implements the existing Protocol over two tables (`sessions`, `messages`). One
  connection (`check_same_thread=False`) guarded by a `threading.Lock`. Reads return fresh
  dicts. `meta` is stored as JSON TEXT and datetimes as ISO-8601 TEXT. The file path comes
  from `database.url`. Tests use `:memory:`. No new dependency.
- **B - slimmed SQLAlchemy store.** Add `sqlalchemy` to `requirements.txt`. Write a new,
  small ORM/Core model for the same two tables, an engine built from `database.url`, and
  a session-per-call store that converts rows to dicts for the Protocol.
- **C - wire `data/` as-is.** Fix `data/__init__.py`, add `sqlalchemy`, run
  `data/migrations.py` `create_all`, and adapt `SessionRun`/`SessionEntry` behind the
  Protocol.
- **D - status quo store + JSON-file snapshot.** Keep `InMemorySessionStore` (live dicts)
  and rewrite the whole store to a JSON file (temp file + `os.replace`) on every write;
  load it at startup. Remove `database.url` (it is not a JSON path). Pure "do nothing" is
  disqualified by the requirement-fidelity gate (nothing survives a restart) and is not
  scored further.

All options except "do nothing" need the same worker port (F3). Once a write path
persists, a direct dict mutation either does nothing (A, B, C return copies) or is never
saved (D).

## Rubric Scoring
Scores are 1 (poor) to 5 (strong). Weighted total = sum of (score x weight).

| Option | Simplicity (3) | Reversibility (3) | Maintainability (3) | Reuse (2) | Fun / learning (2) | Performance (1) | Security (1) | Requirement fidelity (3) | Forward fit REQ-0015 (1) | **Weighted total** |
|---|---|---|---|---|---|---|---|---|---|---|
| **A** sqlite3 | 4: one ~100-150 line class replaces the ~60-line `InMemorySessionStore`; worker port is a net deletion; no ORM/engine/session concepts. Not 5: hand-written SQL plus row<->dict mapping | 4: the Protocol is the seam (only `repos.py` + `main.py` know SQLite); the `.db` file opens in any SQLite tool and in SQLAlchemy later via the same `sqlite:///` URL; the schema is two tables | 4: stdlib only, plain readable SQL, one explicit lock; manual `ALTER` (versioned by `PRAGMA user_version`) if the schema ever changes | 4: reuses the Protocol, `DatabaseSettings.url` as-is, `*.db` gitignore, the env override; no new dep (constraint 3 satisfied outright) | 4: real SQL, transactions, and the thread rules of `sqlite3` (F6) are worthwhile learning; less "framework" learning than B | 4: indexed per-session reads; one commit per write is milliseconds next to multi-second LLM calls | 3: parameterized queries; local file; neutral | 5: every committed write survives a crash; ISO-8601 TEXT round-trips naive datetimes exactly (F7); KeyError on unknown ids keeps "no silent no-op"; honours `database.url`; `:memory:` keeps tests offline and off disk | 4: REQ-0015 can add tables to the same file/connection, and a relational store fits | **78** |
| **B** SQLAlchemy | 3: new dep plus engine, models, session handling for the same two tables; ORM rows still converted to dicts for the Protocol | 3: the dep itself is removable, but ORM/session idioms spread into code, and the backlog flags a new dep as hard to reverse | 3: SQLAlchemy 2.x is a large API surface for one part-timer; session-per-thread rules for the worker; version churn (2.1.x in venv) | 3: `database.url` and `echo` map natively (a plus), but adds a runtime dep where stdlib suffices (constraint 3 "SHOULD avoid") | 5: learning the main Python ORM, which `data/models.py` shows the author was interested in | 4: same SQLite underneath | 3: neutral | 4: meets every MUST, but the dependency justification is weak for two tables (F8) | 5: an ORM pays off with REQ-0015's many related tables; Alembic path | **67** |
| **C** wire `data/` | 1: broken package (F9), ~890 lines/~30 tables with known undefined names (F10), plus an adapter from int `SessionRun`/`SessionEntry` to uuid messages; plus the new dep | 2: persists a 30-table schema immediately; `migrations.py` has no versioning, only `create_all`/`drop_all` (F12) | 1: one person maintaining hundreds of untested ORM lines, most unused until REQ-0015 | 3: reuses code already in the repo, but that code is broken and undeclared | 2: mostly debugging WIP schema rather than learning | 3: neutral | 3: neutral | 1: int, campaign-scoped sessions contradict REQ-0004 (uuid); fitting them requires changing the campaign domain (REQ-0015, forbidden); `migrations.py` ignores `settings.json` (F12) | 3: has campaign tables, but REQ-0015 must redesign them anyway | **34** |
| **D** JSON snapshot | 4: keeps `InMemorySessionStore`; ~30-40 lines of load/save; still needs the worker port | 5: a plain JSON file, no schema at all | 3: custom datetime encode/decode (F7) keyed by field name; a lock around dump/load across 4 threads (F6); whole-file rewrite on every one of the ~6 writes per exchange | 4: stdlib `json`, keeps the existing class; but `database.url` must be removed (a settings-schema change) | 2: little new to learn | 2: O(total history) rewrite per status change; grows without bound over a long campaign | 3: neutral | 3: survives restart; crash safety depends on correct temp+replace; datetime fidelity depends on custom code; `database.url` removed (allowed but a loss) | 2: does not extend to a relational campaign domain; would be replaced by REQ-0015 | **64** |

Totals check (weights 3,3,3,2,2,1,1,3,1):
A = 12+12+12+8+8+4+3+15+4 = **78**; B = 9+9+9+6+10+4+3+12+5 = **67**;
D = 12+15+9+8+4+2+3+9+2 = **64**; C = 3+6+3+6+4+3+3+3+3 = **34**.

Sensitivity: if Fun/learning were weighted High (3), B would reach 72 and A 82; A still
wins. If Forward fit were Medium (2), B would reach 72 and A 82; A still wins. A loses
only if SQLAlchemy is treated as already-approved stack, which F8 contradicts.

## Decision Outcome
Choose **Option A: a stdlib `sqlite3` implementation of the `SessionStore` Protocol.**
It wins on the weighted rubric (78 vs 67 / 64 / 34), meets every REQ-0005 MUST, and adds
no dependency (constraint 3: stdlib suffices for two tables).

### 1. The store
- `app/services/repos.py`: `InMemorySessionStore` is **replaced** by `SqliteSessionStore(path: str)`
  (path required; `":memory:"` allowed). One store implementation, as the requirement
  says. Tests run the **same** class against `:memory:`, so production code is what gets
  tested.
- Schema (created with `CREATE TABLE IF NOT EXISTS` on open; `PRAGMA user_version = 1`
  set so a later change can tell versions apart; no migration framework):
  - `sessions(id TEXT PRIMARY KEY, created_at TEXT NOT NULL)`
  - `messages(seq INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
    id TEXT NOT NULL, client_message_id TEXT, role TEXT, content TEXT, status TEXT NOT NULL,
    meta TEXT NOT NULL /* JSON object */, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(session_id, id))`, plus an index on `(session_id, client_message_id)`.
    Order is `seq` (insertion order, same as the list today). Message ids stay unique
    per session, as in the in-memory store.
- Values: `datetime` <-> ISO-8601 TEXT via `isoformat()` / `datetime.fromisoformat()`
  (exact round-trip of today's naive-UTC values; no change to the API's JSON output,
  which belongs to REQ-0010). `meta` <-> JSON TEXT (`json.dumps`/`json.loads`; request
  meta already arrives as JSON).
- Threads (F6): one `sqlite3.connect(path, check_same_thread=False)` per store, with every
  public method running under one `threading.Lock` and committing each write (`with
  conn:`). This also removes the "worker writes without a lock" exposure ADR-0002 accepted.
- Durability: each write commits, so data survives a kill as well as a clean restart. No
  WAL or pragma tuning (no performance need).
- No silent no-ops: `create_message`, `update_message_status` and any other write on an
  unknown session or message raises `KeyError` (today's `create_message` already raises
  `KeyError`). Reads keep REST's rule: `get_session` returns `None` for an unknown
  session and `[]` for an empty one. The worker already wraps its status writes in
  `try/except` + `logger.exception`, so the error is logged, not silent.
- Restart recovery (SHOULD; needs human acceptance, see the list at the end): on open, any
  message left `queued` or `running` (its in-memory job died with the old process) is set
  to `error` with `meta.error = "interrupted by server restart"`. This uses the existing
  status vocabulary (REQ-0003). Otherwise such messages would report `queued` forever.

### 2. Live dicts vs update methods: port the worker, widen one Protocol method
- Reads return **fresh dicts**. Mutating a returned dict changes nothing. All writes go
  through Protocol methods.
- The `SessionStore` Protocol keeps its **six method names**. One signature changes:
  `update_message_status(session_id, message_id, status, meta: dict[str, Any] | None = None) -> None`.
  It sets `status`, shallow-merges `meta` into the stored meta, and bumps `updated_at`, all
  in **one transaction**.
  - Why widen this method instead of adding `update_message_meta`: every worker meta
    write happens together with a status write (`updated_by` with every status; `error`
    with `"error"`). One atomic call also closes the F4 window, so the WS can no longer
    see `status="error"` before `meta.error` is written. The method-name guard test
    (F14) stays valid, and no second write API is added (PAT-ARCH-001: "keep it small").
- `app/services/inference_service.py`: `_update_message_status(store, sid, mid, status,
  meta=None)` calls `store.update_message_status(sid, mid, status, meta={"updated_by":
  "inference_worker", **(meta or {})})` inside the existing try/except. The error path
  becomes a single call with `meta={"error": str(exc)}`. `_update_message_meta` is
  deleted. Behaviour is preserved: the user message ends with `meta.updated_by` (and
  `meta.error` on failure), and the reply's meta stays exactly `{"reply_to": ...}`. The
  only visible change is that `updated_at` now bumps on worker status changes (more
  accurate, not a contract change).
- `ws.py`, `messages.py`, `session.py`, `intelligence.py`: **no change needed** (F5).
  Their existing deep copies become redundant but harmless; leave them (smallest edit).

### 3. `database.url` is honoured, in `app/main.py`
- Key: `database.url` (`DatabaseSettings.url` in `app/config.py`). Its value in
  `settings.json` stays `"sqlite:///./dnd.db"`. Env override `DATABASE__URL` works through
  the existing loader.
- `app/main.py` replaces the `DEFAULT_REPOS` branch with
  `make_default_repos(get_settings().database.url)`. `make_default_repos(database_url: str
  = "sqlite:///:memory:")` keeps a no-arg form for tests (`conftest.py`,
  `test_tool_calling.py`). It parses only `sqlite:///<path>` (relative to the CWD, like
  `settings.json` itself; `sqlite:////abs/path` for absolute paths, the SQLAlchemy
  convention, so B stays possible later) and `sqlite:///:memory:`. Any other scheme
  raises `ValueError` at startup.
- `DEFAULT_REPOS` is **removed**. It was always the store `main.py` used (F2), and if it
  stayed it would be a second, non-persistent store built at import time.
- `seed_sample_data` becomes idempotent: it skips if `get_session("demo")` already
  exists. Without this, `--seed` on a second run would collide with the persisted `demo`
  session.
- `database.echo` is **not wired**. Honouring it through `sqlite3`'s trace callback can
  log statements with bound values (the children's message text), which conflicts with
  PAT-CODE-001's no-PII rule. It stays as an unused key for REQ-0012 to remove (not
  removed here to keep `settings.json` and `config.py` untouched).

### 4. Fate of `data/`: delete it
| File | Decision | Reason |
|---|---|---|
| `data/__init__.py` | Delete | Broken import (F9); no consumers |
| `data/repos.py` | Delete | The fourth duplicate in-memory repo ADR-0002 deferred here (F11); int ids; no consumers. REQ-0012 no longer needs to count it |
| `data/models.py` | Delete | Not usable for sessions (F10); its campaign/character/quest tables are REQ-0015's to design. It stays recoverable from git; the implementer records the last commit SHA containing it in the spec/wrap-up so REQ-0015 can `git show <sha>:data/models.py` |
| `data/migrations.py` | Delete | Bound to `data.models`, ignores `settings.json`, defaults to `dev.db`, no versioning (F12). Schema creation lives in the store |

Rejected alternatives: *quarantine* (keeps an unimportable package and an undeclared
`sqlalchemy` import in the tree, plus a file name that misleads, `models.py`, with no
benefit over git history); *keep as recorded WIP* (leaves the two-session-model
confusion that REQ-0004 just removed, and a second "persistence layer" next to the real
one).

Traded away:
- B's ORM learning and its head start for REQ-0015. If REQ-0015's many related tables
  make hand-written SQL painful, it can choose SQLAlchemy then, against the same
  `sqlite:///` URL and the same `.db` file. That is the reversibility path.
- D's zero-schema format and its keeping of live dicts.
- The `InMemorySessionStore` and `DEFAULT_REPOS` names that ADR-0002/SPEC-0004 kept
  stable for REQ-0004. They change now because the requirement asks for a single,
  persistent implementation.

## Consequences
- Positive: sessions and messages survive a restart or a crash; one store implementation
  tested under the same code path as production; the worker writes atomically and under a
  lock (closes F4 and the ADR-0002 thread-safety note); the dead `database.url` becomes
  live; `data/` confusion and the last duplicate repo are gone; no new dependency.
- Negative: hand-written SQL and row mapping to maintain; schema changes need a manual
  `ALTER` keyed on `user_version`; widening `update_message_status` changes a
  Protocol signature (method names unchanged); tests and imports that use
  `InMemorySessionStore`/`DEFAULT_REPOS` must be updated (F14); `dnd.db` appears in the
  working directory at first run (already gitignored).
- Follow-up work or risks accepted:
  - WS `_wait_for_terminal` re-reads the whole session every 50 ms. That is fine with
    SQLite at this scale; REQ-0007 owns the polling design.
  - `database.echo` stays unused (REQ-0012).
  - `.github/copilot-instructions.md` describes `InMemorySessionStore`, `DEFAULT_REPOS`
    and `data/` as WIP. Refresh it in the same change, or REQ-0012/REQ-0014 does it.
  - No backup or export story. Out of scope for a hobby project; copying the `.db` file
    works.
  - The test spec (for the spec writer) should cover: a restart round-trip using a
    `tmp_path` file (write, drop the store, reopen, read the same messages with equal
    `datetime`s and `meta`); unknown-id writes raise `KeyError`; the store works from a
    worker thread plus a `TestClient` (existing suites, re-pointed at `:memory:`);
    atomic `status`+`meta` on error; restart recovery of `queued`/`running`; URL parsing
    (`sqlite:///./x.db`, `sqlite:///:memory:`, a bad scheme gives `ValueError`);
    `seed_sample_data` is idempotent; `data` is not importable and the directory is
    gone. No network, no Ollama.

## Pattern Impact
- **Creates** [PAT-ARCH-002](../patterns/architecture/PAT-ARCH-002-stdlib-sqlite-store.md)
  (architecture, `status: accepted`): "Local persistence with stdlib `sqlite3` behind a
  Protocol".
- **Uses** PAT-ARCH-001 (accepted). The decision follows its Solution items 1-7
  unchanged ("a new backend implements the Protocol; callers do not change"). Its
  Consequences text became outdated, so the following changes were approved by the human
  on 2026-10-11 and applied:
  1. Context: replace "Does not cover the choice of persistence backend (that is a
     separate decision, REQ-0005)" with a pointer to ADR-0003 / PAT-ARCH-002.
  2. Consequences: replace "The in-memory store hands out live message dicts and the
     inference worker mutates them in place; backends that return copies must also
     provide update methods." with "Store reads return fresh dicts; callers MUST NOT
     mutate returned dicts to change state. Every write goes through a Protocol method;
     status and meta changes go through `update_message_status(..., meta=None)` in one
     transaction."
  3. Consequences: replace "Not thread-safe beyond what CPython guarantees." with "The
     store serializes all access with one lock (PAT-ARCH-002)."
  4. Examples: `InMemorySessionStore` -> `SqliteSessionStore`.
- **Uses** PAT-CODE-001 (accepted). Change approved and applied 2026-10-11: in
  Context, drop "(and eventually `data/` once it's wired up)", because `data/` is deleted.
