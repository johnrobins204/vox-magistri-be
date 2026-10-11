# app/intelligence/tools/roll.py
"""
`/roll` tool: a small dice parser (REQ-0008, SPEC-0007 WP-3).

Grammar (case-insensitive; whitespace only between terms, around `+` and `-`):
    expr := term (('+'|'-') term)*
    term := dice | INT | 'adv' | 'dis'
    dice := INT? 'd' INT (('kh'|'kl') INT)?
    INT  := [0-9]{1,4}
`adv` is `2d20kh1`, `dis` is `2d20kl1`. Blank args mean `1d20`.

`evaluate` is pure apart from the injected rng, which is only ever asked for
`rng.randint(1, sides)`. Syntax is checked for the whole expression before any
bound, and bounds before any roll.
"""

import random
import re
from typing import Any

from app.intelligence.tools import ToolError

NAME = "roll"

_DEFAULT_RNG = random.Random()

DEFAULT_EXPR = "1d20"
MAX_EXPR_LENGTH = 64
MAX_TERMS = 10
MAX_DICE_PER_TERM = 100
MAX_TOTAL_DICE = 100
MIN_SIDES = 2
MAX_SIDES = 1000
MAX_CONSTANT = 1000

_USAGE = "Invalid dice expression. Usage: /roll [NdM[kh|klK]][+/-...] (e.g. 2d6+3, adv)"

_TERM_RE = re.compile(
    r"(?:(?P<count>[0-9]{1,4})?d(?P<sides>[0-9]{1,4})(?:(?P<mode>kh|kl)(?P<keep>[0-9]{1,4}))?"
    r"|(?P<word>adv|dis)"
    r"|(?P<const>[0-9]{1,4}))"
)


def run(args: str, context: dict) -> dict[str, Any]:
    rng = context.get("rng")
    if rng is None:
        rng = _DEFAULT_RNG
    return evaluate(args, rng)


def evaluate(expr: str, rng: Any) -> dict[str, Any]:
    text = expr.strip()
    if len(text) > MAX_EXPR_LENGTH:
        raise ToolError(f"Expression too long (max {MAX_EXPR_LENGTH} characters)")
    text = text.lower() or DEFAULT_EXPR
    normalized = re.sub(r"\s+", "", text)

    specs = _parse(text)

    pieces: list[str] = []
    term_metas: list[dict[str, Any]] = []
    total = 0
    for index, spec in enumerate(specs):
        body, meta = _roll_term(spec, rng)
        pieces.append(body if index == 0 else f" {spec['sign']} {body}")
        term_metas.append(meta)
        total += meta["value"] if spec["sign"] == "+" else -meta["value"]

    return {
        "text": f"{normalized}: {''.join(pieces)} = {total}",
        "meta": {
            "tool": NAME,
            "expression": normalized,
            "total": total,
            "terms": term_metas,
        },
    }


def _parse(text: str) -> list[dict[str, Any]]:
    """Syntax first (every term), then term count, then per-term bounds, then total dice."""
    pieces = re.split(r"\s*([+-])\s*", text)
    raws = pieces[0::2]
    signs = ["+", *pieces[1::2]]

    matches = []
    for raw in raws:
        match = _TERM_RE.fullmatch(raw)
        if match is None:
            raise ToolError(_USAGE)
        matches.append(match)

    if len(matches) > MAX_TERMS:
        raise ToolError(f"At most {MAX_TERMS} terms")

    specs = [_check_term(sign, match) for sign, match in zip(signs, matches, strict=True)]

    total_dice = sum(spec["count"] for spec in specs if spec["kind"] == "dice")
    if total_dice > MAX_TOTAL_DICE:
        raise ToolError(f"Total dice must be at most {MAX_TOTAL_DICE}")
    return specs


def _check_term(sign: str, match: re.Match[str]) -> dict[str, Any]:
    if match.group("word") is not None:
        return {
            "kind": "dice",
            "sign": sign,
            "count": 2,
            "sides": 20,
            "keep": 1,
            "lowest": match.group("word") == "dis",
        }

    if match.group("sides") is None:
        value = int(match.group("const"))
        if value > MAX_CONSTANT:
            raise ToolError(f"Constants must be 0-{MAX_CONSTANT}")
        return {"kind": "const", "sign": sign, "value": value}

    count = 1 if match.group("count") is None else int(match.group("count"))
    sides = int(match.group("sides"))
    if not 1 <= count <= MAX_DICE_PER_TERM:
        raise ToolError(f"Dice count must be 1-{MAX_DICE_PER_TERM}")
    if not MIN_SIDES <= sides <= MAX_SIDES:
        raise ToolError(f"Dice sides must be {MIN_SIDES}-{MAX_SIDES}")

    keep = None
    lowest = False
    if match.group("mode") is not None:
        keep = int(match.group("keep"))
        if not 1 <= keep <= count:
            raise ToolError("Keep must be between 1 and the dice count")
        lowest = match.group("mode") == "kl"
    return {
        "kind": "dice",
        "sign": sign,
        "count": count,
        "sides": sides,
        "keep": keep,
        "lowest": lowest,
    }


def _roll_term(spec: dict[str, Any], rng: Any) -> tuple[str, dict[str, Any]]:
    """Roll one validated term. Returns (text fragment, meta dict with 'value')."""
    if spec["kind"] == "const":
        value = spec["value"]
        return str(value), {
            "sign": spec["sign"],
            "constant": value,
            "value": value,
        }

    count = spec["count"]
    rolls = [rng.randint(1, spec["sides"]) for _ in range(count)]
    if spec["keep"] is None:
        kept_idx = set(range(count))
    else:
        ranked = sorted(
            range(count),
            key=lambda i: (rolls[i] if spec["lowest"] else -rolls[i], i),
        )
        kept_idx = set(ranked[: spec["keep"]])

    shown = [str(r) if i in kept_idx else f"({r})" for i, r in enumerate(rolls)]
    kept = [r for i, r in enumerate(rolls) if i in kept_idx]
    value = sum(kept)
    return f"[{', '.join(shown)}]", {
        "sign": spec["sign"],
        "count": count,
        "sides": spec["sides"],
        "keep": spec["keep"],
        "rolls": rolls,
        "kept": kept,
        "value": value,
    }
