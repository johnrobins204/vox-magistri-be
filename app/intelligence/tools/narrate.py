# app/intelligence/tools/narrate.py
"""
`/narrate` tool (REQ-0008, SPEC-0007 WP-4).

Builds the DM narrator prompt from the user's text and the `dm_voice` / verbosity
settings, then produces the reply through the injected `inference` service
(`context["inference"].generate(prompt)`). The prompt is not put in `meta` and not logged.
"""

from typing import Any

from app.config import get_settings
from app.intelligence.prompt_builders import NarratorVoiceParams, build_narrator_prompt
from app.intelligence.tools import ToolError

NAME = "narrate"
DESCRIPTION = "Describe what happens next in the story."

_USAGE = "Usage: /narrate <what happens>"


def run(args: str, context: dict) -> dict[str, Any]:
    text = (args or "").strip()
    if not text:
        raise ToolError(_USAGE)

    p = get_settings().prompts
    params = NarratorVoiceParams(
        tone=p.dm_voice.tone,
        dm_persona=p.dm_voice.persona,
        verbosity=p.verbosity_default,
        sensory_focus=p.dm_voice.sensory_focus,
        consequence_level=p.dm_voice.consequence_level,
    )
    prompt = build_narrator_prompt(text, params, None)
    reply = context["inference"].generate(prompt)
    return {"text": reply, "meta": {"tool": NAME}}
