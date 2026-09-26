# services/repos.py

from typing import Any, Dict, List, Optional
from datetime import datetime

class InMemorySessionStore:
    """
    Minimal in-memory session store compatible with app.types.SessionStore.
    Stores sessions as dict: {session_id: [message_dict, ...]}
    """

    def __init__(self):
        self._sessions: Dict[str, List[Dict[str, Any]]] = {}

    def get_session(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        return self._sessions.get(session_id)

    def create_session(self, session_id: str) -> None:
        self._sessions[session_id] = []

    def create_message(self, session_id: str, message_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        msg = {
            "id": message_id,
            "client_message_id": payload.get("client_message_id"),
            "role": payload.get("role", "user"),
            "content": payload.get("content"),
            "status": "queued",
            "meta": payload.get("meta") or {},
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        self._sessions[session_id].append(msg)
        return msg

    def get_by_client_id(self, session_id: str, client_message_id: str) -> Optional[Dict[str, Any]]:
        for m in self._sessions.get(session_id, []):
            if m.get("client_message_id") == client_message_id:
                return m
        return None

    def list_messages(self, session_id: str) -> List[Dict[str, Any]]:
        return self._sessions.get(session_id, [])

    def update_message_status(self, session_id: str, message_id: str, status: str) -> None:
        for m in self._sessions.get(session_id, []):
            if m.get("id") == message_id:
                m["status"] = status
                m["updated_at"] = datetime.utcnow()
                return


# ------------------------------------------------------------
# Repo factory functions expected by app/main.py
# ------------------------------------------------------------

DEFAULT_REPOS: Dict[str, Any] = {
    "session": InMemorySessionStore(),
}

def make_default_repos() -> Dict[str, Any]:
    return {
        "session": InMemorySessionStore(),
    }

def seed_sample_data(repos: Dict[str, Any]) -> None:
    """
    Optional: seed a demo session for development.
    """
    store = repos["session"]
    store.create_session("demo")
    store.create_message("demo", "msg-1", {
        "client_message_id": None,
        "role": "user",
        "content": "Hello world!",
        "meta": {},
    })
