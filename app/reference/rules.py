"""Rules model for the open5e `rules` dataset (SPEC-0014 WP-2; ADR-0009, PAT-ARCH-006)."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RULES_PATH = Path(__file__).resolve().parent / "rules.json"


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str
    edition: Literal["5e", "5.5e"] | None
    source: str
    publisher: str | None
    third_party: bool
    source_key: str
    description: str

    # NEW FIELD: Holds the cached embedding array for vector search
    vector: list[float] = Field(default_factory=list)
