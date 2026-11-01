# reference/weapons.py
"""Weapon model for the open5e weapons pilot (SPEC-0012 WP-4; ADR-0007, PAT-ARCH-006)."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WEAPONS_PATH = Path(__file__).resolve().parent / "weapons.json"


class Weapon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str
    edition: Literal["5e", "5.5e"] | None
    source: str
    publisher: str | None
    third_party: bool
    source_key: str
    damage_dice: str | None
    damage_type: str | None
    properties: list[str]
    range: int
    long_range: int
    distance_unit: str | None
    is_simple: bool
    is_improvised: bool
