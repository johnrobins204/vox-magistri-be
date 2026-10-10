# vox-magistri-be — Agent Instructions

FastAPI backend for an AI Dungeon Master server. A local Ollama model generates
narration/adjudication; the client is a separate React app (not in this repo).

## Architecture
- `app/main.py` — CLI entrypoint (`python -m app.main`). Wires repos → services → FastAPI app, then runs uvicorn.
- `app/factory.py` — `create_app(services=...)` builds the FastAPI app, registers routers, CORS, startup/shutdown hooks.
- `app/config.py` — Typed Pydantic `Settings` loaded from root `settings.json` (namespaces: ollama, app, server, tools, prompts, world, database, auth, logging). Use `get_settings()` / `get_namespace()` / `get()`, never read `settings.json` directly elsewhere.
- `app/deps.py` — Service-locator pattern: `set_services()` is called once by `create_app`; routers pull services via `get_inference_service()`, `get_session_store()`, `get_tool_service()`. There is no per-request DB session dependency yet.
- `app/services/build_services.py` — Constructs the services dict (`session`, `tool`, `game`, `inference`) from repos + settings.
- `app/services/repos.py` — **Active** in-memory repo layer (`InMemorySessionStore`, `DEFAULT_REPOS`). This is what's actually wired up today.
- `app/api/v1/*` — Routers: `session.py` (REST session/message CRUD), `ws.py` (live session WebSocket), `intelligence.py` (tool/inference endpoints). All prefixed `/api/v1/...`.
- `app/intelligence/` — Prompting, Ollama client (`client.py`, uses `httpx`), and the tool-call pipeline (`tool_handler.py`, `prompting.py`, `prompt_builders.py`).
- `app/intelligence/tools/` — Pluggable tools (`roll.py`, `narrate.py`, `clear.py`). Contract: module exposes `NAME: str` and `run(args: str, context: dict) -> Any`.

## Known gaps / traps (verified, not guesses)
- **Tool discovery is currently broken.** `app/services/tool_service.py` does `import intelligence.tools` (not `app.intelligence.tools`), which raises `ModuleNotFoundError` and is silently swallowed — `ToolService` ends up with an empty registry. Fix by importing `app.intelligence.tools` or adjusting `sys.path`/package layout before relying on tool discovery.
- `data/` (`models.py`, `migrations.py`, `repos.py`) is a **separate, not-yet-wired SQLAlchemy layer** — it uses `sqlalchemy`, which isn't installed and isn't in `requirements.txt`. Don't assume it's live; `app/services/repos.py`'s in-memory store is what's actually used by `build_services()`. Treat `data/` as WIP until it's connected.
- `app/intelligence/tools/roll.py` is a stub (`# TODO: implement your dice parser`).
- `app/factory.py` uses deprecated FastAPI `@app.on_event` hooks (works today, but expect a future migration to lifespan handlers).

## Conventions
- Errors: wrap risky I/O in `try/except Exception` and `logger.exception(...)`, don't let startup/shutdown crash the process.
- Logging: use `app.services.logger.get_logger(__name__)`, not the stdlib `logging` module directly. Logs are JSON-formatted.
- Services/repos are passed around as plain `dict`s (`services.get("inference")` or dict/attr dual access) — not a DI framework.
- Settings: add new config under the right namespace in both `app/config.py` (Pydantic model) and `settings.json` (actual values).

## Dev workflow
- Python 3.13 venv at `venv-dnd-server/` (gitignored). Activate or call binaries directly: `./venv-dnd-server/bin/python`.
- Run the server: `./restart.sh` or `python -m app.main --debug` (add `--seed` to seed sample data, `--no-tools` to skip tool discovery).
- Runtime deps: `requirements.txt`. Dev deps (pytest, ruff, black): `requirements-dev.txt` — install with `pip install -r requirements-dev.txt`.
- Tests: `pytest` (config in `pyproject.toml`, tests live in `tests/`). Use the `app`/`client` fixtures in `tests/conftest.py` (builds a real app with in-memory repos, no network/Ollama required).
- Lint/format: `ruff check app tests` and `black app tests`. `data/` is intentionally excluded from the default lint scope until it's integrated (it has real undefined-name errors from in-progress model relationships).
- `dupe-scan.sh` detects accidentally duplicated files with the same basename under different folders — a recurring issue in this repo's history; run it after large refactors.
