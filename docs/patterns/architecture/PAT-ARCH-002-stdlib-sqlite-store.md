---
id: PAT-ARCH-002
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# Local persistence with stdlib `sqlite3` behind a Protocol

## Problem
State that must survive a restart (sessions/messages now, maybe campaign data later)
needs durable local storage. It is read and written from several threads: the inference
worker, the event loop, Starlette's threadpool for sync routes, and test threads. Pulling
in an ORM for a handful of tables adds a dependency and concepts a part-time maintainer
has to carry. Handing out live, mutable objects lets callers change state without the
store knowing, so the change is never persisted.

## Context
Use this when a store behind a Protocol (e.g. `SessionStore`, PAT-ARCH-001) needs to
persist locally and the data fits a few tables. Do not use it for multi-process or
multi-host access, or for anything that needs migrations beyond a manual `ALTER` (revisit
with an ADR; SQLAlchemy against the same `sqlite:///` URL is the planned escape hatch).
Do not create a shared base class or generic repository until a second store actually
exists (constraints.md, constraint 2).

## Solution
1. **One connection per store, one lock.** `sqlite3.connect(path,
   check_same_thread=False)`; every public method runs under a single
   `threading.Lock`; every write commits in its own transaction (`with conn:`).
2. **Copies out, explicit writes in.** Reads build fresh `dict`s from rows. Callers never
   mutate returned objects to change state; each state change is a store method (combine
   fields that must change together, e.g. status + meta, into one method and one
   transaction).
3. **Fail loudly.** A write that targets an unknown parent or row raises `KeyError`.
   Reads return `None` for "does not exist" when the Protocol says so. No silent no-ops.
4. **Explicit value encoding.** `datetime` <-> ISO-8601 TEXT (`isoformat()` /
   `datetime.fromisoformat()`; do not rely on `sqlite3`'s default adapters, deprecated
   since Python 3.12). `dict`/`list` <-> JSON TEXT.
5. **Schema on open.** `CREATE TABLE IF NOT EXISTS ...` in the constructor plus `PRAGMA
   user_version = N`. Bump N and add a small `ALTER` branch when the schema changes. No
   migration framework.
6. **Configuration.** The path comes from `settings.database.url` (`sqlite:///<path>`,
   `sqlite:////abs/path`, or `sqlite:///:memory:`), parsed in one place. Any other scheme
   raises `ValueError` at startup. The store is built in `app/main.py` (not at import
   time). Tests use `:memory:`, which needs no disk and no network.
7. **Logging** through `get_logger` (PAT-CODE-001). Do not trace SQL with bound values
   into logs (message text may be personal).

## Consequences
- No new runtime dependency; the `.db` file opens in any SQLite tool.
- Hand-written SQL and row mapping to maintain; schema evolution is manual.
- A single lock serializes all access. That is fine for one household and would not be
  for real concurrency (explicitly not a goal).
- Copies-out costs a little allocation per read; irrelevant next to LLM latency.

## Examples
- `SqliteSessionStore` in `app/services/repos.py:33` (ADR-0003, REQ-0005): schema and
  `PRAGMA user_version = 1` in `__init__` (line 71); restart recovery in
  `_recover_interrupted` (line 74); `make_default_repos(database_url)` at
  `app/services/repos.py:209`, called with `database.url` from `app/main.py:44`.
