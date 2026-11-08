"""SPEC-0018 test helper: a valid Creature built in memory (no file I/O)."""

import re

from app.reference.creatures import Creature

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def make_creature(name: str, edition: str = "5.5e", **overrides) -> Creature:
    slug = _NON_SLUG.sub("-", name.lower()).strip("-")
    suffix = "-5e" if edition == "5e" else ""
    fields = {
        "id": f"{slug}{suffix}",
        "name": name,
        "edition": edition,
        "source": "Test Source",
        "publisher": "Test Publisher",
        "third_party": False,
        "source_key": "test-source-key",
        "cr": 0.25,
        **overrides,
    }
    return Creature(**fields)
