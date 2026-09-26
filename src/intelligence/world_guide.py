# intelligence/world_guide.py
"""
Small wrapper around prompt_builders for world guidance flows.

WorldGuide.build_prompt(mode, step_name, answers, existing_world) -> str
"""

from __future__ import annotations
from typing import Dict
from .prompt_builders import build_game_state_payload  # reuse if needed
from .prompt_builders import _compact_json  # internal helper (ok to reuse here)


class WorldGuide:
    """Build bounded world guidance requests; callers decide acceptance."""

    def build_prompt(self, mode: str, step_name: str, answers: Dict[str, str], existing_world: str = "") -> str:
        # Simple, deterministic wrapper that produces a compact prompt for the LLM
        payload = {"mode": mode, "step": step_name, "answers": answers, "existing_world": existing_world}
        return f"WORLD_GUIDANCE:{_compact_json(payload)}"
