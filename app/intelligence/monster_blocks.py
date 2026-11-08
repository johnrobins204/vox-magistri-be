# intelligence/monster_blocks.py
"""
Pure stat-block renderer for the /monster lookup (SPEC-0018 WP-5; ADR-0012, PAT-ARCH-011).

render_stat_block() turns one Creature into plain text: no I/O, no logging, no store.
Lines are omitted when empty; text from the catalog is never truncated or reworded.
find_creature() matches a typed name against the catalog (SPEC-0018 WP-6; REQ-0031).
"""

import difflib
import re

from app.intelligence.tools import ToolError
from app.reference.creatures import Creature, StatEntry

_ABILITIES = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")
_SPEED_ORDER = ("walk", "burrow", "climb", "fly", "swim")
_CR_FRACTIONS = {0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}
_EDITION_YEAR = {"5e": "2014", "5.5e": "2024"}
_EDITION_TOKEN = {"2014": "5e", "2024": "5.5e"}
_LIST_LIMIT = 5
_SUGGEST_LIMIT = 3
_SUGGEST_CUTOFF = 0.8
_SECTIONS = (
    ("traits", "Traits"),
    ("actions", "Actions"),
    ("bonus_actions", "Bonus Actions"),
    ("reactions", "Reactions"),
    ("legendary_actions", "Legendary Actions"),
)


def render_stat_block(creature: Creature) -> str:
    lines = [_title(creature)]
    kind = " ".join(part for part in (creature.size, creature.type) if part)
    kind_line = ", ".join(part for part in (kind, creature.alignment) if part)
    if kind_line:
        lines.append(kind_line)
    if creature.armor_class is not None:
        lines.append(_with_detail(f"AC {creature.armor_class}", creature.armor_detail))
    if creature.hit_points is not None:
        lines.append(_with_detail(f"HP {creature.hit_points}", creature.hit_dice))
    speeds = [
        f"{key} {value} ft." for key, value in _in_order(creature.speed, _SPEED_ORDER) if value > 0
    ]
    if speeds:
        lines.append("Speed " + ", ".join(speeds))
    lines.append(_ability_line(creature))
    saves = [
        f"{key[:3].capitalize()} {value:+d}"
        for key, value in _in_order(creature.saving_throws, _ABILITIES)
    ]
    if saves:
        lines.append("Saving Throws " + ", ".join(saves))
    skills = [
        f"{_skill_name(key)} {value:+d}" for key, value in _in_order(creature.skill_bonuses, ())
    ]
    if skills:
        lines.append("Skills " + ", ".join(skills))
    for label, value in (
        ("Damage Vulnerabilities", creature.damage_vulnerabilities),
        ("Damage Resistances", creature.damage_resistances),
        ("Damage Immunities", creature.damage_immunities),
        ("Condition Immunities", creature.condition_immunities),
    ):
        if value:
            lines.append(f"{label} {value}")
    senses = [f"{key} {value} ft." for key, value in _in_order(creature.senses, ()) if value > 0]
    if creature.passive_perception is not None:
        senses.append(f"passive Perception {creature.passive_perception}")
    if senses:
        lines.append("Senses " + ", ".join(senses))
    lines.append(f"Languages {creature.languages or '—'}")
    lines.append(_challenge_line(creature))
    for field, heading in _SECTIONS:
        entries = getattr(creature, field)
        if entries:
            lines.append("")
            lines.append(heading)
            lines.extend(_entry_line(entry) for entry in entries)
    return "\n".join(lines)


def _title(creature: Creature) -> str:
    year = _EDITION_YEAR.get(creature.edition or "")
    return f"{creature.name} ({year})" if year else creature.name


def _with_detail(text: str, detail: str) -> str:
    return f"{text} ({detail})" if detail else text


def _in_order(mapping: dict, order: tuple) -> list:
    """Items by position in `order`; unknown keys follow, sorted by key."""
    rank = {key: index for index, key in enumerate(order)}
    return sorted(mapping.items(), key=lambda item: (rank.get(item[0], len(rank)), item[0]))


def _skill_name(key: str) -> str:
    return " ".join("of" if word == "of" else word.capitalize() for word in key.split("_"))


def _ability_line(creature: Creature) -> str:
    scores = creature.ability_scores
    parts = []
    for ability in _ABILITIES:
        score = getattr(scores, ability)
        modifier = (score - 10) // 2
        parts.append(f"{ability[:3].upper()} {score} ({modifier:+d})")
    return " ".join(parts)


def _challenge_line(creature: Creature) -> str:
    text = f"CR {_cr_text(creature.cr)}"
    if creature.experience_points is not None:
        text += f" (XP {creature.experience_points:,})"
    return text


def _cr_text(cr: float) -> str:
    if cr in _CR_FRACTIONS:
        return _CR_FRACTIONS[cr]
    return str(int(cr)) if float(cr).is_integer() else str(cr)


def _entry_line(entry: StatEntry) -> str:
    name = entry.name
    if entry.usage:
        name += f" ({entry.usage})"
    if entry.cost is not None and entry.cost > 1:
        name += f" (Costs {entry.cost} Actions)"
    return f"{name}. {entry.desc}"


def find_creature(query: str, creatures: list[Creature]) -> Creature | None:
    """Exact normalized name, then substring; a trailing 2014/2024 token limits the edition.

    Several distinct names raise ToolError; no match raises ToolError with difflib
    suggestions when any are close, else returns None. Pure: no I/O.
    """
    name, edition = _split_edition(_norm(query))
    if not name:
        return None
    pool = [c for c in creatures if edition is None or c.edition == edition]
    candidates = [c for c in pool if _norm(c.name) == name]
    if not candidates:
        candidates = [c for c in pool if name in _norm(c.name)]
    if not candidates:
        _suggest(query, name, pool)
        return None
    if len({_norm(c.name) for c in candidates}) > 1:
        labels = sorted({c.name for c in candidates})[:_LIST_LIMIT]
        raise ToolError(
            f'"{query}" matches several monsters: {", ".join(labels)}. Use a more exact name.'
        )
    return min(candidates, key=lambda c: (c.edition != "5.5e", c.third_party, c.id))


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


def _split_edition(normalized: str) -> tuple[str, str | None]:
    """Drop a final 2014/2024 token when a name is left in front of it."""
    head, _, last = normalized.rpartition(" ")
    if head and last in _EDITION_TOKEN:
        return head, _EDITION_TOKEN[last]
    return normalized, None


def _suggest(query: str, name: str, pool: list[Creature]) -> None:
    """Raise ToolError with close names; return quietly when nothing is close."""
    originals: dict[str, set[str]] = {}
    for creature in pool:
        originals.setdefault(_norm(creature.name), set()).add(creature.name)
    close = difflib.get_close_matches(
        name, sorted(originals), n=_SUGGEST_LIMIT, cutoff=_SUGGEST_CUTOFF
    )
    if not close:
        return
    labels = [min(originals[key]) for key in close]
    raise ToolError(f'No SRD monster named "{query}". Did you mean: {", ".join(labels)}?')
