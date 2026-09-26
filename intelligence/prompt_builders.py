# intelligence/prompt_builders.py
"""
Prompt builders for narration, adjudication, and compact game/chat payloads.

This module centralizes prompt construction so the rest of the app can call:
    from intelligence.prompt_builders import build_narrator_prompt, build_adjudicator_prompt, build_game_chat_prompt

The functions are deterministic, compact, and optimized for small LLMs (token-sparing).
They intentionally return plain strings; callers decide which model and client to use.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# --- small helpers ---------------------------------------------------------
def _truncate(s: Optional[str], n: int) -> str:
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
def build_adjudicator_prompt(game_state: Dict[str, Any]) -> str:
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


def build_narrator_prompt(adjudicator_output: str, params: NarratorVoiceParams, player_intent: Optional[str] = None) -> str:
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


def build_game_chat_prompt(
    *,
    game: Any,
    session_run: Any,
    voice_label: str,
    user_input: str,
    included_characters: Iterable[Any] = (),
    max_turns: int = 6,
    max_field_len: int = 240,
) -> str:
    """
    Compact prompt for general game chat / DM responses.
    - game: object with name, campaign.name, quest.title (optional), character, character_links
    - session_run: object with entries (list-like)
    - included_characters: iterable of Character-like objects to include
    """
    # voice
    voice = getattr(voice_label, "label", voice_label) if hasattr(voice_label, "label") else voice_label
    current = getattr(game, "character", None) or {}

    # minimal character data
    def minimal_character(c):
        try:
            return {
                "id": getattr(c, "id", None),
                "name": _truncate(getattr(c, "name", ""), max_field_len),
                "class": getattr(c, "class_name", ""),
                "level": getattr(c, "level", 0),
                "hp": {"current": int(getattr(c, "current_hp", 0)), "max": int(getattr(c, "max_hp", 1))},
            }
        except Exception:
            return {"name": str(c)}

    included_data = [minimal_character(c) for c in included_characters]
    included_json = _compact_json({"active": minimal_character(current), "included": included_data} if included_data else minimal_character(current))

    recent_entries = getattr(session_run, "entries", [])[-max_turns:]
    recent_turns = "\n".join(f"{getattr(e, 'kind', 'entry')}:{_truncate(getattr(e, 'content', str(e)), max_field_len)}" for e in recent_entries) or "None"

    meta = (
        f"GAME:{_truncate(getattr(game, 'name', ''), 64)}|CAMPAIGN:{_truncate(getattr(game.campaign, 'name', ''), 64) if getattr(game, 'campaign', None) else 'None'}|"
        f"QUEST:{(_truncate(getattr(game.quest, 'title', ''), 64) if getattr(game, 'quest', None) else 'None')}|CHAR:{_truncate(getattr(current, 'name', ''), 64)}"
    )

    parts = [
        "SYS:DND5e",
        f"VOICE:{voice}",
        meta,
        f"CHAR_JSON:{included_json}",
        f"RECENT:{recent_turns}",
        f"INPUT:{_truncate(user_input, max_field_len)}",
        "INSTR:Use CHAR_JSON as authoritative source; do not invent missing sheet data.",
    ]
    return "\n".join(parts)


def build_game_state_payload(
    *,
    game: Any,
    session_run: Any,
    user_input: str,
    included_characters: Iterable[Any],
    max_turns: int = 6,
) -> Dict[str, Any]:
    """
    Compact payload for adjudication: returns a dict suitable for JSON serialization.
    """
    game_chars = [link.character for link in getattr(game, "character_links", [])] or [getattr(game, "character", None)]
    char_map = {c.id: {"id": c.id, "name": c.name, "class": c.class_name, "level": c.level, "hp": {"current": c.current_hp, "max": c.max_hp}} for c in game_chars if c is not None}

    included = []
    for c in included_characters:
        included.append(char_map.get(getattr(c, "id", None)) or {"id": getattr(c, "id", None), "name": getattr(c, "name", "")})

    recent = [{"kind": str(getattr(e, "kind", "")), "content": _truncate(getattr(e, "content", ""), 200)} for e in getattr(session_run, "entries", [])[-max_turns:]]

    payload = {
        "game": {"name": getattr(game, "name", ""), "campaign": getattr(game.campaign, "name", "") if getattr(game, "campaign", None) else ""},
        "characters": list(char_map.values()),
        "included_characters": included,
        "recent_turns": recent,
        "last_action": _truncate(user_input, 300),
    }
    return payload


def build_turn_summary(*, game: Any, session_run: Any, max_turns: int = 6) -> Dict[str, Any]:
    """
    Compact turn summary used by UI or voice systems.
    Returns a simple dict (serializable).
    """
    quest = getattr(game, "quest", None)
    quest_title = getattr(quest, "title", None) if quest else None
    quest_goal = "No active quest"
    if quest:
        open_objectives = [o for o in getattr(quest, "objectives", []) if getattr(o, "status", "") == "Open"]
        if open_objectives:
            quest_goal = getattr(open_objectives[0], "title", quest_goal)
        elif getattr(quest, "objective", None):
            quest_goal = getattr(quest, "objective")

    game_chars = [link.character for link in getattr(game, "character_links", [])] or [getattr(game, "character", None)]
    party = []
    for c in game_chars:
        if c is None:
            continue
        max_hp = max(1, int(getattr(c, "max_hp", 1) or 1))
        current_hp = int(getattr(c, "current_hp", 0) or 0)
        ratio = current_hp / max_hp
        if current_hp <= 0:
            condition = "Down"
        elif ratio <= 0.5:
            condition = "Bloodied"
        else:
            condition = "Healthy"
        party.append({"name": c.name, "class": c.class_name, "level": c.level, "current_hp": current_hp, "max_hp": max_hp, "condition": condition})

    turn_number = sum(1 for e in getattr(session_run, "entries", []) if getattr(e, "kind", "") == "Chat input") + 1
    scene = (getattr(session_run, "current_scene", "") or getattr(session_run, "title", "") or "No scene set").strip()

    return {"turn_number": turn_number, "scene": scene, "quest_title": quest_title, "quest_goal": quest_goal, "party": party}
