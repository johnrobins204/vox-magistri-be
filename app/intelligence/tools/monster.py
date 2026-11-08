# intelligence/tools/monster.py
"""
`/monster` tool (SPEC-0018 WP-7; ADR-0012, PAT-ARCH-011, PAT-ARCH-009).

`run` looks the name up in `context["reference"]["creatures"]` (the in-memory catalog loaded at
startup). A hit is rendered by `render_stat_block` and makes no LLM call. A true miss makes
exactly one flagged training call. The tool never touches the store, never writes, and logs
counts and source only.
"""

from typing import Any

from app.intelligence.monster_blocks import find_creature, render_stat_block
from app.intelligence.prompt_builders import build_monster_prompt
from app.intelligence.tools import ToolError
from app.services.logger import get_logger

logger = get_logger(__name__)

NAME = "monster"

_USAGE = "Usage: /monster <monster name> [2014|2024]"
HELP = (
    "Usage: /monster <monster name> [2014|2024], e.g. /monster goblin or /monster goblin 2014. "
    "A monster in the SRD catalog is shown as its stat block; a 2014 or 2024 token picks the "
    "edition. A monster not in the catalog gets a general-knowledge answer, marked as not "
    "checked against the SRD monster text."
)
TRAINING_DISCLAIMER = "Not checked against the SRD monster text."


def run(args: str, context: dict) -> dict[str, Any]:
    text = (args or "").strip()
    if not text:
        raise ToolError(_USAGE)
    if text.lower() == "help":
        return {"text": HELP, "meta": {"tool": NAME, "help": True}}

    catalog = (context.get("reference") or {}).get("creatures") or []
    creature = find_creature(text, catalog)
    if creature is not None:
        rendered = render_stat_block(creature)
        logger.info(
            "monster.lookup",
            extra={"source": "creatures", "creature_count": 1, "rendered_chars": len(rendered)},
        )
        return {
            "text": rendered,
            "meta": {"tool": NAME, "source": "creatures", "creature_ids": [creature.id]},
        }

    reply = context["inference"].generate(build_monster_prompt(text))
    logger.info(
        "monster.lookup",
        extra={"source": "training", "creature_count": 0, "rendered_chars": 0},
    )
    return {
        "text": reply.rstrip() + "\n\n" + TRAINING_DISCLAIMER,
        "meta": {"tool": NAME, "source": "training", "creature_ids": []},
    }
