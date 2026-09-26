# services/game_service.py
"""
GameService: orchestrates game-level operations.

Responsibilities:
- Create / list / get games
- Start and stop game sessions (delegates to SessionRepo)
- Persist game state via repos
- Provide small, testable methods used by UI scenes

Constructor:
    GameService(repos: dict, tool_service: Optional[object] = None)

Expected repos keys (optional):
    - 'game': GameRepo with methods create(name), get(id), list(), update(id, data)
    - 'session': SessionRepo with methods create_for_game(game_id), get_active_for_game(game_id), end(run_id)
    - 'character': CharacterRepo (optional)
    - 'quest': QuestRepo (optional)
"""

import time
from typing import Any


class GameService:
    def __init__(self, repos: dict[str, object] | None = None, tool_service: object | None = None):
        self.repos = repos or {}
        self.tool_service = tool_service

    # -------------------------
    # Game CRUD
    # -------------------------
    def create_game(self, name: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a new game. Returns the created game dict/DTO."""
        metadata = metadata or {}
        repo = self.repos.get("game")
        if repo and hasattr(repo, "create"):
            return repo.create(name=name, metadata=metadata)
        # fallback in-memory representation
        gid = int(time.time() * 1000)
        game = {"id": gid, "name": name, "metadata": metadata}
        # store in a simple in-memory repo if provided
        if repo is None:
            # create a minimal in-memory store on self.repos for dev convenience
            self.repos["game"] = _InMemoryGameRepo()
            return self.repos["game"].create(name=name, metadata=metadata)
        return game

    def list_games(self) -> list[dict[str, Any]]:
        """Return list of games."""
        repo = self.repos.get("game")
        if repo and hasattr(repo, "list"):
            return repo.list()
        # fallback empty
        return []

    def get_game(self, game_id: int) -> dict[str, Any] | None:
        """Return a single game by id or None."""
        repo = self.repos.get("game")
        if repo and hasattr(repo, "get"):
            return repo.get(game_id)
        return None

    def update_game(self, game_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
        """Apply a partial update to a game and persist it."""
        repo = self.repos.get("game")
        if repo and hasattr(repo, "update"):
            return repo.update(game_id, patch)
        # best-effort: if in-memory repo exists, try that
        if isinstance(self.repos.get("game"), _InMemoryGameRepo):
            return self.repos["game"].update(game_id, patch)
        return None

    # -------------------------
    # Session orchestration
    # -------------------------
    def start_session(self, game_id: int, starter: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Start or return an active session run for the given game.
        Delegates to SessionRepo.get_active_for_game or create_for_game.
        """
        session_repo = self.repos.get("session")
        if session_repo:
            # prefer get_active_for_game if available
            if hasattr(session_repo, "get_active_for_game"):
                active = session_repo.get_active_for_game(game_id)
                if active:
                    return active
            # otherwise create a new run
            if hasattr(session_repo, "create_for_game"):
                return session_repo.create_for_game(game_id, starter or {})
        # fallback: create a minimal in-memory run
        if "session" not in self.repos:
            self.repos["session"] = _InMemorySessionRepo()
        return self.repos["session"].create_for_game(game_id, starter or {})

    def end_session(self, run_id: int) -> bool:
        """End a session run."""
        session_repo = self.repos.get("session")
        if session_repo and hasattr(session_repo, "end"):
            return session_repo.end(run_id)
        # fallback: in-memory
        if isinstance(self.repos.get("session"), _InMemorySessionRepo):
            return self.repos["session"].end(run_id)
        return False

    # -------------------------
    # Convenience helpers
    # -------------------------
    def save(self, game_id: int, state: dict[str, Any]) -> dict[str, Any] | None:
        """Persist arbitrary game state (metadata, world snapshot)."""
        repo = self.repos.get("game")
        if repo and hasattr(repo, "update"):
            return repo.update(game_id, {"state": state})
        # fallback: if in-memory repo exists, update it
        if isinstance(self.repos.get("game"), _InMemoryGameRepo):
            return self.repos["game"].update(game_id, {"state": state})
        return None

    def snapshot(self, game_id: int) -> dict[str, Any] | None:
        """Return a snapshot of the game's persisted state."""
        g = self.get_game(game_id)
        if not g:
            return None
        return g.get("state") if isinstance(g, dict) else None

    # -------------------------
    # Tool integration (optional)
    # -------------------------
    def invoke_tool(self, tool_name: str, args: str, context: dict[str, Any] | None = None) -> Any:
        """
        Convenience wrapper to call the ToolService from game-level logic.
        Returns whatever the tool returns.
        """
        if not self.tool_service:
            raise RuntimeError("ToolService not configured")
        return self.tool_service.invoke(tool_name, args, context or {})


# -------------------------
# Minimal in-memory repos for development and tests
# -------------------------
class _InMemoryGameRepo:
    def __init__(self):
        self._store = {}
        self._next = 1

    def create(self, name: str, metadata: dict[str, Any] | None = None):
        gid = self._next
        self._next += 1
        self._store[gid] = {"id": gid, "name": name, "metadata": metadata or {}, "state": {}}
        return self._store[gid]

    def list(self):
        return list(self._store.values())

    def get(self, gid: int):
        return self._store.get(gid)

    def update(self, gid: int, patch: dict[str, Any]):
        if gid not in self._store:
            return None
        self._store[gid].update(patch)
        return self._store[gid]


class _InMemorySessionRepo:
    def __init__(self):
        self._store = {}
        self._next = 1

    def create_for_game(self, game_id: int, starter: dict[str, Any]):
        rid = self._next
        self._next += 1
        run = {
            "id": rid,
            "game_id": game_id,
            "started_at": time.time(),
            "starter": starter,
            "active": True,
            "entries": [],
        }
        self._store[rid] = run
        return run

    def get_active_for_game(self, game_id: int):
        for run in self._store.values():
            if run["game_id"] == game_id and run.get("active"):
                return run
        return None

    def end(self, run_id: int):
        run = self._store.get(run_id)
        if not run:
            return False
        run["active"] = False
        run["ended_at"] = time.time()
        return True
