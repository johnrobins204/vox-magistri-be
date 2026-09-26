# intelligence/writer.py
"""
Thin alias module exposing session prompt builder(s).

Other modules can import from intelligence.writer to get the session prompt helpers.
"""

from .prompt_builders import build_game_chat_prompt, build_narrator_prompt, build_adjudicator_prompt

__all__ = ["build_game_chat_prompt", "build_narrator_prompt", "build_adjudicator_prompt"]
