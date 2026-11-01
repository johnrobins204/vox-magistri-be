"""Session character storage on the store (SPEC-0013 WP-2, ADR-0008 D5)."""

import inspect
import sqlite3

import pytest

from app.services.repos import SqliteSessionStore
from app.type_defs import SessionStore

ARIA = {
    "id": "hero-1",
    "name": "Aria",
    "lineage": "Wood Elf",
    "species_id": "elf",
    "char_class": "Ranger",
    "level": 3,
    "hp_current": 24,
    "hp_max": 28,
    "ac": 14,
    "abilities": {"STR": 12, "DEX": 16, "CON": 13, "INT": 11, "WIS": 15, "CHA": 10},
    "conditions": ["Blessed"],
}

V1_DDL = [
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
]


def _make_v1_db(path) -> None:
    conn = sqlite3.connect(str(path))
    with conn:
        for ddl in V1_DDL:
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO sessions (id, created_at) VALUES ('s-old', '2026-01-01T00:00:00')"
        )
        conn.execute("PRAGMA user_version = 1")
    conn.close()


def test_create_and_get_character_round_trip():
    store = SqliteSessionStore(":memory:")
    store.create_session("s", character=ARIA)
    assert store.get_character("s") == ARIA


def test_get_character_returns_fresh_dict():
    store = SqliteSessionStore(":memory:")
    store.create_session("s", character=ARIA)
    first = store.get_character("s")
    first["name"] = "Mutated"
    first["abilities"]["STR"] = 1
    assert store.get_character("s") == ARIA


def test_session_without_character_reads_none():
    store = SqliteSessionStore(":memory:")
    store.create_session("s")
    assert store.get_character("s") is None
    assert store.get_session("s") == []


def test_get_character_unknown_session_raises_key_error():
    store = SqliteSessionStore(":memory:")
    with pytest.raises(KeyError):
        store.get_character("nope")


def test_character_survives_reopen(tmp_path):
    path = tmp_path / "char.db"
    store = SqliteSessionStore(str(path))
    store.create_session("s", character=ARIA)
    store.close()

    reopened = SqliteSessionStore(str(path))
    try:
        assert reopened.get_character("s") == ARIA
    finally:
        reopened.close()


def test_migrated_old_session_reads_none(tmp_path):
    path = tmp_path / "old.db"
    _make_v1_db(path)

    store = SqliteSessionStore(str(path))
    try:
        assert store.get_character("s-old") is None
    finally:
        store.close()


def test_character_is_immutable_for_session():
    store = SqliteSessionStore(":memory:")
    store.create_session("s", character=ARIA)
    assert not hasattr(store, "set_character")
    assert not hasattr(store, "update_character")

    with pytest.raises(sqlite3.IntegrityError):
        store.create_session("s", character={**ARIA, "name": "Other"})
    assert store.get_character("s") == ARIA


def test_signatures_match_spec():
    for owner in (SessionStore, SqliteSessionStore):
        sig = inspect.signature(owner.create_session)
        assert list(sig.parameters) == ["self", "session_id", "character"]
        assert sig.parameters["character"].default is None

        sig = inspect.signature(owner.get_character)
        assert list(sig.parameters) == ["self", "session_id"]
