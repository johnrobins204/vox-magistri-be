# services/repos.py

import json
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.services.logger import get_logger

logger = get_logger(__name__)

INTERRUPTED_ERROR = "interrupted by server restart"
_REVISION_REASONS = frozenset({"edit", "regenerate"})

# Append-only (PAT-ARCH-008): (version, table, column, ddl). Never edit an entry.
# column None = CREATE TABLE IF NOT EXISTS step, guarded by sqlite_master (ADR-0010).
_MIGRATIONS: list[tuple[int, str, str | None, str]] = [
    (2, "sessions", "character", "ALTER TABLE sessions ADD COLUMN character TEXT"),
    (
        3,
        "world_entities",
        None,
        "CREATE TABLE IF NOT EXISTS world_entities (id TEXT PRIMARY KEY, "
        "session_id TEXT REFERENCES sessions(id), kind TEXT NOT NULL, name TEXT NOT NULL, "
        "aliases TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '', "
        "status TEXT NOT NULL DEFAULT 'canon', created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)",
    ),
    (4, "messages", "canon", "ALTER TABLE messages ADD COLUMN canon INTEGER DEFAULT 1"),
]


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
        "canon": row["canon"] is None or bool(row["canon"]),
    }


def _entity_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "kind": row["kind"],
        "name": row["name"],
        "aliases": json.loads(row["aliases"]),
        "notes": row["notes"],
        "status": row["status"],
        "created_at": _parse_ts(row["created_at"]),
        "updated_at": _parse_ts(row["updated_at"]),
    }


# Operator-editable fields of a world entity (SPEC-0015). id/session_id/timestamps are not.
_ENTITY_EDITABLE = frozenset({"name", "kind", "aliases", "notes", "status"})


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
            self._migrate()
            self._recover_interrupted()

    def _migrate(self) -> None:
        # Caller holds self._lock. Each step is one explicit transaction (PAT-ARCH-008).
        start = self._conn.execute("PRAGMA user_version").fetchone()[0]
        newest = _MIGRATIONS[-1][0]
        if start > newest:
            logger.warning("store.schema_newer_than_code", extra={"version": start})
            return
        if start < 1:
            with self._conn:
                self._conn.execute("PRAGMA user_version = 1")
        current = max(start, 1)
        for version, table, column, ddl in _MIGRATIONS:
            if version <= current:
                continue
            try:
                self._conn.execute("BEGIN")
                if column is None:
                    exists = self._conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
                    ).fetchone()
                    if exists is None:
                        self._conn.execute(ddl)
                else:
                    columns = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
                    if column not in columns:
                        self._conn.execute(ddl)
                self._conn.execute(f"PRAGMA user_version = {int(version)}")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                logger.exception("store.migration_failed", extra={"version": version})
                self._conn.close()
                raise
        final = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if final != start:
            logger.info("store.migrated", extra={"from": start, "to": final})

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

    def create_session(self, session_id: str, character: dict[str, Any] | None = None) -> None:
        character_text = None if character is None else json.dumps(character)
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO sessions (id, created_at, character) VALUES (?, ?, ?)",
                    (session_id, _now().isoformat(), character_text),
                )

    def get_character(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT character FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError(session_id)
            return None if row[0] is None else json.loads(row[0])

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
            "canon": True,
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

    def update_message(
        self,
        session_id: str,
        message_id: str,
        *,
        content: str | None = None,
        canon: bool | None = None,
        meta: dict[str, Any] | None = None,
        reason: str = "edit",
    ) -> dict[str, Any]:
        # PAT-ARCH-010: content changes append to meta.revisions; nothing is deleted.
        if content is None and canon is None and meta is None:
            raise ValueError("nothing to change")
        if reason not in _REVISION_REASONS:
            raise ValueError(f"invalid revision reason: {reason!r}")
        if meta is not None and "revisions" in meta:
            raise ValueError("meta key 'revisions' is reserved")
        with self._lock:
            with self._conn:
                row = self._conn.execute(
                    "SELECT * FROM messages WHERE session_id = ? AND id = ?",
                    (session_id, message_id),
                ).fetchone()
                if row is None:
                    raise KeyError(message_id)
                merged = {**json.loads(row["meta"]), **(meta or {})}
                now = _now().isoformat()
                new_content = row["content"]
                if content is not None and content != row["content"]:
                    revisions = list(merged.get("revisions", []))
                    revisions.append(
                        {"content": row["content"], "replaced_at": now, "reason": reason}
                    )
                    merged["revisions"] = revisions
                    new_content = content
                # Serialize before the UPDATE so a bad meta raises with nothing written.
                meta_text = json.dumps(merged)
                new_canon = row["canon"] if canon is None else int(canon)
                self._conn.execute(
                    "UPDATE messages SET content = ?, canon = ?, meta = ?, updated_at = ? "
                    "WHERE session_id = ? AND id = ?",
                    (new_content, new_canon, meta_text, now, session_id, message_id),
                )
                updated = self._conn.execute(
                    "SELECT * FROM messages WHERE session_id = ? AND id = ?",
                    (session_id, message_id),
                ).fetchone()
                return _message_from_row(updated)

    def create_entity(
        self,
        *,
        name: str,
        kind: str = "other",
        aliases: list[str] | None = None,
        notes: str = "",
        status: str = "canon",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        entity_id = str(uuid4())
        aliases_text = json.dumps(aliases or [])
        now = _now()
        with self._lock:
            with self._conn:
                if session_id is not None:
                    exists = self._conn.execute(
                        "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
                    ).fetchone()
                    if exists is None:
                        raise KeyError(session_id)
                self._conn.execute(
                    "INSERT INTO world_entities (id, session_id, kind, name, aliases, notes, "
                    "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entity_id,
                        session_id,
                        str(kind),
                        name,
                        aliases_text,
                        notes,
                        str(status),
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
        return {
            "id": entity_id,
            "session_id": session_id,
            "kind": str(kind),
            "name": name,
            "aliases": json.loads(aliases_text),
            "notes": notes,
            "status": str(status),
            "created_at": now,
            "updated_at": now,
        }

    def get_entity(self, entity_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM world_entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if row is None:
                raise KeyError(entity_id)
            return _entity_from_row(row)

    def list_entities(
        self,
        session_id: str | None = None,
        *,
        status: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            # Global (NULL-scope) entities are visible in every session.
            clauses.append("(session_id IS NULL OR session_id = ?)")
            params.append(session_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM world_entities{where} ORDER BY updated_at DESC, id ASC",
                params,
            ).fetchall()
            return [_entity_from_row(r) for r in rows]

    def update_entity(self, entity_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        unknown = set(changes) - _ENTITY_EDITABLE
        if unknown:
            raise ValueError(f"world entity fields not editable: {sorted(unknown)}")
        values: dict[str, Any] = dict(changes)
        if "aliases" in values:
            values["aliases"] = json.dumps(values["aliases"] or [])
        if "kind" in values:
            values["kind"] = str(values["kind"])
        if "status" in values:
            values["status"] = str(values["status"])
        values["updated_at"] = _now().isoformat()
        assignments = ", ".join(f"{column} = ?" for column in values)
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    f"UPDATE world_entities SET {assignments} WHERE id = ?",
                    [*values.values(), entity_id],
                )
                if cursor.rowcount == 0:
                    raise KeyError(entity_id)
                row = self._conn.execute(
                    "SELECT * FROM world_entities WHERE id = ?", (entity_id,)
                ).fetchone()
            return _entity_from_row(row)

    def delete_entity(self, entity_id: str) -> None:
        with self._lock:
            with self._conn:
                cursor = self._conn.execute("DELETE FROM world_entities WHERE id = ?", (entity_id,))
                if cursor.rowcount == 0:
                    raise KeyError(entity_id)

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
    store = SqliteSessionStore(_sqlite_path(database_url))
    return {"session": store, "world": store}


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
