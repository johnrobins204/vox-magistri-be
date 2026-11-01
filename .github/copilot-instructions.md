# vox-magistri-be — Agent Instructions

FastAPI backend for an AI Dungeon Master server. A local Ollama model generates
narration/adjudication; the client is a separate React app (not in this repo).

## Architecture
- `app/main.py` — CLI entrypoint (`python -m app.main`). Wires repos → services → FastAPI app, then runs uvicorn.
- `app/factory.py` — `create_app(services=...)` builds the FastAPI app, registers routers, CORS, startup/shutdown hooks.
- `app/config.py` — Typed Pydantic `Settings` loaded from root `settings.json` (namespaces: ollama, app, server, tools, prompts, world, database, auth, logging). Use `get_settings()` / `get_namespace()` / `get()`, never read `settings.json` directly elsewhere.
- `app/deps.py` — Service-locator pattern: `set_services()` is called once by `create_app`; routers pull services via `get_inference_service()`, `get_session_store()`, `get_tool_service()`. There is no per-request DB session dependency yet.
- `app/services/build_services.py` — Constructs the services dict (`session`, `tool`, `inference`) from repos + settings.
- `app/services/repos.py` — holds `SqliteSessionStore` (stdlib `sqlite3`), the only session store. It implements the `SessionStore` Protocol in `app/type_defs.py`, and every transport (REST, the single WebSocket, `/intel` snapshot) uses it via `get_session_store()`. Sessions and messages persist across restarts. The path comes from `settings.json` `database.url` (default `sqlite:///./dnd.db`; `:memory:` in tests) and is passed to `make_default_repos(database_url)` by `app/main.py`. On open, in-flight `queued`/`running` messages are marked `error`. Session ids are uuid strings. The `sessions` table has a nullable `character` JSON column, set once at create and read by `get_character`; the schema is a `user_version` migration ladder (PAT-ARCH-008).
- `app/api/v1/*` — Routers: `session.py` (REST session CRUD; `POST /api/v1/sessions` takes an optional `character` body, plus message CRUD), `ws.py` (the only WebSocket, `/api/v1/ws/sessions/{session_id}`), `intelligence.py` (tool/inference endpoints, plus `/api/v1/intel/sessions/{session_id}/snapshot`). All prefixed `/api/v1/...`. `app/services/messages.py` holds the shared "submit user message" and "snapshot" helpers used by REST and WS.
- `app/intelligence/` — Prompting, Ollama client (`client.py`, uses `httpx`), and the tool-call pipeline (`tool_handler.py`, `prompting.py`, `prompt_builders.py`).
- `app/intelligence/tools/` — Pluggable tools (`roll.py`, `narrate.py`); contract in `.github/instructions/tools.instructions.md`.

## Known gaps / traps (verified, not guesses)
- Tool discovery goes through `app.intelligence.tools.discover_tool_modules`, called by `ToolService.reload_tools()`; `tool_handler.get_registry()` shares it. Import failures are logged, not swallowed.
- `data/` (the unused SQLAlchemy layer) was deleted under REQ-0005; recover its models for REQ-0015 with `git show 0365f2bf23789f85fef4b89595abd6056b35a1a5:data/models.py`.
- `app/factory.py` uses deprecated FastAPI `@app.on_event` hooks (works today, but expect a future migration to lifespan handlers).

## Conventions
- Errors: wrap risky I/O in `try/except Exception` and `logger.exception(...)`, don't let startup/shutdown crash the process.
- Logging: use `app.services.logger.get_logger(__name__)`, not the stdlib `logging` module directly. Logs are JSON-formatted.
- Services/repos are passed around as plain `dict`s (`services.get("inference")` or dict/attr dual access) — not a DI framework.
- Settings: add new config under the right namespace in both `app/config.py` (Pydantic model) and `settings.json` (actual values).

## Dev workflow
- Python 3.13 venv at `venv-dnd-server/` (gitignored). Activate or call binaries directly: `./venv-dnd-server/bin/python`.
- Run the server: `./restart.sh` or `python -m app.main --debug` (add `--seed` to seed sample data, `--no-tools` to skip tool discovery). The first real run creates a gitignored `dnd.db` in the working directory; sessions survive a restart. Delete `dnd.db` to start empty.
- Runtime deps: `requirements.txt`. Dev deps (pytest, ruff, black): `requirements-dev.txt` — install with `pip install -r requirements-dev.txt`.
- Tests: `pytest` (config in `pyproject.toml`, tests live in `tests/`). Use the `app`/`client` fixtures in `tests/conftest.py` (builds a real app with `:memory:` SQLite repos, no network/Ollama required).
- Lint/format: `ruff check app tests` and `black app tests`.
- CI (`.github/workflows/ci.yml`) runs `ruff check`, `black --check` and `pytest`; run the same locally before declaring work done.
- `dupe-scan.sh` was retired; after large refactors, eyeball `git ls-files` for accidentally duplicated basenames under different folders (a recurring issue in this repo's history).

## Coworking workflow (requirements → architecture → spec → implement → wrap-up)
For any non-trivial requirement, need, or desired outcome, use the **Coworking
Orchestrator** custom agent instead of free-form changes. It runs four stages:
restate the requirement in RFC 2119 language (logged in
`docs/requirements/LOG.md`) → backlog entry in `.github/BACKLOG.json` (written
only by the **Backlog Manager Subagent**) → architecture review via the **Senior Architect**
agent (decides if an ADR is needed, writes it under `docs/adr/` with a weighted
rubric from `docs/constraints.md`) → spec via the **Spec Writer** agent
(test-spec-first, then self-contained work packages, under `docs/specs/`).
Every stage MUST consult `docs/patterns/INDEX.md` before producing new
architecture, specs, or code — new patterns can be authored freely at
`status: proposed`, but changing an `accepted` pattern requires the architect
plus explicit human sign-off. `docs/constraints.md` is the standing charter:
this is a solo, part-time hobby project — prefer the smallest edit, avoid
speculative abstraction, and don't scope-creep toward production hardening.

After the spec: the **Implementer** agent executes one work package at a time,
test-first, then the **Session Cleanup Agent** runs the gate (pytest/ruff/black),
verifies against the spec, updates the backlog and stages changes with a drafted
commit message — you review and commit. Orchestrators offer these as handoff
buttons; `/new-req` and `/wrap-up` prompts start the first and last stage.

