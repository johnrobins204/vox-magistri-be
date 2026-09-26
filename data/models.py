# models_optimized.py
"""
Optimized SQLAlchemy declarative models for the campaign / DM system.

Key improvements applied:
- Use SQLAlchemy Enum columns for strong DB-level constraints where appropriate.
- Use explicit `nullable=` on optional columns.
- Use `server_default=func.now()` for created_at timestamps (DB-side default).
- Add a small TimestampMixin to reduce repetition.
- Make enum defaults explicit via `.value`.
- Add a few helpful indexes and explicit UniqueConstraint comments preserved.
- Keep relationships and cascade semantics as in the original schema.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# Base and mixins
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Enums (StrEnum) and helper to use them in SA Enum columns
# ---------------------------------------------------------------------------
class CharacterKind(StrEnum):
    PLAYER_CHARACTER = "Player character"
    NPC = "NPC"


class CharacterClass(StrEnum):
    BARBARIAN = "Barbarian"
    BARD = "Bard"
    CLERIC = "Cleric"
    DRUID = "Druid"
    FIGHTER = "Fighter"
    MONK = "Monk"
    PALADIN = "Paladin"
    RANGER = "Ranger"
    ROGUE = "Rogue"
    SORCERER = "Sorcerer"
    WARLOCK = "Warlock"
    WIZARD = "Wizard"


class CharacterAncestry(StrEnum):
    AASIMAR = "Aasimar"
    DRAGONBORN = "Dragonborn"
    DWARF = "Dwarf"
    ELF = "Elf"
    GNOME = "Gnome"
    GOLIATH = "Goliath"
    HALFLING = "Halfling"
    HUMAN = "Human"
    ORC = "Orc"
    TIEFLING = "Tiefling"


class Alignment(StrEnum):
    LAWFUL_GOOD = "Lawful Good"
    NEUTRAL_GOOD = "Neutral Good"
    CHAOTIC_GOOD = "Chaotic Good"
    LAWFUL_NEUTRAL = "Lawful Neutral"
    TRUE_NEUTRAL = "True Neutral"
    CHAOTIC_NEUTRAL = "Chaotic Neutral"
    LAWFUL_EVIL = "Lawful Evil"
    NEUTRAL_EVIL = "Neutral Evil"
    CHAOTIC_EVIL = "Chaotic Evil"


class QuestStatus(StrEnum):
    RUMOR = "Rumor"
    ACTIVE = "Active"
    COMPLETED = "Completed"
    FAILED = "Failed"


class QuestChapterStatus(StrEnum):
    LOCKED = "Locked"
    AVAILABLE = "Available"
    ACTIVE = "Active"
    COMPLETED = "Completed"


class QuestObjectiveStatus(StrEnum):
    HIDDEN = "Hidden"
    OPEN = "Open"
    COMPLETE = "Complete"
    FAILED = "Failed"


class QuestTriggerType(StrEnum):
    MANUAL = "Manual"
    LOCATION = "Location"
    JOURNAL = "Journal"
    OBJECTIVE = "Objective"
    ITEM = "Item"
    NPC = "NPC"
    COMBAT = "Combat"


class ItemKind(StrEnum):
    GEAR = "Gear"
    CONSUMABLE = "Consumable"
    WEAPON = "Weapon"
    ARMOR = "Armor"
    QUEST = "Quest item"
    TREASURE = "Treasure"


class JournalEntryKind(StrEnum):
    MEMORY = "Memory"
    SECRET = "Secret"
    RELATIONSHIP = "Relationship"
    GOAL = "Goal"
    NOTE = "Note"


class SessionRunStatus(StrEnum):
    PLANNED = "Planned"
    ACTIVE = "Active"
    COMPLETE = "Complete"


class GameStatus(StrEnum):
    PLANNED = "Planned"
    ACTIVE = "Active"
    COMPLETE = "Complete"


class SessionEntryKind(StrEnum):
    SCENE = "Scene"
    NARRATION = "Narration"
    DM_NOTE = "DM note"
    TABLE_NOTE = "Table note"
    CHAT_INPUT = "Chat input"
    CHAT_OUTPUT = "Chat output"
    SYSTEM = "System"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    system: Mapped[str] = mapped_column(String(80), default="D&D 5e (2024)", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)

    players: Mapped[list[Player]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    characters: Mapped[list[Character]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    locations: Mapped[list[Location]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    quests: Mapped[list[Quest]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    journal_entries: Mapped[list[JournalEntry]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    encounters: Mapped[list[Encounter]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    items: Mapped[list[Item]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    maps: Mapped[list[CampaignMap]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    session_runs: Mapped[list[SessionRun]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    games: Mapped[list[Game]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    world_profile: Mapped[WorldProfile | None] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", uselist=False
    )


class Player(TimestampMixin, Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    campaign: Mapped[Campaign] = relationship(back_populates="players")
    characters: Mapped[list[Character]] = relationship(back_populates="player")


class Character(TimestampMixin, Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(
        SAEnum(CharacterKind, name="character_kind"),
        default=CharacterKind.NPC.value,
        nullable=False,
    )
    ancestry: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    class_name: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    armor_class: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_hp: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_hp: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    campaign: Mapped[Campaign] = relationship(back_populates="characters")
    player: Mapped[Player | None] = relationship(back_populates="characters")
    sheet: Mapped[CharacterSheet | None] = relationship(
        back_populates="character", cascade="all, delete-orphan", uselist=False
    )
    abilities: Mapped[list[CharacterAbility]] = relationship(
        back_populates="character", cascade="all, delete-orphan"
    )
    skills: Mapped[list[CharacterSkill]] = relationship(
        back_populates="character", cascade="all, delete-orphan"
    )
    features: Mapped[list[CharacterFeature]] = relationship(
        back_populates="character", cascade="all, delete-orphan"
    )
    journal_entries: Mapped[list[CharacterJournalEntry]] = relationship(
        back_populates="character", cascade="all, delete-orphan"
    )
    inventory: Mapped[list[InventoryItem]] = relationship(
        back_populates="character", cascade="all, delete-orphan"
    )
    quest_links: Mapped[list[QuestCharacter]] = relationship(
        back_populates="character", cascade="all, delete-orphan"
    )
    games: Mapped[list[Game]] = relationship(back_populates="character")
    game_links: Mapped[list[GameCharacter]] = relationship(
        back_populates="character", cascade="all, delete-orphan"
    )
    session_runs: Mapped[list[SessionRun]] = relationship(back_populates="character")


class Location(TimestampMixin, Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    environment: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    secrets: Mapped[str] = mapped_column(Text, default="", nullable=False)

    campaign: Mapped[Campaign] = relationship(back_populates="locations")


class Quest(TimestampMixin, Base):
    __tablename__ = "quests"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(QuestStatus, name="quest_status"), default=QuestStatus.RUMOR.value, nullable=False
    )
    hook: Mapped[str] = mapped_column(Text, default="", nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reward: Mapped[str] = mapped_column(Text, default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    campaign: Mapped[Campaign] = relationship(back_populates="quests")
    chapters: Mapped[list[QuestChapter]] = relationship(
        back_populates="quest",
        cascade="all, delete-orphan",
        order_by="QuestChapter.sort_order",
    )
    objectives: Mapped[list[QuestObjective]] = relationship(
        back_populates="quest",
        cascade="all, delete-orphan",
        order_by="QuestObjective.sort_order",
    )
    triggers: Mapped[list[QuestTrigger]] = relationship(
        back_populates="quest", cascade="all, delete-orphan"
    )
    rewards: Mapped[list[QuestReward]] = relationship(
        back_populates="quest", cascade="all, delete-orphan"
    )
    map_links: Mapped[list[QuestMap]] = relationship(
        back_populates="quest", cascade="all, delete-orphan"
    )
    item_links: Mapped[list[QuestItem]] = relationship(
        back_populates="quest", cascade="all, delete-orphan"
    )
    npc_links: Mapped[list[QuestCharacter]] = relationship(
        back_populates="quest", cascade="all, delete-orphan"
    )
    table_games: Mapped[list[Game]] = relationship(back_populates="quest")
    session_runs: Mapped[list[SessionRun]] = relationship(back_populates="quest")


class JournalEntry(TimestampMixin, Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tags: Mapped[str] = mapped_column(String(240), default="", nullable=False)

    campaign: Mapped[Campaign] = relationship(back_populates="journal_entries")


class Encounter(TimestampMixin, Base):
    __tablename__ = "encounters"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    active_turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    campaign: Mapped[Campaign] = relationship(back_populates="encounters")
    combatants: Mapped[list[Combatant]] = relationship(
        back_populates="encounter", cascade="all, delete-orphan"
    )


class Combatant(TimestampMixin, Base):
    __tablename__ = "combatants"

    id: Mapped[int] = mapped_column(primary_key=True)
    encounter_id: Mapped[int] = mapped_column(
        ForeignKey("encounters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    initiative: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    armor_class: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_hp: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_hp: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    conditions: Mapped[str] = mapped_column(String(240), default="", nullable=False)

    encounter: Mapped[Encounter] = relationship(back_populates="combatants")


class CharacterSheet(TimestampMixin, Base):
    __tablename__ = "character_sheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), unique=True, index=True
    )
    background: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    alignment: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    experience_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    temporary_hp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hit_dice: Mapped[str] = mapped_column(String(30), default="", nullable=False)
    speed: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    proficiency_bonus: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    passive_perception: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    inspiration: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    death_save_successes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    death_save_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    spellcasting_ability: Mapped[str] = mapped_column(String(30), default="", nullable=False)
    spell_save_dc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spell_attack_bonus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ability_score_method: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    character: Mapped[Character] = relationship(back_populates="sheet")


class CharacterAbility(TimestampMixin, Base):
    __tablename__ = "character_abilities"
    __table_args__ = (UniqueConstraint("character_id", "ability_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), index=True
    )
    ability_name: Mapped[str] = mapped_column(String(30), nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    modifier: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    save_proficient: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    save_bonus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    character: Mapped[Character] = relationship(back_populates="abilities")


class CharacterSkill(TimestampMixin, Base):
    __tablename__ = "character_skills"
    __table_args__ = (UniqueConstraint("character_id", "skill_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), index=True
    )
    skill_name: Mapped[str] = mapped_column(String(60), nullable=False)
    ability_name: Mapped[str] = mapped_column(String(30), nullable=False)
    proficiency_rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bonus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    character: Mapped[Character] = relationship(back_populates="skills")


class CharacterFeature(TimestampMixin, Base):
    __tablename__ = "character_features"

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(60), default="Feature", nullable=False)
    source: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    uses_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uses_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recharge: Mapped[str] = mapped_column(String(60), default="", nullable=False)

    character: Mapped[Character] = relationship(back_populates="features")


class CharacterJournalEntry(TimestampMixin, Base):
    __tablename__ = "character_journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(40), default=JournalEntryKind.NOTE.value, nullable=False
    )
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    session_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_private: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tags: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    character: Mapped[Character] = relationship(back_populates="journal_entries")


class Item(TimestampMixin, Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(
        SAEnum(ItemKind, name="item_kind"), default=ItemKind.GEAR.value, nullable=False
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_gp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rarity: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    is_unique: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    campaign: Mapped[Campaign] = relationship(back_populates="items")
    inventory_entries: Mapped[list[InventoryItem]] = relationship(back_populates="item")
    quest_links: Mapped[list[QuestItem]] = relationship(back_populates="item")
    rewards: Mapped[list[QuestReward]] = relationship(back_populates="item")


class InventoryItem(TimestampMixin, Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL"), nullable=True
    )
    custom_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    equipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attuned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    character: Mapped[Character] = relationship(back_populates="inventory")
    item: Mapped[Item | None] = relationship(back_populates="inventory_entries")


class CampaignMap(TimestampMixin, Base):
    __tablename__ = "maps"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    grid_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    campaign: Mapped[Campaign] = relationship(back_populates="maps")
    markers: Mapped[list[MapMarker]] = relationship(
        back_populates="map", cascade="all, delete-orphan"
    )
    quest_links: Mapped[list[QuestMap]] = relationship(
        back_populates="map", cascade="all, delete-orphan"
    )


class MapMarker(TimestampMixin, Base):
    __tablename__ = "map_markers"

    id: Mapped[int] = mapped_column(primary_key=True)
    map_id: Mapped[int] = mapped_column(ForeignKey("maps.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    marker_type: Mapped[str] = mapped_column(
        String(60), default="Point of interest", nullable=False
    )
    x: Mapped[float | None] = mapped_column(Float, nullable=True)
    y: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    map: Mapped[CampaignMap] = relationship(back_populates="markers")
    location: Mapped[Location | None] = relationship()


class QuestChapter(TimestampMixin, Base):
    __tablename__ = "quest_chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(QuestChapterStatus, name="quest_chapter_status"),
        default=QuestChapterStatus.LOCKED.value,
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    dm_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    quest: Mapped[Quest] = relationship(back_populates="chapters")
    objectives: Mapped[list[QuestObjective]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", order_by="QuestObjective.sort_order"
    )
    triggers: Mapped[list[QuestTrigger]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan"
    )
    rewards: Mapped[list[QuestReward]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan"
    )


class QuestObjective(TimestampMixin, Base):
    __tablename__ = "quest_objectives"

    id: Mapped[int] = mapped_column(primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("quest_chapters.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(QuestObjectiveStatus, name="quest_objective_status"),
        default=QuestObjectiveStatus.OPEN.value,
        nullable=False,
    )
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completion_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    quest: Mapped[Quest] = relationship(back_populates="objectives")
    chapter: Mapped[QuestChapter | None] = relationship(back_populates="objectives")


class QuestTrigger(TimestampMixin, Base):
    __tablename__ = "quest_triggers"

    id: Mapped[int] = mapped_column(primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("quest_chapters.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    trigger_type: Mapped[str] = mapped_column(
        SAEnum(QuestTriggerType, name="quest_trigger_type"),
        default=QuestTriggerType.MANUAL.value,
        nullable=False,
    )
    condition: Mapped[str] = mapped_column(Text, default="", nullable=False)
    effect: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_fired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    quest: Mapped[Quest] = relationship(back_populates="triggers")
    chapter: Mapped[QuestChapter | None] = relationship(back_populates="triggers")


class QuestReward(TimestampMixin, Base):
    __tablename__ = "quest_rewards"

    id: Mapped[int] = mapped_column(primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("quest_chapters.id", ondelete="CASCADE"), nullable=True
    )
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    experience_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gold_pieces: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    quest: Mapped[Quest] = relationship(back_populates="rewards")
    chapter: Mapped[QuestChapter | None] = relationship(back_populates="rewards")
    item: Mapped[Item | None] = relationship(back_populates="rewards")


class QuestMap(TimestampMixin, Base):
    __tablename__ = "quest_maps"
    __table_args__ = (UniqueConstraint("quest_id", "map_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id", ondelete="CASCADE"), index=True)
    map_id: Mapped[int] = mapped_column(ForeignKey("maps.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(120), default="Reference", nullable=False)

    quest: Mapped[Quest] = relationship(back_populates="map_links")
    map: Mapped[CampaignMap] = relationship(back_populates="quest_links")


class Game(TimestampMixin, Base):
    __tablename__ = "games"
    __table_args__ = (UniqueConstraint("campaign_id", "character_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), index=True
    )
    quest_id: Mapped[int | None] = mapped_column(
        ForeignKey("quests.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(GameStatus, name="game_status"), default=GameStatus.ACTIVE.value, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    campaign: Mapped[Campaign] = relationship(back_populates="games")
    character: Mapped[Character] = relationship(back_populates="games")
    quest: Mapped[Quest | None] = relationship(back_populates="table_games")
    character_links: Mapped[list[GameCharacter]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    session_runs: Mapped[list[SessionRun]] = relationship(back_populates="game")


class GameCharacter(TimestampMixin, Base):
    __tablename__ = "game_characters"
    __table_args__ = (UniqueConstraint("game_id", "character_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), index=True
    )

    game: Mapped[Game] = relationship(back_populates="character_links")
    character: Mapped[Character] = relationship(back_populates="game_links")


class QuestItem(TimestampMixin, Base):
    __tablename__ = "quest_items"
    __table_args__ = (UniqueConstraint("quest_id", "item_id", "role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(40), default="Mentioned", nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    quest: Mapped[Quest] = relationship(back_populates="item_links")
    item: Mapped[Item] = relationship(back_populates="quest_links")


class QuestCharacter(TimestampMixin, Base):
    __tablename__ = "quest_characters"
    __table_args__ = (UniqueConstraint("quest_id", "character_id", "role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(80), default="NPC", nullable=False)
    relationship_label: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    quest: Mapped[Quest] = relationship(back_populates="npc_links")
    character: Mapped[Character] = relationship(back_populates="quest_links")


class SessionRun(TimestampMixin, Base):
    __tablename__ = "session_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    game_id: Mapped[int | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL"), nullable=True
    )
    character_id: Mapped[int | None] = mapped_column(
        ForeignKey("characters.id", ondelete="SET NULL"), nullable=True
    )
    quest_id: Mapped[int | None] = mapped_column(
        ForeignKey("quests.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    session_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum(SessionRunStatus, name="session_run_status"),
        default=SessionRunStatus.PLANNED.value,
        nullable=False,
    )
    current_scene: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    campaign: Mapped[Campaign] = relationship(back_populates="session_runs")
    game: Mapped[Game | None] = relationship(back_populates="session_runs")
    character: Mapped[Character | None] = relationship(back_populates="session_runs")
    quest: Mapped[Quest | None] = relationship(back_populates="session_runs")
    entries: Mapped[list[SessionEntry]] = relationship(
        back_populates="session_run",
        cascade="all, delete-orphan",
        order_by="SessionEntry.created_at",
    )


class SessionEntry(TimestampMixin, Base):
    __tablename__ = "session_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_run_id: Mapped[int] = mapped_column(
        ForeignKey("session_runs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(
        SAEnum(SessionEntryKind, name="session_entry_kind"),
        default=SessionEntryKind.TABLE_NOTE.value,
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_dm_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    session_run: Mapped[SessionRun] = relationship(back_populates="entries")


class WorldProfile(TimestampMixin, Base):
    __tablename__ = "world_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    premise: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mood: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    scope: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    starting_region: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    geography: Mapped[str] = mapped_column(Text, default="", nullable=False)
    everyday_life: Mapped[str] = mapped_column(Text, default="", nullable=False)

    campaign: Mapped[Campaign] = relationship(back_populates="world_profile")
    history_events: Mapped[list[WorldHistoryEvent]] = relationship(
        back_populates="world", cascade="all, delete-orphan"
    )
    factions: Mapped[list[WorldFaction]] = relationship(
        back_populates="world", cascade="all, delete-orphan"
    )
    magic_rules: Mapped[list[WorldMagicRule]] = relationship(
        back_populates="world", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Optional: add indexes for common queries
# ---------------------------------------------------------------------------
Index("ix_quest_campaign_status", Quest.__table__.c.campaign_id, Quest.__table__.c.status)
Index(
    "ix_sessionrun_campaign_status",
    SessionRun.__table__.c.campaign_id,
    SessionRun.__table__.c.status,
)


# ---------------------------------------------------------------------------
# Canonical ORM exports
# ---------------------------------------------------------------------------

# Export Base and metadata so migrations and repos use a single source of truth.
Base = Base
metadata = Base.metadata

# ---------------------------------------------------------------------------
# Session factory helper
# ---------------------------------------------------------------------------
from sqlalchemy.orm import sessionmaker

def make_session_factory(engine):
    """
    Create a configured SQLAlchemy session factory.

    Usage:
        SessionFactory = make_session_factory(engine)
        with SessionFactory() as session:
            ...
    """
    return sessionmaker(bind=engine, expire_on_commit=False)

