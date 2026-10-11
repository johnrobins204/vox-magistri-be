---
description: "Test conventions for tests/."
applyTo: "tests/**"
---
- Use the `app` / `client` fixtures from `tests/conftest.py` (real app, in-memory
  repos, `enable_tool_discovery=False`); no network or Ollama.
- Each test should map to a Test Spec entry in `docs/specs/` when one exists.
- `tests/test_backlog_schema.py` guards `.github/BACKLOG.json`; keep the schema
  documented in `.github/agents/coworking.agent.md` in sync with it.
- Gate before declaring done: `pytest -q`, `ruff check app tests`, `black --check app tests`.
