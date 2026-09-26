# services/session_service.py
"""
SessionService: manage session runs, entries, and simple conversation history.

Responsibilities:
- Create/get active session runs for a game
- Append entries (chat, narration, actions) to a run
- Query entries, snapshot, and end runs
- Integrate with repos for persistence; provide in-memory fallback for MVP
- Keep methods small and testable; UI calls this service, not repos directly
"""

from __future__ import annotations

import threading
import time
from typing import Any


class SessionService:
    """
    High-level session orchestration used by UI and GameService.

    Constructor:
        SessionService(repos: Optional[Dict[str, object]] = None, tool_service: Optional[object] = None)

    Expected repo methods (if provided):
        session_repo.get_active_for_game(game_id) -> run | None
        session_repo.create_for_game(game_id, starter) -> run
        session_repo.append_entry(run_id, entry) -> entry
        session_repo.list_entries(run_id) -> list[entry]
        session_repo.end(run_id) -> bool
    """

    def __init__(self, repos: dict[str, object] | None = None, tool_service: object | None = None):
        self.repos = repos or {}
        self.tool_service = tool_service
        # simple in-memory store used if no repo provided
        if "session" not in self.repos:
            self._inmem = _InMemorySessionRepo()
            self.repos["session"] = self._inmem
        else:
            self._inmem = None
        # thread lock for concurrency safety in UI threads
        self._lock = threading.RLock()

    # -------------------------
    # Session lifecycle
    # -------------------------
    def ensure_active(self, game_id: int, starter: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Return an active run for the game, creating one if necessary.
        """
        with self._lock:
            repo = self.repos.get("session")
            if repo and hasattr(repo, "get_active_for_game"):
                active = repo.get_active_for_game(game_id)
                if active:
                    return active
            if repo and hasattr(repo, "create_for_game"):
                return repo.create_for_game(game_id, starter or {})
            # fallback to in-memory
            return self._inmem.create_for_game(game_id, starter or {})

    def get_active(self, game_id: int) -> dict[str, Any] | None:
        """Return active run or None."""
        repo = self.repos.get("session")
        if repo and hasattr(repo, "get_active_for_game"):
            return repo.get_active_for_game(game_id)
        return None

    def end_run(self, run_id: int) -> bool:
        """Mark a run as ended."""
        with self._lock:
            repo = self.repos.get("session")
            if repo and hasattr(repo, "end"):
                return repo.end(run_id)
            if self._inmem:
                return self._inmem.end(run_id)
            return False

    # -------------------------
    # Entries and chat
    # -------------------------
    def append_entry(
        self, run_id: int, role: str, text: str, meta: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Append an entry to the session run.

        Entry schema (MVP):
            {
                "id": int,
                "run_id": int,
                "timestamp": float,
                "role": "You"|"Assistant"|"Tool"|"System",
                "text": str,
                "meta": dict
            }
        """
        with self._lock:
            entry = {
                "id": int(time.time() * 1000),
                "run_id": run_id,
                "timestamp": time.time(),
                "role": role,
                "text": text,
                "meta": meta or {},
            }
            repo = self.repos.get("session")
            if repo and hasattr(repo, "append_entry"):
                try:
                    return repo.append_entry(run_id, entry)
                except Exception:
                    # fallback to in-memory append
                    pass
            if self._inmem:
                return self._inmem.append_entry(run_id, entry)
            # last-resort: return entry without persistence
            return entry

    def list_entries(self, run_id: int, limit: int | None = None) -> list[dict[str, Any]]:
        """Return entries for a run, newest-last. Limit optional."""
        repo = self.repos.get("session")
        if repo and hasattr(repo, "list_entries"):
            try:
                entries = repo.list_entries(run_id)
                return entries[-limit:] if limit else entries
            except Exception:
                pass
        if self._inmem:
            entries = self._inmem.list_entries(run_id)
            return entries[-limit:] if limit else entries
        return []

    # -------------------------
    # Convenience helpers
    # -------------------------
    def append_user_message(self, game_id: int, text: str) -> dict[str, Any]:
        """Ensure active run and append a user message."""
        run = self.ensure_active(game_id)
        return self.append_entry(run["id"], "You", text)

    def append_assistant_message(
        self, game_id: int, text: str, meta: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        run = self.ensure_active(game_id)
        return self.append_entry(run["id"], "Assistant", text, meta)

    def invoke_tool_and_record(self, game_id: int, tool_name: str, args: str) -> dict[str, Any]:
        """
        Invoke a tool via ToolService (if configured), record the tool call and response as entries,
        and return the tool response (as a dict with 'text' and optional metadata).
        """
        run = self.ensure_active(game_id)
        run_id = run["id"]
        # record invocation
        self.append_entry(run_id, "You", f"/{tool_name} {args}", {"tool_call": True})
        if not self.tool_service or not hasattr(self.tool_service, "invoke"):
            resp_text = f"(no tool service configured) /{tool_name}"
            self.append_entry(run_id, "System", resp_text)
            return {"text": resp_text}
        try:
            resp = self.tool_service.invoke(tool_name, args)
            # normalize response
            if isinstance(resp, tuple) and len(resp) >= 1:
                resp_text = str(resp[0])
            else:
                resp_text = str(resp)
            self.append_entry(run_id, "Tool", resp_text)
            return {"text": resp_text}
        except Exception as e:
            err = f"Tool error: {e}"
            self.append_entry(run_id, "System", err)
            return {"text": err}

    # -------------------------
    # Snapshots and export
    # -------------------------
    def snapshot_run(self, run_id: int) -> dict[str, Any]:
        """Return a snapshot object for the run (entries + metadata)."""
        entries = self.list_entries(run_id)
        return {"run_id": run_id, "entries": entries, "snapshot_at": time.time()}


# -------------------------
# Minimal in-memory session repo used by SessionService when no repo provided
# -------------------------
class _InMemorySessionRepo:
    def __init__(self):
        self._runs: dict[int, dict[str, Any]] = {}
        self._entries: dict[int, list[dict[str, Any]]] = {}
        self._next_run = 1
        self._lock = threading.RLock()

    def create_for_game(self, game_id: int, starter: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            rid = self._next_run
            self._next_run += 1
            run = {
                "id": rid,
                "game_id": game_id,
                "started_at": time.time(),
                "starter": starter,
                "active": True,
            }
            self._runs[rid] = run
            self._entries[rid] = []
            return run

    def get_active_for_game(self, game_id: int) -> dict[str, Any] | None:
        with self._lock:
            for run in self._runs.values():
                if run["game_id"] == game_id and run.get("active"):
                    return run
            return None

    def append_entry(self, run_id: int, entry: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if run_id not in self._entries:
                self._entries[run_id] = []
            self._entries[run_id].append(entry)
            return entry

    def list_entries(self, run_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries.get(run_id, []))

    def end(self, run_id: int) -> bool:
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return False
            run["active"] = False
            run["ended_at"] = time.time()
            return True
