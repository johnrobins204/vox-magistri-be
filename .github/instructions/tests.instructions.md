---
description: "Test conventions for tests/."
applyTo: "tests/**"
---
- Use the `app` / `client` fixtures from `tests/conftest.py` (real app, in-memory
  repos, `enable_tool_discovery=False`); no network or Ollama.
- Each test should map to a Test Spec entry in `docs/specs/` when one exists.
- `tests/test_backlog_schema.py` guards `.github/BACKLOG.json`; edit the backlog only
  via `scripts/backlog.py` (its schema constants and this test must stay in sync).
- `tests/test_patterns.py` is the pattern linter; add a check there when a pattern gains
  a checkable rule, and list it in `docs/patterns/INDEX.md`.
- Gate before declaring done: `pytest -q`, `ruff check app tests`, `black --check app tests`.
