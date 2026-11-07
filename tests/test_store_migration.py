"""SqliteSessionStore migration ladder (SPEC-0013 WP-1; T-01..T-06; PAT-ARCH-008).

Old-version DBs are built with raw sqlite3 in tmp_path. Every store is closed.
"""

import logging
import sqlite3
from contextlib import closing

import pytest

import app.services.repos as repos_module
from app.services.repos import SqliteSessionStore

LOGGER_NAME = "app.services.repos"

# Literal v1 base schema, as shipped before the ladder existed.
V1_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL)",
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
    "UNIQUE(session_id, id))",
    "CREATE INDEX IF NOT EXISTS idx_messages_client ON messages(session_id, client_message_id)",
)


def _make_v1_db(path, extra_statements=()):
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            for stmt in V1_SCHEMA:
                conn.execute(stmt)
            for stmt in extra_statements:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO sessions (id, created_at) "
                "VALUES ('s-old', '2026-01-01T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO messages (session_id, id, client_message_id, role, content, "
                "status, meta, created_at, updated_at) VALUES ('s-old', 'm-old', 'cm-old', "
                "'user', 'hello old', 'done', '{}', '2026-01-01T00:00:01+00:00', "
                "'2026-01-01T00:00:01+00:00')"
            )
        conn.execute("PRAGMA user_version = 1")


def _make_v2_db(path, extra_statements=()):
    _make_v1_db(
        path, extra_statements=("ALTER TABLE sessions ADD COLUMN character TEXT", *extra_statements)
    )
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA user_version = 2")


WORLD_ENTITIES_DDL = (
    "CREATE TABLE IF NOT EXISTS world_entities (id TEXT PRIMARY KEY, session_id TEXT REFERENCES "
    "sessions(id), kind TEXT NOT NULL, name TEXT NOT NULL, aliases TEXT NOT NULL DEFAULT '[]', "
    "notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'canon', created_at TEXT NOT "
    "NULL, updated_at TEXT NOT NULL)"
)


def _raw_version(path):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def _raw_columns(path, table):
    with closing(sqlite3.connect(path)) as conn:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _migrated_records(caplog):
    return [r for r in caplog.records if r.getMessage() == "store.migrated"]


def test_t01_v1_file_db_keeps_rows_and_gains_character_column(tmp_path, caplog):
    path = str(tmp_path / "old.db")
    _make_v1_db(path)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        store = SqliteSessionStore(path)
    try:
        assert [m["id"] for m in store.list_messages("s-old")] == ["m-old"]
    finally:
        store.close()

    assert "character" in _raw_columns(path, "sessions")
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT character FROM sessions WHERE id='s-old'").fetchone() == (None,)
    assert _raw_version(path) == 3

    records = _migrated_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert records[0].__dict__["from"] == 1
    assert records[0].to == 3


def test_t02_reopen_migrated_file_is_a_noop(tmp_path, caplog):
    path = str(tmp_path / "old.db")
    _make_v1_db(path)
    SqliteSessionStore(path).close()

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        store = SqliteSessionStore(path)
    try:
        assert [m["id"] for m in store.list_messages("s-old")] == ["m-old"]
    finally:
        store.close()

    assert _raw_version(path) == 3
    assert _migrated_records(caplog) == []


def test_t03_fresh_file_db_reaches_version_2(tmp_path, caplog):
    path = str(tmp_path / "fresh.db")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        SqliteSessionStore(path).close()

    assert "character" in _raw_columns(path, "sessions")
    assert _raw_version(path) == 3
    records = _migrated_records(caplog)
    assert len(records) == 1
    assert records[0].__dict__["from"] == 0
    assert records[0].to == 3


def test_t04_half_applied_step_is_skipped_without_error(tmp_path):
    path = str(tmp_path / "half.db")
    _make_v1_db(path, extra_statements=("ALTER TABLE sessions ADD COLUMN character TEXT",))

    SqliteSessionStore(path).close()

    assert _raw_version(path) == 3
    assert _raw_columns(path, "sessions").count("character") == 1


def test_t05_failing_step_rolls_back_and_raises(tmp_path, monkeypatch):
    path = str(tmp_path / "broken.db")
    bogus = (4, "sessions", "bogus", "ALTER TABLE no_such_table ADD COLUMN x TEXT")
    monkeypatch.setattr(repos_module, "_MIGRATIONS", [*repos_module._MIGRATIONS, bogus])

    with pytest.raises(sqlite3.OperationalError):
        SqliteSessionStore(path)

    assert _raw_version(path) == 3
    assert "bogus" not in _raw_columns(path, "sessions")

    monkeypatch.undo()
    SqliteSessionStore(path).close()
    assert _raw_version(path) == 3


def test_t06_newer_schema_is_never_lowered(tmp_path, caplog):
    path = str(tmp_path / "newer.db")
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA user_version = 99")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        store = SqliteSessionStore(path)
    store.close()

    assert _raw_version(path) == 99
    warnings = [
        r
        for r in caplog.records
        if r.name == LOGGER_NAME
        and r.levelno == logging.WARNING
        and r.getMessage() == "store.schema_newer_than_code"
    ]
    assert len(warnings) == 1


def _table_exists(path, table):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()


def test_fresh_store_has_world_table():
    store = SqliteSessionStore(":memory:")
    try:
        columns = [row[1] for row in store._conn.execute("PRAGMA table_info(world_entities)")]
        version = store._conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        store.close()

    assert len(columns) == 9
    assert version == 3


@pytest.mark.parametrize("make_db", [_make_v1_db, _make_v2_db], ids=["v1", "v2"])
def test_v1_and_v2_files_upgrade(tmp_path, caplog, make_db):
    path = str(tmp_path / "old.db")
    make_db(path)
    assert not _table_exists(path, "world_entities")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        store = SqliteSessionStore(path)
    try:
        assert [m["id"] for m in store.list_messages("s-old")] == ["m-old"]
    finally:
        store.close()

    assert len(_raw_columns(path, "world_entities")) == 9
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM world_entities").fetchone() == (0,)
    assert _raw_version(path) == 3
    assert len(_migrated_records(caplog)) == 1

    caplog.clear()
    SqliteSessionStore(path).close()
    assert _raw_version(path) == 3
    assert _migrated_records(caplog) == []


def test_table_step_is_idempotent(tmp_path):
    path = str(tmp_path / "half.db")
    _make_v2_db(
        path,
        extra_statements=(
            WORLD_ENTITIES_DDL,
            "INSERT INTO world_entities (id, session_id, kind, name, created_at, updated_at) "
            "VALUES ('e-1', 's-old', 'npc', 'Mira', '2026-01-01T00:00:00+00:00', "
            "'2026-01-01T00:00:00+00:00')",
        ),
    )

    SqliteSessionStore(path).close()

    assert _raw_version(path) == 3
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT id, name FROM world_entities").fetchall() == [("e-1", "Mira")]
