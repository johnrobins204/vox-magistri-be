# Pattern Index

| ID | Category | Name | Status | Summary |
|---|---|---|---|---|
| PAT-ARCH-001 | architecture | One session store API; transports are thin adapters | accepted | uuid session ids everywhere; the `SessionStore` Protocol (via `get_session_store()`) is the only session-state API; REST/WS/`/intel` are thin adapters; replies are written only by the worker; no `hasattr` fallbacks or private stores. |
| PAT-ARCH-002 | architecture | Local persistence with stdlib `sqlite3` behind a Protocol | accepted | One `check_same_thread=False` connection plus one lock per store; reads return fresh dicts, every write is an explicit method in one transaction; unknown ids raise `KeyError`; datetimes as ISO TEXT, dicts as JSON TEXT; schema via `CREATE IF NOT EXISTS` + `user_version`; path from `database.url`; tests use `:memory:`. |
| PAT-CODE-001 | code | Centralized logging via app.services.logger | accepted | Use `get_logger(__name__)` from `app/services/logger.py` everywhere; no stdlib `logging.getLogger` or `print()` for app logging. |
