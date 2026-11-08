# reference/creatures.py
"""Creature model for the open5e creatures dataset (SPEC-0018 WP-2; ADR-0012, PAT-ARCH-006)."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CREATURES_PATH = Path(__file__).resolve().parent / "creatures.json"


class StatEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    desc: str
    usage: str | None = None
    cost: int | None = None


class AbilityScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10


class Creature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str
    edition: Literal["5e", "5.5e"] | None
    source: str
    publisher: str | None
    third_party: bool
    source_key: str
    size: str = ""
    type: str = ""
    alignment: str = ""
    armor_class: int | None = None
    armor_detail: str = ""
    hit_points: int | None = None
    hit_dice: str = ""
    speed: dict[str, int] = Field(default_factory=dict)
    ability_scores: AbilityScores = Field(default_factory=AbilityScores)
    saving_throws: dict[str, int] = Field(default_factory=dict)
    skill_bonuses: dict[str, int] = Field(default_factory=dict)
    damage_vulnerabilities: str = ""
    damage_resistances: str = ""
    damage_immunities: str = ""
    condition_immunities: str = ""
    passive_perception: int | None = None
    senses: dict[str, int] = Field(default_factory=dict)
    languages: str = ""
    cr: float
    experience_points: int | None = None
    traits: list[StatEntry] = Field(default_factory=list)
    actions: list[StatEntry] = Field(default_factory=list)
    bonus_actions: list[StatEntry] = Field(default_factory=list)
    reactions: list[StatEntry] = Field(default_factory=list)
    legendary_actions: list[StatEntry] = Field(default_factory=list)
