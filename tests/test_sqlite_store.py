"""SqliteSessionStore contract (SPEC-0005 WP-2; T-01..T-12, T-13/T-14 in WP-3).

Stores are ":memory:" or a file under tmp_path; every store is closed.
"""

import logging
import sqlite3
import threading
from datetime import datetime

import pytest

from app.services.repos import SqliteSessionStore

MESSAGE_KEYS = {
    "id",
    "client_message_id",
    "role",
    "content",
    "status",
    "meta",
    "created_at",
    "updated_at",
}


@pytest.fixture
def store():
    s = SqliteSessionStore(":memory:")
    yield s
    s.close()


def _ids(messages):
    return [m["id"] for m in messages]


def test_empty_and_unknown_sessions(store):
    assert store.get_session("x") is None
    assert store.list_messages("x") == []

    store.create_session("x")

    assert store.get_session("x") == []
    assert store.list_messages("x") == []


def test_create_message_and_reads(store):
    store.create_session("s")
    created = store.create_message(
        "s",
        "m1",
        {"client_message_id": "c1", "role": "user", "content": "hi", "meta": {"k": 1}},
    )

    assert set(created) == MESSAGE_KEYS
    assert created["id"] == "m1"
    assert created["client_message_id"] == "c1"
    assert created["role"] == "user"
    assert created["content"] == "hi"
    assert created["status"] == "queued"
    assert created["meta"] == {"k": 1}
    assert isinstance(created["created_at"], datetime)
    assert isinstance(created["updated_at"], datetime)

    assert store.list_messages("s") == [created]
    assert store.get_session("s") == [created]


def test_create_message_defaults(store):
    store.create_session("s")

    empty = store.create_message("s", "m-empty", {})
    assert empty["role"] == "user"
    assert empty["content"] is None
    assert empty["client_message_id"] is None
    assert empty["meta"] == {}

    none_meta = store.create_message("s", "m-none", {"meta": None})
    assert none_meta["meta"] == {}


def test_reads_return_fresh_dicts(store):
    store.create_session("s")
    created = store.create_message("s", "m1", {"content": "hi", "meta": {"k": 1}})

    from_session = store.get_session("s")
    from_session[0]["content"] = "changed"
    from_session[0]["meta"]["k"] = 99

    from_list = store.list_messages("s")
    from_list[0]["meta"]["k"] = 42
    from_list.append({"id": "ghost"})

    created["content"] = "changed too"
    created["meta"]["k"] = 7

    later = store.list_messages("s")
    assert _ids(later) == ["m1"]
    assert later[0]["content"] == "hi"
    assert later[0]["meta"] == {"k": 1}
    assert later is not store.list_messages("s")


def test_get_by_client_id(store):
    store.create_session("s")
    m1 = store.create_message("s", "m1", {"client_message_id": "c1", "content": "a"})
    store.create_message("s", "m2", {"content": "no client id"})

    assert store.get_by_client_id("s", "c1") == m1
    assert store.get_by_client_id("s", "unknown") is None
    assert store.get_by_client_id("nope", "c1") is None
    assert store.get_by_client_id("s", None) is None


def test_unknown_writes_raise_keyerror(store):
    with pytest.raises(KeyError):
        store.create_message("nope", "m1", {"content": "x"})
    with pytest.raises(KeyError):
        store.update_message_status("nope", "m1", "error")

    store.create_session("s")
    store.create_message("s", "m1", {"content": "x"})
    with pytest.raises(KeyError):
        store.update_message_status("s", "missing", "error")

    assert store.get_session("nope") is None
    msgs = store.get_session("s")
    assert _ids(msgs) == ["m1"]
    assert msgs[0]["status"] == "queued"
    assert msgs[0]["meta"] == {}


def test_duplicate_session_and_message_ids_raise_integrityerror(store):
    store.create_session("s")
    store.create_message("s", "m1", {"content": "first"})

    with pytest.raises(sqlite3.IntegrityError):
        store.create_session("s")
    msgs = store.list_messages("s")
    assert _ids(msgs) == ["m1"]
    assert msgs[0]["content"] == "first"

    with pytest.raises(sqlite3.IntegrityError):
        store.create_message("s", "m1", {"content": "second"})
    assert _ids(store.list_messages("s")) == ["m1"]


def test_update_message_status_merges_meta_and_bumps_updated_at(store):
    store.create_session("s")
    created = store.create_message("s", "m1", {"content": "x", "meta": {"a": 1}})

    store.update_message_status("s", "m1", "running")
    msg = store.list_messages("s")[0]
    assert msg["status"] == "running"
    assert msg["meta"] == {"a": 1}
    assert msg["updated_at"] >= created["updated_at"]
    assert msg["created_at"] == created["created_at"]

    store.update_message_status("s", "m1", "error", meta={"error": "boom", "a": 2})
    msg = store.list_messages("s")[0]
    assert msg["status"] == "error"
    assert msg["meta"] == {"a": 2, "error": "boom"}
    assert msg["created_at"] == created["created_at"]

    store.update_message_status("s", "m1", "cancelled", meta=None)
    assert store.list_messages("s")[0]["meta"] == {"a": 2, "error": "boom"}


def test_update_status_and_meta_are_atomic(store):
    store.create_session("s")
    store.create_message("s", "m1", {"content": "x", "meta": {"a": 1}})

    with pytest.raises(TypeError):
        store.update_message_status("s", "m1", "error", meta={"bad": object()})
    msg = store.list_messages("s")[0]
    assert msg["status"] == "queued"
    assert msg["meta"] == {"a": 1}

    store.update_message_status("s", "m1", "error", meta={"error": "boom"})
    msg = store.list_messages("s")[0]
    assert msg["status"] == "error"
    assert msg["meta"]["error"] == "boom"


def test_datetimes_and_meta_round_trip(tmp_path):
    path = str(tmp_path / "t.db")
    store = SqliteSessionStore(path)
    try:
        store.create_session("s")
        store.create_message(
            "s",
            "m1",
            {"content": "x", "meta": {"a": [1, 2, {"b": None}], "s": "é", "f": 1.5, "t": True}},
        )
        # WP-3 (G-4): a queued message would be recovered to error on reopen, so move it
        # to a terminal status first; capture after that update.
        store.update_message_status("s", "m1", "completed")
        captured = store.list_messages("s")[0]
    finally:
        store.close()

    reopened = SqliteSessionStore(path)
    try:
        msgs = reopened.get_session("s")
    finally:
        reopened.close()

    assert msgs == [captured]
    assert msgs[0]["created_at"] == captured["created_at"]
    assert msgs[0]["updated_at"] == captured["updated_at"]
    assert msgs[0]["meta"] == {"a": [1, 2, {"b": None}], "s": "é", "f": 1.5, "t": True}


def test_restart_round_trip_file(tmp_path):
    path = str(tmp_path / "r.db")
    store = SqliteSessionStore(path)
    try:
        store.create_session("s")
        u1 = store.create_message("s", "u1", {"client_message_id": "c1", "content": "hello"})
        store.create_message("s", "a1", {"role": "assistant", "meta": {"reply_to": "u1"}})
        store.update_message_status("s", "u1", "completed", meta={"updated_by": "inference_worker"})
        # WP-3 (G-4): a queued a1 would be recovered to error on reopen; complete it first.
        store.update_message_status("s", "a1", "completed")
        store.create_session("e")
        before = store.get_session("s")
    finally:
        store.close()
    assert u1["id"] == "u1"

    reopened = SqliteSessionStore(path)
    try:
        msgs = reopened.get_session("s")
        assert msgs == before
        assert _ids(msgs) == ["u1", "a1"]
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[0]["content"] == "hello"
        assert msgs[0]["status"] == "completed"
        assert msgs[0]["meta"] == {"updated_by": "inference_worker"}
        assert msgs[1]["meta"] == {"reply_to": "u1"}
        assert reopened.get_session("e") == []
        assert reopened.get_session("nope") is None
        assert reopened.get_by_client_id("s", "c1")["id"] == "u1"

        reopened.create_message("s", "m3", {"content": "later"})
        assert _ids(reopened.get_session("s")) == ["u1", "a1", "m3"]
    finally:
        reopened.close()


def test_schema_created_on_open(tmp_path):
    path = str(tmp_path / "schema.db")
    store = SqliteSessionStore(path)
    store.create_session("s")
    store.create_message("s", "m1", {"content": "kept"})
    store.close()

    raw = sqlite3.connect(path)
    try:
        tables = {
            row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        version = raw.execute("PRAGMA user_version").fetchone()[0]
    finally:
        raw.close()
    assert {"sessions", "messages"} <= tables
    assert version == 1

    reopened = SqliteSessionStore(path)
    try:
        assert _ids(reopened.list_messages("s")) == ["m1"]
    finally:
        reopened.close()


def test_store_is_usable_across_threads(store):
    errors: list[BaseException] = []

    def first_session():
        try:
            store.create_session("s0")
            store.create_message("s0", "m0", {"content": "from thread"})
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=first_session)
    t.start()
    t.join(timeout=10)
    assert not t.is_alive()
    assert errors == []
    assert _ids(store.list_messages("s0")) == ["m0"]

    store.create_session("bulk")

    def writer(i: int):
        try:
            for j in range(10):
                store.create_message("bulk", f"t{i}-{j}", {"content": f"{i}/{j}"})
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)
    assert not any(th.is_alive() for th in threads)
    assert errors == []

    msgs = store.list_messages("bulk")
    assert len(msgs) == 80
    assert len(set(_ids(msgs))) == 80


INTERRUPTED = "interrupted by server restart"


def test_restart_marks_interrupted_messages_as_error(tmp_path):
    path = str(tmp_path / "interrupted.db")
    store = SqliteSessionStore(path)
    try:
        store.create_session("s")
        store.create_message(
            "s", "q1", {"client_message_id": "cq", "content": "a", "meta": {"x": 1}}
        )
        store.create_message("s", "r1", {"content": "b"})
        store.update_message_status("s", "r1", "running")
        store.create_message("s", "c1", {"role": "assistant", "content": "c"})
        store.update_message_status("s", "c1", "completed")
        store.create_message(
            "s", "e1", {"role": "assistant", "content": "d", "meta": {"error": "old"}}
        )
        store.update_message_status("s", "e1", "error")
        store.create_message("s", "x1", {"content": "e"})
        store.update_message_status("s", "x1", "cancelled")
        before = store.list_messages("s")
    finally:
        store.close()
    before_by_id = {m["id"]: m for m in before}

    reopened = SqliteSessionStore(path)
    try:
        after = reopened.list_messages("s")
    finally:
        reopened.close()
    after_by_id = {m["id"]: m for m in after}

    assert _ids(after) == ["q1", "r1", "c1", "e1", "x1"]
    assert [m["content"] for m in after] == [m["content"] for m in before]
    assert [m["role"] for m in after] == [m["role"] for m in before]

    assert after_by_id["q1"]["status"] == "error"
    assert after_by_id["q1"]["meta"] == {"x": 1, "error": INTERRUPTED}
    assert after_by_id["q1"]["updated_at"] > before_by_id["q1"]["updated_at"]
    assert after_by_id["r1"]["status"] == "error"
    assert after_by_id["r1"]["meta"] == {"error": INTERRUPTED}
    assert after_by_id["r1"]["updated_at"] > before_by_id["r1"]["updated_at"]

    for mid in ("c1", "e1", "x1"):
        assert after_by_id[mid] == before_by_id[mid]


def test_restart_recovery_is_idempotent_and_memory_safe(tmp_path):
    path = str(tmp_path / "idem.db")
    store = SqliteSessionStore(path)
    try:
        store.create_session("s")
        store.create_message("s", "m1", {"content": "pending"})
        store.update_message_status("s", "m1", "running")
    finally:
        store.close()

    first = SqliteSessionStore(path)
    try:
        after_first = first.list_messages("s")
    finally:
        first.close()
    assert after_first[0]["status"] == "error"
    assert after_first[0]["meta"]["error"] == INTERRUPTED

    second = SqliteSessionStore(path)
    try:
        assert second.list_messages("s") == after_first
    finally:
        second.close()

    memory = SqliteSessionStore(":memory:")
    memory.close()

    empty_path = str(tmp_path / "empty.db")
    SqliteSessionStore(empty_path).close()
    reopened_empty = SqliteSessionStore(empty_path)
    try:
        assert reopened_empty.get_session("s") is None
    finally:
        reopened_empty.close()


def test_recovery_logs_only_when_rows_change(tmp_path, caplog):
    path = str(tmp_path / "log.db")
    store = SqliteSessionStore(path)
    store.create_session("s")
    store.create_message("s", "m1", {"content": "secret text"})
    store.update_message_status("s", "m1", "running")
    store.close()

    with caplog.at_level(logging.WARNING, logger="app.services.repos"):
        first = SqliteSessionStore(path)
        first.close()
        second = SqliteSessionStore(path)
        second.close()

    records = [r for r in caplog.records if r.getMessage() == "store.recovered_interrupted"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].count == 1
    assert "secret text" not in caplog.text
    assert "m1" not in caplog.text
