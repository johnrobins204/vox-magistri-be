# services/repos.py

import json
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from app.services.logger import get_logger

logger = get_logger(__name__)

INTERRUPTED_ERROR = "interrupted by server restart"


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _message_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "client_message_id": row["client_message_id"],
        "role": row["role"],
        "content": row["content"],
        "status": row["status"],
        "meta": json.loads(row["meta"]),
        "created_at": _parse_ts(row["created_at"]),
        "updated_at": _parse_ts(row["updated_at"]),
    }


class SqliteSessionStore:
    """
    Durable session store on stdlib sqlite3 (PAT-ARCH-002, ADR-0003).

    One connection (check_same_thread=False) guarded by one lock; every public method
    takes the lock and does not call another public method. Reads return fresh dicts;
    each write is one transaction. Unknown parents or rows raise KeyError.
    """

    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            with self._conn:
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS sessions ("
                    "id TEXT PRIMARY KEY, created_at TEXT NOT NULL)"
                )
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS messages ("
                    "seq INTEGER PRIMARY KEY, "
                    "session_id TEXT NOT NULL REFERENCES sessions(id), "
                    "id TEXT NOT NULL, "
                    "client_message_id TEXT, "
                    "role TEXT, "
                    "content TEXT, "
                    "status TEXT NOT NULL, "
                    "meta TEXT NOT NULL, "
                    "created_at TEXT NOT NULL, "
                    "updated_at TEXT NOT NULL, "
                    "UNIQUE(session_id, id))"
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_messages_client "
                    "ON messages(session_id, client_message_id)"
                )
                self._conn.execute("PRAGMA user_version = 1")
            self._recover_interrupted()

    def _recover_interrupted(self) -> None:
        # Caller holds self._lock. G-4: queued/running messages cannot survive a restart.
        now = _now().isoformat()
        with self._conn:
            rows = self._conn.execute(
                "SELECT seq, meta FROM messages WHERE status IN ('queued', 'running')"
            ).fetchall()
            for row in rows:
                merged = {**json.loads(row["meta"]), "error": INTERRUPTED_ERROR}
                self._conn.execute(
                    "UPDATE messages SET status = 'error', meta = ?, updated_at = ? WHERE seq = ?",
                    (json.dumps(merged), now, row["seq"]),
                )
        if rows:
            logger.warning("store.recovered_interrupted", extra={"count": len(rows)})

    def _messages(self, session_id: str) -> list[dict[str, Any]]:
        # Caller holds self._lock.
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY seq", (session_id,)
        ).fetchall()
        return [_message_from_row(r) for r in rows]

    def get_session(self, session_id: str) -> list[dict[str, Any]] | None:
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if exists is None:
                return None
            return self._messages(session_id)

    def create_session(self, session_id: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                    (session_id, _now().isoformat()),
                )

    def create_message(
        self,
        session_id: str,
        message_id: str,
        payload: dict[str, Any],
        status: str = "queued",
    ) -> dict[str, Any]:
        client_message_id = payload.get("client_message_id")
        role = payload.get("role", "user")
        content = payload.get("content")
        meta_text = json.dumps(payload.get("meta") or {})
        now = _now()
        with self._lock:
            with self._conn:
                exists = self._conn.execute(
                    "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if exists is None:
                    raise KeyError(session_id)
                self._conn.execute(
                    "INSERT INTO messages (session_id, id, client_message_id, role, content, "
                    "status, meta, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        message_id,
                        client_message_id,
                        role,
                        content,
                        status,
                        meta_text,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
        return {
            "id": message_id,
            "client_message_id": client_message_id,
            "role": role,
            "content": content,
            "status": status,
            "meta": json.loads(meta_text),
            "created_at": now,
            "updated_at": now,
        }

    def get_message(self, session_id: str, message_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM messages WHERE session_id = ? AND id = ?",
                (session_id, message_id),
            ).fetchone()
            return None if row is None else _message_from_row(row)

    def get_by_client_id(self, session_id: str, client_message_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM messages WHERE session_id = ? AND client_message_id = ? "
                "ORDER BY seq LIMIT 1",
                (session_id, client_message_id),
            ).fetchone()
            return None if row is None else _message_from_row(row)

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return self._messages(session_id)

    def update_message_status(
        self, session_id: str, message_id: str, status: str, meta: dict[str, Any] | None = None
    ) -> None:
        with self._lock:
            with self._conn:
                row = self._conn.execute(
                    "SELECT meta FROM messages WHERE session_id = ? AND id = ?",
                    (session_id, message_id),
                ).fetchone()
                if row is None:
                    raise KeyError(message_id)
                # Serialize before the UPDATE so a bad meta raises with nothing written.
                merged = {**json.loads(row["meta"]), **(meta or {})}
                meta_text = json.dumps(merged)
                self._conn.execute(
                    "UPDATE messages SET status = ?, meta = ?, updated_at = ? "
                    "WHERE session_id = ? AND id = ?",
                    (status, meta_text, _now().isoformat(), session_id, message_id),
                )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ------------------------------------------------------------
# Repo factory functions expected by app/main.py
# ------------------------------------------------------------


def _sqlite_path(database_url: str) -> str:
    prefix = "sqlite:///"
    path = database_url[len(prefix) :] if database_url.startswith(prefix) else ""
    if not path:
        # Do not echo the URL: it may carry credentials.
        raise ValueError(
            "Unsupported database url; only sqlite:///<path> and sqlite:///:memory: are supported"
        )
    return path


def make_default_repos(database_url: str = "sqlite:///:memory:") -> dict[str, Any]:
    return {"session": SqliteSessionStore(_sqlite_path(database_url))}


def seed_sample_data(repos: dict[str, Any]) -> None:
    """
    Optional: seed a demo session for development.
    """
    store = repos["session"]
    if store.get_session("demo") is not None:
        return
    store.create_session("demo")
    store.create_message(
        "demo",
        "msg-1",
        {
            "client_message_id": None,
            "role": "user",
            "content": "Hello world!",
            "meta": {},
        },
    )
