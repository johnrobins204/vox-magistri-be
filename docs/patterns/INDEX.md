# Pattern Index

| ID | Category | Name | Status | Summary |
|---|---|---|---|---|
| PAT-CODE-001 | code | Centralized logging via app.services.logger | accepted | Use `get_logger(__name__)` from `app/services/logger.py` everywhere; no stdlib `logging.getLogger` or `print()` for app logging. |
