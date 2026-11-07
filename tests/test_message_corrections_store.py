"""Store write update_message (SPEC-0016 WP-2, REQ-0027; T-10..T-14).

Stores are ":memory:" or a file under tmp_path; every store is closed.
"""

from datetime import datetime

import pytest

from app.services.repos import SqliteSessionStore
from app.type_defs import SessionStore


@pytest.fixture
def store():
    s = SqliteSessionStore(":memory:")
    yield s
    s.close()


@pytest.fixture
def seeded(store):
    store.create_session("s")
    store.create_message(
        "s",
        "m",
        {"role": "assistant", "content": "A", "meta": {"reply_to": "u1"}},
    )
    return store


def test_edit_appends_revision(seeded):
    fresh = seeded.update_message("s", "m", content="B")

    assert fresh["content"] == "B"
    assert fresh["meta"]["reply_to"] == "u1"
    assert len(fresh["meta"]["revisions"]) == 1
    rev = fresh["meta"]["revisions"][0]
    assert rev["content"] == "A"
    assert rev["reason"] == "edit"
    assert isinstance(rev["replaced_at"], str)
    datetime.fromisoformat(rev["replaced_at"])

    second = seeded.update_message("s", "m", content="C")
    revisions = second["meta"]["revisions"]
    assert [r["content"] for r in revisions] == ["A", "B"]

    # Same content again: no revision added.
    same = seeded.update_message("s", "m", content="C")
    assert same["meta"]["revisions"] == revisions
    assert same["content"] == "C"


def test_canon_toggle_only(seeded):
    before = seeded.get_message("s", "m")

    off = seeded.update_message("s", "m", canon=False)

    assert off["canon"] is False
    assert seeded.get_message("s", "m")["canon"] is False
    assert [m["canon"] for m in seeded.list_messages("s")] == [False]
    after = seeded.get_message("s", "m")
    assert after["content"] == before["content"]
    assert after["meta"] == before["meta"]
    assert "revisions" not in after["meta"]

    on = seeded.update_message("s", "m", canon=True)
    assert on["canon"] is True
    assert seeded.get_message("s", "m")["canon"] is True


def test_content_canon_meta_together(seeded):
    fresh = seeded.update_message(
        "s", "m", content="B", canon=False, meta={"tool": "roll"}, reason="regenerate"
    )

    assert fresh["content"] == "B"
    assert fresh["canon"] is False
    assert fresh["meta"]["reply_to"] == "u1"
    assert fresh["meta"]["tool"] == "roll"
    assert fresh["meta"]["revisions"] == [
        {
            "content": "A",
            "replaced_at": fresh["meta"]["revisions"][0]["replaced_at"],
            "reason": "regenerate",
        }
    ]


def test_invalid_calls_write_nothing(seeded):
    before = seeded.get_message("s", "m")

    with pytest.raises(KeyError):
        seeded.update_message("s", "nope", content="x")
    with pytest.raises(KeyError):
        seeded.update_message("unknown", "m", content="x")
    with pytest.raises(ValueError):
        seeded.update_message("s", "m")
    with pytest.raises(ValueError):
        seeded.update_message("s", "m", meta={"revisions": []})
    with pytest.raises(ValueError):
        seeded.update_message("s", "m", content="B", reason="bogus")
    with pytest.raises(TypeError):
        seeded.update_message("s", "m", meta={"bad": object()})

    assert seeded.get_message("s", "m") == before


def test_fresh_dicts_and_persistence(tmp_path):
    path = str(tmp_path / "corrections.db")
    s = SqliteSessionStore(path)
    assert hasattr(SessionStore, "update_message")
    s.create_session("s")
    s.create_message("s", "m", {"role": "assistant", "content": "A", "meta": {}})

    result = s.update_message("s", "m", content="B", canon=False)
    result["meta"]["revisions"].append("junk")
    result["meta"]["extra"] = 1
    result["content"] = "mutated"

    stored = s.get_message("s", "m")
    assert stored["content"] == "B"
    assert stored["meta"]["revisions"][0]["content"] == "A"
    assert stored["meta"]["revisions"][0]["reason"] == "edit"
    assert set(stored["meta"]) == {"revisions"}
    assert stored["canon"] is False
    s.close()

    reopened = SqliteSessionStore(path)
    try:
        again = reopened.get_message("s", "m")
        assert again["content"] == "B"
        assert again["canon"] is False
        assert [r["content"] for r in again["meta"]["revisions"]] == ["A"]
    finally:
        reopened.close()
