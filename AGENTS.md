# AGENTS.md

Agent instructions for this repo live in
[.github/copilot-instructions.md](.github/copilot-instructions.md) (architecture,
conventions, dev workflow, coworking workflow). Scoped rules are in
[.github/instructions/](.github/instructions/). Custom agents are in
[.github/agents/](.github/agents/).

Quick reference:
- Python 3.13 venv: `./venv-dnd-server/bin/python`
- Gate: `scripts/gate.sh` (= `pytest -q`, `ruff check app tests`, `black --check app tests`; CI runs the same)
- Never read `.github/BACKLOG.json` / `docs/requirements/LOG.md` / whole specs; use `scripts/backlog.py` and
  `scripts/spec_slice.py` (see "Token-lean workflow rules" in copilot-instructions.md)
- Charter: solo hobby project — smallest edit, no speculative abstraction
  ([docs/constraints.md](docs/constraints.md)); consult
  [docs/patterns/INDEX.md](docs/patterns/INDEX.md) before new architecture, specs or code.
