# reference/species.py
"""
Species catalog model and fail-soft loader (SPEC-0011 WP-2; ADR-0006, PAT-ARCH-006).

load_species() reads the normalized app/reference/species.json once, when services are built.
It never raises: a missing or invalid file logs one WARNING and returns []; an invalid or
duplicate entry is dropped with one WARNING each. Logs carry reasons and indexes only.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.logger import get_logger

logger = get_logger(__name__)

SPECIES_PATH = Path(__file__).resolve().parent / "species.json"


class Species(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str
    edition: Literal["5e", "5.5e"] | None
    source: str
    publisher: str | None
    third_party: bool
    creature_type: str
    description: str
    character_creation_implications: str


def load_species(path: Path | str = SPECIES_PATH) -> list[Species]:
    """Load the species catalog from a JSON array file. Never raises; see module docstring."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        reason = "missing"
    except (OSError, UnicodeDecodeError):
        reason = "unreadable"
    except ValueError:
        reason = "invalid_json"
    else:
        if isinstance(data, list):
            return _validate_entries(data)
        reason = "not_list"
    logger.warning("reference.unavailable", extra={"reason": reason})
    return []


def _validate_entries(data: list) -> list[Species]:
    species: list[Species] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(data):
        try:
            entry = Species.model_validate(raw)
        except ValidationError:
            logger.warning("reference.entry_dropped", extra={"index": index, "reason": "invalid"})
            continue
        if entry.id in seen_ids:
            logger.warning(
                "reference.entry_dropped", extra={"index": index, "reason": "duplicate_id"}
            )
            continue
        seen_ids.add(entry.id)
        species.append(entry)
    return species
