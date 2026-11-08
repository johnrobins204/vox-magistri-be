"""SqliteSessionStore world entity CRUD (SPEC-0015 WP-3; T-10, T-11, T-13..T-16).

Stores are ":memory:" or a file under tmp_path; every store is closed.
"""

import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest

from app.services.repos import SqliteSessionStore, make_default_repos

ENTITY_KEYS = {
    "id",
    "session_id",
    "kind",
    "name",
    "aliases",
    "notes",
    "status",
    "evidence",
    "created_at",
    "updated_at",
}


@pytest.fixture
def store():
    s = SqliteSessionStore(":memory:")
    yield s
    s.close()


def test_create_get_roundtrip(store):
    created = store.create_entity(name="Aldric")

    assert set(created) == ENTITY_KEYS
    assert isinstance(created["id"], str) and created["id"]
    assert created["kind"] == "other"
    assert created["aliases"] == []
    assert created["notes"] == ""
    assert created["status"] == "canon"
    assert created["session_id"] is None
    for key in ("created_at", "updated_at"):
        assert created[key].utcoffset() == timedelta(0)
        assert created[key].tzinfo is not None
    assert store.get_entity(created["id"]) == created

    created["name"] = "Mutated"
    created["aliases"].append("x")
    fresh = store.get_entity(created["id"])
    assert fresh["name"] == "Aldric"
    assert fresh["aliases"] == []


def test_unknown_ids_raise(store):
    with pytest.raises(KeyError):
        store.create_entity(name="Ghost", session_id="nope")
    assert store.list_entities() == []

    with pytest.raises(KeyError):
        store.get_entity("missing")
    with pytest.raises(KeyError):
        store.update_entity("missing", {"name": "x"})
    with pytest.raises(KeyError):
        store.delete_entity("missing")


def test_update_partial(store):
    created = store.create_entity(name="Aldric", aliases=["Al"], notes="n")

    updated = store.update_entity(created["id"], {"status": "pending"})

    assert updated["status"] == "pending"
    assert updated["name"] == created["name"]
    assert updated["kind"] == created["kind"]
    assert updated["aliases"] == ["Al"]
    assert updated["notes"] == "n"
    assert updated["session_id"] is None
    assert updated["created_at"] == created["created_at"]
    assert updated["updated_at"] >= created["updated_at"]
    assert store.get_entity(created["id"]) == updated

    store.update_entity(created["id"], {"aliases": ["Al", "The Bold"]})
    assert store.get_entity(created["id"])["aliases"] == ["Al", "The Bold"]


@pytest.mark.parametrize("key", ["id", "session_id", "created_at", "bogus"])
def test_update_rejects_non_editable_keys(store, key):
    created = store.create_entity(name="Aldric")

    with pytest.raises(ValueError):
        store.update_entity(created["id"], {"name": "Changed", key: "x"})

    assert store.get_entity(created["id"]) == created


def test_list_scope_and_filters(store):
    store.create_session("s1")
    store.create_session("s2")
    global_row = store.create_entity(name="Global", kind="place")
    s1_row = store.create_entity(name="One", session_id="s1", status="pending")
    s2_row = store.create_entity(name="Two", session_id="s2")

    assert {e["id"] for e in store.list_entities()} == {
        global_row["id"],
        s1_row["id"],
        s2_row["id"],
    }
    assert {e["id"] for e in store.list_entities("s1")} == {global_row["id"], s1_row["id"]}
    assert {e["id"] for e in store.list_entities("s2")} == {global_row["id"], s2_row["id"]}

    assert [e["id"] for e in store.list_entities("s1", status="pending")] == [s1_row["id"]]
    assert [e["id"] for e in store.list_entities(kind="place")] == [global_row["id"]]
    assert store.list_entities("s1", kind="npc") == []


def test_list_order_updated_desc_then_id_asc(store):
    a = store.create_entity(name="A")
    b = store.create_entity(name="B")
    c = store.create_entity(name="C")
    store.update_entity(a["id"], {"notes": "touched"})
    ordered = store.list_entities()

    assert ordered[0]["id"] == a["id"]
    assert {e["id"] for e in ordered} == {a["id"], b["id"], c["id"]}
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        assert earlier["updated_at"] >= later["updated_at"]
        if earlier["updated_at"] == later["updated_at"]:
            assert earlier["id"] < later["id"]


def test_entity_evidence_round_trip(tmp_path):
    path = str(tmp_path / "evidence.db")
    evidence = {"source": "reply", "message_id": "m1", "snippet": "Rusty Anchor"}
    first = SqliteSessionStore(path)
    try:
        created = first.create_entity(name="Rusty Anchor", evidence=evidence)
        plain = first.create_entity(name="Plain")
        assert created["evidence"] == evidence
        assert plain["evidence"] is None
        assert first.get_entity(created["id"]) == created

        updated = first.update_entity(created["id"], {"evidence": {"source": "edit"}})
        assert updated["evidence"] == {"source": "edit"}
        assert updated["updated_at"] > created["updated_at"]
        assert first.get_entity(created["id"])["evidence"] == {"source": "edit"}

        first.update_entity(created["id"], {"evidence": evidence})
    finally:
        first.close()

    second = SqliteSessionStore(path)
    try:
        assert second.get_entity(created["id"])["evidence"] == evidence
        assert second.get_entity(plain["id"])["evidence"] is None
        second.update_entity(created["id"], {"evidence": None})
        assert second.get_entity(created["id"])["evidence"] is None
    finally:
        second.close()

    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute(
            "SELECT evidence FROM world_entities WHERE id = ?", (created["id"],)
        ).fetchone() == (None,)


def test_delete_and_persistence(tmp_path):
    path = str(tmp_path / "world.db")
    first = SqliteSessionStore(path)
    try:
        keep = first.create_entity(name="Keep")
        gone = first.create_entity(name="Gone")
        first.delete_entity(gone["id"])
    finally:
        first.close()

    second = SqliteSessionStore(path)
    try:
        assert second.get_entity(keep["id"])["name"] == "Keep"
        with pytest.raises(KeyError):
            second.get_entity(gone["id"])
        assert [e["id"] for e in second.list_entities()] == [keep["id"]]
    finally:
        second.close()


def test_repos_expose_world():
    repos = make_default_repos()
    try:
        assert repos["world"] is repos["session"]
        assert isinstance(repos["world"], SqliteSessionStore)
    finally:
        repos["session"].close()
