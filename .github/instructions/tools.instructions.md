---
description: "Tool module contract and conventions for app/intelligence/tools."
applyTo: "app/intelligence/tools/**"
---
- A tool is a module in `app/intelligence/tools/` exposing `NAME: str` and `run(args: str, context: dict)` returning `str` or `{"text": str, "meta": dict}`. Discovery requires both.
- Raise `app.intelligence.tools.ToolError` for bad user input; its message is shown to the user (HTTP 400 on `/invoke`; a slash command marks the user message `error`). Any other exception is a bug (HTTP 500; `IntelligenceError` is HTTP 502). Tools never write messages or touch the store.
- Discovery goes only through `app.intelligence.tools.discover_tool_modules` (ADR-0001); do not add a second registry or import path.
- Context: the server-owned keys `inference`, `repos`, `store`, `session_id`, `message_id`, `logger` and `rng` cannot be overridden by clients (`ToolService` drops them and logs only the key names). `session_id`, `message_id` and `store` are set only by the worker. Use `context["inference"].generate(prompt)` for LLM calls and `context.get("rng")` for randomness.
- `context["reference"]` is the in-memory reference catalog (`{"species": [...], "weapons": [...], "rules": [...]}`), set by `build_services`; read it, never open `app/reference/*.json` or `dnd_data/`. A tool that puts catalog text into a prompt follows PAT-ARCH-009: deterministic selection, a chars budget from settings, never truncate an entry, `meta.source` is the dataset name or `training` with an always-present id list, and a training reply gets a fixed 'not checked' sentence. `/rules` is the example.
- Slash commands `/name args` are dispatched by the inference worker (`detect_tool`, PAT-ARCH-004); the result is stored as an assistant reply with `meta.tool` and `meta.reply_to`. An unknown `/x` is an error and is not sent to the LLM. `clear` is deleted (REQ-0008, human decision 2026-10-11): there is no `clear` tool and no replacement, and `/clear` is an unknown tool (chat: the user message is marked `error`; `POST /api/v1/intel/tools/clear/invoke`: HTTP 404).
- `ToolService.invoke` raises `UnknownToolError` for an unregistered name and propagates tool exceptions unchanged; it does not hold its registry lock while a tool runs.
- Log with `get_logger(__name__)`; never log prompts.
- Tests must not need network or Ollama (see `tests/test_tool_calling.py`, `tests/test_roll.py`, `tests/test_slash_dispatch.py`, `tests/test_rules_tool.py`).
