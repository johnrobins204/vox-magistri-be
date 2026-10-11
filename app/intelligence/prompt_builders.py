# intelligence/prompt_builders.py
"""
Prompt builders for narration, adjudication, and the chat pipeline.

This module centralizes prompt construction so the rest of the app can call:
    from intelligence.prompt_builders import build_narrator_prompt, build_adjudicator_prompt

Chat pipeline (SPEC-0006): build_system_prompt builds the DM system message from the DM role
sentence, the dm_voice config text (loaded by load_voice_configs) and the prompt settings;
build_chat_messages assembles [system, capped completed prior messages, current user message]
from plain message dicts. No I/O, no store access.

The functions are deterministic, compact, and optimized for small LLMs (token-sparing).
They intentionally return plain strings or plain message dicts; callers decide which model
and client to use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import PromptSettings
from app.services.logger import get_logger

logger = get_logger(__name__)

VOICE_CONFIGS_PATH = Path(__file__).resolve().parent / "voice_configs" / "voice_configs.json"

DM_ROLE_PROMPT = (
    "You are the Dungeon Master of a D&D 5e game. Narrate the world, play its characters, "
    "and respond to the player's actions without deciding what the player does."
)


# --- voice configs ---------------------------------------------------------
def load_voice_configs(path: Path | str = VOICE_CONFIGS_PATH) -> dict[str, str]:
    """
    Load the voice config strings (dm_voice, dm_analysis, ...) from a JSON object file.
    Never raises: a missing, unreadable, invalid or non-object file logs one WARNING and
    returns {}; entries whose key or value is not a str are dropped with one WARNING each.
    File contents are never logged.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        reason = "missing"
    except (OSError, UnicodeDecodeError):
        reason = "unreadable"
    except ValueError:
        reason = "invalid_json"
    else:
        if isinstance(data, dict):
            configs: dict[str, str] = {}
            for key, value in data.items():
                if isinstance(key, str) and isinstance(value, str):
                    configs[key] = value
                else:
                    logger.warning("voice_configs.entry_dropped", extra={"key": str(key)})
            return configs
        reason = "not_object"
    logger.warning("voice_configs.unavailable", extra={"path": str(path), "reason": reason})
    return {}


# --- small helpers ---------------------------------------------------------
def _truncate(s: str | None, n: int) -> str:
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _compact_json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, default=str)


def _verbosity_to_sentences(verbosity: str) -> int:
    v = (verbosity or "").lower()
    return {"brief": 1, "short": 1, "normal": 3, "long": 5, "verbose": 8}.get(v, 3)


# --- narrator voice params -------------------------------------------------
@dataclass(frozen=True)
class NarratorVoiceParams:
    tone: str
    dm_persona: str
    verbosity: str
    sensory_focus: str
    consequence_level: str


# --- prompt builders ------------------------------------------------------
def build_adjudicator_prompt(game_state: dict[str, Any]) -> str:
    """
    Build a compact adjudicator prompt that expects a strict JSON outcome.
    Caller must ensure game_state is already truncated/compact.
    """
    json_payload = _compact_json(game_state)

    example_in = {
        "last_action": "I want to look around",
        "recent_turns": [{"kind": "player", "content": "I want to look around"}],
        "included_characters": [{"id": "pc1", "name": "Aria", "perception_mod": 5}],
    }
    example_out = {
        "outcome": "success",
        "reason": "perception success detected hidden door",
        "targets": [],
        "consequences": [
            {"type": "reveal", "target": "north wall", "detail": "hidden door revealed"}
        ],
        "notes": None,
    }

    instructions = (
        "ROLE: You are the mechanical adjudicator. Analyze the compact GAME_STATE JSON and return "
        "ONLY a single JSON object matching the schema below.\n\n"
        "OUTPUT SCHEMA (exact):\n"
        '{ "outcome": "success"|"fail"|"partial", "reason": string|null, "targets": [string...], '
        '"consequences":[{"type":string,"target":string|null,"value":number|null,"detail":string|null}], "notes":string|null }\n\n'
        "RULES:\n- Output ONLY the JSON object and nothing else.\n- Be literal and conservative; do not invent new entities.\n- Include numeric values where applicable."
    )

    parts = [
        "SYSTEM: Mechanical adjudicator. Return only the JSON outcome object.",
        f"GAME_STATE:{json_payload}",
        "EXAMPLE_IN:" + _compact_json(example_in),
        "EXAMPLE_OUT:" + _compact_json(example_out),
        instructions,
    ]
    return "\n\n".join(parts)


def build_narrator_prompt(
    adjudicator_output: str, params: NarratorVoiceParams, player_intent: str | None = None
) -> str:
    """
    Build a compact narrator prompt that translates adjudicator output into second-person narration.
    """
    voice_block = (
        f"TONE:{params.tone}|PERSONA:{params.dm_persona}|VERBOSITY:{params.verbosity}|"
        f"SENSE:{params.sensory_focus}|CONSEQ:{params.consequence_level}"
    )

    example = (
        "EXAMPLE_IN: intent='I want to look around' | mechanical='You detect a hidden door to the north.'\n"
        "EXAMPLE_OUT: You notice a faint draft from the north wall; the stone there is slightly cooler, "
        "and a hairline seam runs vertical—someone has hidden a door here."
    )

    directives = (
        "DIRECTIVES:\n- Output a single narrative paragraph in second person; begin immediately.\n"
        "- Do not mention dice, mechanics, or preambles.\n- Use the voice parameters and match verbosity."
    )

    parts = [
        "SYS: You are an expert Dungeon Master. Translate mechanical outcomes into immediate D&D narration.",
        f"VOICE:{voice_block}",
        f"MECHANICAL_OUTCOME:{adjudicator_output.strip()}",
        f"PLAYER_INTENT:{(player_intent or '').strip() or 'None'}",
        example,
        directives,
    ]
    return "\n\n".join(parts)


def build_system_prompt(prompts: PromptSettings, voice_configs: dict[str, str]) -> str:
    """
    DM system message: the role sentence, then the dm_voice config text (only when it is a
    non-empty str), then the voice settings line. Parts are joined with a blank line.
    """
    parts = [DM_ROLE_PROMPT]
    dm_voice = voice_configs.get("dm_voice")
    if isinstance(dm_voice, str) and dm_voice:
        parts.append(dm_voice)
    voice = prompts.dm_voice
    parts.append(
        f"VOICE: TONE:{voice.tone}|PERSONA:{voice.persona}|VERBOSITY:{prompts.verbosity_default}|"
        f"SENSE:{voice.sensory_focus}|CONSEQ:{voice.consequence_level}"
    )
    return "\n\n".join(parts)


def build_chat_messages(
    system: str,
    history: list[dict[str, Any]],
    current_message_id: str,
    current_text: str,
    *,
    max_turns: int,
    max_field_len: int,
) -> list[dict[str, str]]:
    """
    Chat messages for one turn: [system, prior, current user]. Prior messages are the completed
    user/assistant messages before the current one in history (all of them if the current id is
    not found), keeping the last max_turns (none when max_turns <= 0), oldest first, with contents
    truncated to max_field_len. The current text is not truncated. Reads plain dicts only: no
    mutation, no I/O.
    """
    prior: list[dict[str, Any]] = []
    for message in history:
        if message.get("id") == current_message_id:
            break
        if message.get("status") == "completed" and message.get("role") in ("user", "assistant"):
            prior.append(message)
    kept = prior[-max_turns:] if max_turns > 0 else []
    return [
        {"role": "system", "content": system},
        *({"role": m["role"], "content": _truncate(m.get("content"), max_field_len)} for m in kept),
        {"role": "user", "content": current_text},
    ]
