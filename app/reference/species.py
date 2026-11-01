# reference/species.py
"""
Species catalog model and fail-soft loader (SPEC-0011 WP-2; ADR-0006, PAT-ARCH-006).

load_species() reads the normalized app/reference/species.json once, when services are built.
It never raises: a missing or invalid file logs one WARNING and returns []; an invalid or
duplicate entry is dropped with one WARNING each. Logs carry reasons and indexes only.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.reference.loader import load_entries
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
    return load_entries(path, Species, "species", logger)
