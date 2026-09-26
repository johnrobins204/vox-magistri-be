# data/repos.py
"""
Repository implementations and interfaces for the DnD DM project.

This module provides:
- Thin repository interfaces (duck-typed) expected by services.
- In-memory fallback implementations suitable for MVP and tests.
- Small helpers to seed sample data.

Repos are intentionally simple: methods return plain dicts/lists and do
not depend on SQLAlchemy. Services call repos; repos are responsible for
persistence (DB, file, etc.) in a real deployment.

Provided repos:
- CharacterRepo (in-memory: InMemoryCharacterRepo)
- QuestRepo (in-memory: InMemoryQuestRepo)
- GameRepo (in-memory: InMemoryGameRepo)
- SessionRepo (in-memory: InMemorySessionRepo)
- Generic helper: InMemoryRepoBase
"""

from __future__ import annotations

import builtins
import copy
import threading
import time
from typing import Any


# -------------------------
# Base in-memory repo
# -------------------------
class InMemoryRepoBase:
    """
    Minimal thread-safe in-memory store keyed by integer id.
    Subclasses should call self._next_id() and self._store to manage items.
    """

    def __init__(self):
        self._store: dict[int, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._next = 1

    def _next_id(self) -> int:
        with self._lock:
            nid = self._next
            self._next += 1
            return nid

    def _clone(self, obj: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(obj)

    # Generic operations -------------------------------------------------
    def list(self) -> builtins.list[dict[str, Any]]:
        with self._lock:
            return [
                self._clone(v) for v in sorted(self._store.values(), key=lambda x: x.get("id", 0))
            ]

    def get(self, obj_id: int) -> dict[str, Any] | None:
        with self._lock:
            v = self._store.get(obj_id)
            return self._clone(v) if v is not None else None

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            nid = self._next_id()
            item = dict(payload)
            item["id"] = nid
            item.setdefault("created_at", time.time())
            self._store[nid] = item
            return self._clone(item)

    def update(self, obj_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            if obj_id not in self._store:
                return None
            self._store[obj_id].update(patch)
            return self._clone(self._store[obj_id])

    def delete(self, obj_id: int) -> bool:
        with self._lock:
            if obj_id in self._store:
                del self._store[obj_id]
                return True
            return False

    def find(self, predicate) -> builtins.list[dict[str, Any]]:
        with self._lock:
            return [self._clone(v) for v in self._store.values() if predicate(v)]


# -------------------------
# Character repo
# -------------------------
class InMemoryCharacterRepo(InMemoryRepoBase):
    """
    Character repository with a couple of convenience methods used by UI/services.
    """

    def list_by_campaign(self, campaign_id: int) -> list[dict[str, Any]]:
        return self.find(lambda v: v.get("campaign_id") == campaign_id)

    def list_by_player(self, player_id: int) -> list[dict[str, Any]]:
        return self.find(lambda v: v.get("player_id") == player_id)

    def create_character(self, payload: dict[str, Any]) -> dict[str, Any]:
        # normalize minimal fields
        payload = dict(payload)
        payload.setdefault("name", "Unnamed")
        payload.setdefault("level", 1)
        payload.setdefault("max_hp", 1)
        payload.setdefault("current_hp", payload.get("max_hp", 1))
        return self.create(payload)


# -------------------------
# Quest repo
# -------------------------
class InMemoryQuestRepo(InMemoryRepoBase):
    """
    Quest repository with helpers for active quest and objectives.
    """

    def list_by_campaign(self, campaign_id: int) -> list[dict[str, Any]]:
        return self.find(lambda v: v.get("campaign_id") == campaign_id)

    def get_active(self, campaign_id: int) -> dict[str, Any] | None:
        # Active defined as status == "Active"
        res = self.find(
            lambda v: v.get("campaign_id") == campaign_id and v.get("status") == "Active"
        )
        return res[0] if res else None

    def create_quest(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        payload.setdefault("title", "Untitled Quest")
        payload.setdefault("status", payload.get("status", "Rumor"))
        payload.setdefault("objectives", payload.get("objectives", []))
        return self.create(payload)


# -------------------------
# Game repo
# -------------------------
class InMemoryGameRepo(InMemoryRepoBase):
    """
    Game repository used by GameService. Supports simple lookups.
    """

    def list_by_campaign(self, campaign_id: int) -> list[dict[str, Any]]:
        return self.find(lambda v: v.get("campaign_id") == campaign_id)

    def find_by_character_and_campaign(
        self, campaign_id: int, character_id: int
    ) -> list[dict[str, Any]]:
        return self.find(
            lambda v: v.get("campaign_id") == campaign_id and v.get("character_id") == character_id
        )

    def create_game(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        payload.setdefault("name", "New Game")
        payload.setdefault("status", "Active")
        return self.create(payload)


# -------------------------
# Session repo
# -------------------------
class InMemorySessionRepo:
    """
    Session repo specialized for session runs and entries. Kept separate because
    session entries are stored per-run and have ordering semantics.
    """

    def __init__(self):
        self._runs: dict[int, dict[str, Any]] = {}
        self._entries: dict[int, list[dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._next_run = 1
        self._next_entry = 1

    # Runs ---------------------------------------------------------------
    def create_for_game(
        self, game_id: int, starter: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self._lock:
            rid = self._next_run
            self._next_run += 1
            run = {
                "id": rid,
                "game_id": game_id,
                "starter": starter or {},
                "active": True,
                "created_at": time.time(),
            }
            self._runs[rid] = run
            self._entries[rid] = []
            return copy.deepcopy(run)

    def get_active_for_game(self, game_id: int) -> dict[str, Any] | None:
        with self._lock:
            for run in self._runs.values():
                if run.get("game_id") == game_id and run.get("active"):
                    return copy.deepcopy(run)
            return None

    def end(self, run_id: int) -> bool:
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return False
            run["active"] = False
            run["ended_at"] = time.time()
            return True

    # Entries ------------------------------------------------------------
    def append_entry(self, run_id: int, entry: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if run_id not in self._entries:
                self._entries[run_id] = []
            entry = dict(entry)
            entry.setdefault("id", self._next_entry)
            self._next_entry += 1
            entry.setdefault("created_at", time.time())
            self._entries[run_id].append(entry)
            return copy.deepcopy(entry)

    def list_entries(self, run_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._entries.get(run_id, []))


# -------------------------
# Convenience factory to produce a repos dict for services
# -------------------------
def make_default_repos() -> dict[str, Any]:
    """
    Return a dict of default in-memory repos keyed by conventional names used by services.
    Example keys: 'character', 'quest', 'game', 'session'
    """
    return {
        "character": InMemoryCharacterRepo(),
        "quest": InMemoryQuestRepo(),
        "game": InMemoryGameRepo(),
        "session": InMemorySessionRepo(),
    }


# -------------------------
# Small seed helper for development
# -------------------------
def seed_sample_data(repos: dict[str, Any]) -> None:
    """
    Populate provided repos with a few sample items for local development.
    Safe to call multiple times; it will not overwrite existing items.
    """
    char_repo: InMemoryCharacterRepo | None = repos.get("character")
    quest_repo: InMemoryQuestRepo | None = repos.get("quest")
    game_repo: InMemoryGameRepo | None = repos.get("game")

    if char_repo and not char_repo.list():
        char_repo.create_character(
            {
                "name": "Aria",
                "class_name": "Rogue",
                "level": 3,
                "max_hp": 18,
                "current_hp": 18,
                "campaign_id": 1,
            }
        )
        char_repo.create_character(
            {
                "name": "Borin",
                "class_name": "Fighter",
                "level": 2,
                "max_hp": 22,
                "current_hp": 22,
                "campaign_id": 1,
            }
        )
    if quest_repo and not quest_repo.list():
        quest_repo.create_quest(
            {
                "campaign_id": 1,
                "title": "The Missing Heirloom",
                "status": "Active",
                "objectives": [
                    {"text": "Investigate the manor grounds", "done": False},
                    {"text": "Question the suspicious merchant", "done": False},
                ],
            }
        )
    if game_repo and not game_repo.list():
        game_repo.create_game(
            {"campaign_id": 1, "character_id": 1, "name": "Demo Table", "status": "Active"}
        )


# -------------------------
# Module-level convenience: default repos instance
# -------------------------
_default_repos = make_default_repos()
# seed_sample_data(_default_repos)  # uncomment during local dev if desired

# Expose default repos for quick wiring in app.main
DEFAULT_REPOS = _default_repos
