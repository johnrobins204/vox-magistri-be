# intelligence/character_mods.py
"""
Pure ability-modifier helpers for character-aware dice (REQ-0022, SPEC-0017).

Not under tools/ so tool discovery ignores it. The first three functions are
pure; require_character only reads the tool context and never writes.
"""

__all__ = [
    "ABILITIES",
    "NO_CHARACTER",
    "ability_modifier",
    "ability_modifiers",
    "require_character",
    "weapon_ability",
]

from app.intelligence.tools import ToolError

ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
NO_CHARACTER = "No character on this session. Create or select a character first."


def ability_modifier(score: int) -> int:
    return (score - 10) // 2


def ability_modifiers(character: dict) -> dict[str, int]:
    abilities = character.get("abilities")
    if not isinstance(abilities, dict):
        return {}
    return {
        key: ability_modifier(value)
        for key, value in abilities.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }


def weapon_ability(properties: list[str], mods: dict[str, int]) -> tuple[str, int]:
    names = {str(p).lower() for p in properties}
    str_mod = mods.get("STR", 0)
    dex_mod = mods.get("DEX", 0)
    if "finesse" in names:
        return ("DEX", dex_mod) if dex_mod > str_mod else ("STR", str_mod)
    if "ammunition" in names:
        return ("DEX", dex_mod)
    return ("STR", str_mod)


def require_character(context: dict) -> dict:
    store = context.get("store")
    session_id = context.get("session_id")
    if store is None or session_id is None:
        raise ToolError(NO_CHARACTER)
    try:
        character = store.get_character(session_id)
    except KeyError:
        raise ToolError(NO_CHARACTER) from None
    if character is None:
        raise ToolError(NO_CHARACTER)
    return character
