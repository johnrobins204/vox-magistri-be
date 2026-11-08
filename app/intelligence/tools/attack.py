# app/intelligence/tools/attack.py
"""
`/attack` tool: one weapon attack roll and, on a hit, its damage (REQ-0022, SPEC-0017 WP-3).

Parsing and lookup are pure and run before any rng call. The character is read through
character_mods only; weapons come from context["reference"]["weapons"] (PAT-ARCH-006).
Attack rolls use roll.evaluate, so the rng is only asked for randint(1, sides).
"""

import random
import re
from typing import Any

from app.intelligence.character_mods import (
    ability_modifiers,
    require_character,
    weapon_ability,
)
from app.intelligence.tools import ToolError
from app.intelligence.tools.roll import MAX_DICE_PER_TERM, MAX_SIDES, MIN_SIDES, evaluate

NAME = "attack"
DESCRIPTION = "Make an attack with a weapon."

_DEFAULT_RNG = random.Random()

HELP = (
    "Usage: /attack <weapon> [vs <AC>], e.g. /attack longsword vs 15. "
    "Rolls 1d20 plus the weapon's ability modifier from your session character: "
    "STR, or DEX for Finesse weapons (the better of STR and DEX) and Ammunition weapons. "
    "A natural 20 is a critical hit and doubles the weapon's damage dice (flat damage is not doubled). "
    "A natural 1 always misses. With vs <AC> the attack hits when the total meets or beats AC; "
    "without it the DM decides. Damage is rolled only on a hit. "
    "A proficiency bonus and spell attacks are out of scope."
)

_CATALOG_MISSING = "The weapon catalog is empty or unavailable."
_AC_RE = re.compile(r"[0-9]{1,3}")
_VS_RE = re.compile(r"(?:^|(?<=\s))vs(?=\s|$)", re.IGNORECASE)
_DICE_RE = re.compile(r"([0-9]{1,2})?d([0-9]{1,3})")
_FLAT_RE = re.compile(r"[0-9]{1,3}")


def run(args: str, context: dict) -> dict[str, Any]:
    if args.strip().lower() == "help":
        return {"text": HELP, "meta": {"tool": NAME, "help": True}}
    name, ac = _parse(args)
    weapon = _lookup(name, _catalog(context))
    _check_damage(weapon)
    character = require_character(context)
    ability, modifier = weapon_ability(list(weapon.properties), ability_modifiers(character))
    rng = context.get("rng")
    if rng is None:
        rng = _DEFAULT_RNG

    attack = evaluate(f"1d20{_signed(modifier)}", rng)
    nat = attack["meta"]["terms"][0]["rolls"][0]
    total = attack["meta"]["total"]
    critical = nat == 20
    hit = _hit(nat, total, ac)

    damage = None
    damage_roll = None
    if hit is True:
        damage_roll = evaluate(damage_expression(weapon.damage_dice, modifier, critical), rng)
        damage = max(0, damage_roll["meta"]["total"])

    text = f"{weapon.name} ({ability} {modifier:+d})"
    if ac is not None:
        text += f" vs {ac}"
    text += f": {attack['text']}. {_verdict(nat, hit, critical)}"
    if damage_roll is not None:
        text += f" Damage: {damage_roll['text']}."

    return {
        "text": text,
        "meta": {
            "tool": NAME,
            "weapon": weapon.name,
            "weapon_id": weapon.id,
            "ability": ability,
            "modifier": modifier,
            "ac": ac,
            "attack_roll": nat,
            "attack_total": total,
            "hit": hit,
            "critical": critical,
            "damage": damage,
            "damage_expression": None if damage_roll is None else damage_roll["meta"]["expression"],
        },
    }


def damage_expression(damage_dice: str, modifier: int, critical: bool) -> str:
    """Damage roll for a validated damage_dice string: dice count doubled on a crit, flat unchanged."""
    dice = _DICE_RE.fullmatch(damage_dice)
    if dice is None:
        return f"{damage_dice}{_signed(modifier)}"
    count = int(dice.group(1) or 1) * (2 if critical else 1)
    return f"{count}d{dice.group(2)}{_signed(modifier)}"


def _signed(modifier: int) -> str:
    return f"{modifier:+d}" if modifier else ""


def _parse(args: str) -> tuple[str, int | None]:
    """Returns (weapon name, AC or None). Every parse failure is a usage error."""
    text = args.strip()
    if not text:
        raise ToolError(HELP)
    matches = list(_VS_RE.finditer(text))
    if not matches:
        return text, None
    match = matches[-1]
    name = text[: match.start()].strip()
    ac_text = text[match.end() :].strip()
    if not name or _AC_RE.fullmatch(ac_text) is None:
        raise ToolError(HELP)
    ac = int(ac_text)
    if not 1 <= ac <= 40:
        raise ToolError(HELP)
    return name, ac


def _catalog(context: dict) -> list:
    reference = context.get("reference") or {}
    return reference.get("weapons") or []


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


def _lookup(name: str, weapons: list):
    if not weapons:
        raise ToolError(_CATALOG_MISSING)
    query = _norm(name)
    unknown = ToolError(f'Unknown weapon "{name}". Check the spelling or use a more exact name.')
    if not query:
        raise unknown
    candidates = [w for w in weapons if _norm(w.name) == query]
    if not candidates:
        candidates = [w for w in weapons if query in _norm(w.name)]
    if not candidates:
        raise unknown
    if len({_norm(w.name) for w in candidates}) > 1:
        labels = sorted({w.name for w in candidates})[:5]
        raise ToolError(
            f'"{name}" matches several weapons: {", ".join(labels)}. Use a more exact name.'
        )
    return min(candidates, key=lambda w: (w.edition != "5.5e", w.third_party, w.id))


def _check_damage(weapon) -> None:
    """Reject damage_dice the roll parser would refuse, before the attack is rolled."""
    damage_dice = weapon.damage_dice
    message = f"{weapon.name} has no usable damage dice in the weapon catalog."
    if damage_dice is None:
        raise ToolError(message)
    dice = _DICE_RE.fullmatch(damage_dice)
    if dice is not None:
        count = int(dice.group(1) or 1)
        sides = int(dice.group(2))
        if not (1 <= count and 2 * count <= MAX_DICE_PER_TERM and MIN_SIDES <= sides <= MAX_SIDES):
            raise ToolError(message)
    elif _FLAT_RE.fullmatch(damage_dice) is None:
        raise ToolError(message)


def _hit(nat: int, total: int, ac: int | None) -> bool | None:
    if nat == 20:
        return True
    if nat == 1:
        return False
    if ac is None:
        return None
    return total >= ac


def _verdict(nat: int, hit: bool | None, critical: bool) -> str:
    if critical:
        return "Critical hit!"
    if nat == 1:
        return "Natural 1: miss."
    if hit is True:
        return "Hit!"
    if hit is False:
        return "Miss."
    return "No AC given: roll the damage after the DM calls a hit."
