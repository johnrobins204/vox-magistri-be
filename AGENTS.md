# AGENTS.md

Agent instructions for this repo live in
[.github/copilot-instructions.md](.github/copilot-instructions.md) (architecture,
conventions, dev workflow, coworking workflow). Scoped rules are in
[.github/instructions/](.github/instructions/). Custom agents are in
[.github/agents/](.github/agents/).

Quick reference:
- Python 3.13 venv: `./venv-dnd-server/bin/python`
- Gate: `pytest -q`, `ruff check app tests`, `black --check app tests` (CI runs the same)
- Charter: solo hobby project — smallest edit, no speculative abstraction
  ([docs/constraints.md](docs/constraints.md)); consult
  [docs/patterns/INDEX.md](docs/patterns/INDEX.md) before new architecture, specs or code.
