# intelligence/__init__.py
"""
Intelligence package: LLM client, prompt builders, and tool discovery/handler.

This refactor organizes the intelligence layer into:
- client.py        : Intelligence client protocol + concrete Ollama client
- prompt_builders  : Reusable prompt construction helpers (narration, adjudicator, chat pipeline)
- tools/__init__   : Lightweight discovery helpers for intelligence.tools
- tool_handler.py  : Safe tool invocation and payload parsing
- world_guide.py   : Small wrapper for world-guidance prompts

The package intentionally keeps imports light and provides clear extension points
for voice configs and tool modules.
"""

__all__ = ["client", "prompt_builders", "tools", "tool_handler", "world_guide"]

from app.intelligence import (
    client,
    prompt_builders,
    tool_handler,
    world_guide,
)

from . import tools
