# Pattern Index

| ID | Category | Name | Status | Summary |
|---|---|---|---|---|
| PAT-ARCH-001 | architecture | One session store API; transports are thin adapters | accepted | uuid session ids everywhere; the `SessionStore` Protocol (via `get_session_store()`) is the only session-state API; REST/WS/`/intel` are thin adapters; replies are written only by the worker; no `hasattr` fallbacks or private stores. |
| PAT-CODE-001 | code | Centralized logging via app.services.logger | accepted | Use `get_logger(__name__)` from `app/services/logger.py` everywhere; no stdlib `logging.getLogger` or `print()` for app logging. |
