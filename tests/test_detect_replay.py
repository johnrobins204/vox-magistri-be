"""SPEC-0019 WP-7: read-only replay of the mention detector over stored canon replies.

Every DB is built in tmp_path. The repo-root dnd.db is never opened: the refusal test spies on
sqlite3.connect and asserts it is not called.
"""

import hashlib
import importlib.util
import sqlite3
from pathlib import Path

from app.services.repos import SqliteSessionStore

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "detect_replay.py"

_spec = importlib.util.spec_from_file_location("detect_replay", SCRIPT)
detect_replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detect_replay)

F1 = (
    "You push open the door of the Rusty Anchor and the noise of the tavern washes over you. "
    'Behind the bar, Old Marta polishes a mug and nods. "Aria, you came back," she says. '
    '"Captain Harl was asking after you."\n'
    "Harl sits in the corner with two sailors from Brightwater. He raises a hand and Marta "
    'whispers, "Careful. The Captain owes money to half of Brightwater." '
    "Veyra's name is not spoken here."
)
ROLL = "Veyra Ashgrove rolls a d20 and gets 14 on Perception."
UNCANON = "Mira Quillon waits by the well and says nothing."


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_store(path: Path) -> None:
    store = SqliteSessionStore(str(path))
    store.create_session("s1", character={"name": "Aria"})
    store.create_entity(name="Brightwater", status="canon")
    store.create_message("s1", "u1", {"role": "user", "content": "I walk in."}, status="completed")
    store.create_message(
        "s1",
        "r1",
        {"role": "assistant", "content": F1, "meta": {"reply_to": "u1"}},
        status="completed",
    )
    store.create_message(
        "s1",
        "r2",
        {"role": "assistant", "content": ROLL, "meta": {"tool": "roll"}},
        status="completed",
    )
    store.create_message(
        "s1",
        "r3",
        {"role": "assistant", "content": UNCANON, "meta": {"reply_to": "u1"}},
        status="completed",
    )
    store.update_message("s1", "r3", canon=False)
    store.close()


def test_replay_prints_candidates_and_counts(tmp_path, capsys):
    path = tmp_path / "game.db"
    _build_store(path)

    rc = detect_replay.main([str(path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert '+ Rusty Anchor [other] "You push open the door of the Rusty Anchor' in out
    assert '+ Old Marta [other] "Behind the bar, Old Marta polishes a mug and nods."' in out
    assert "+ Captain Harl [npc]" in out
    assert "candidates=3" in out
    assert "replies scanned=1 candidates=3 mean=3.00 max=3" in out
    # Only the canon chat reply is scanned: the tool reply and the non-canon reply are absent.
    assert "Veyra Ashgrove" not in out
    assert "Mira Quillon" not in out
    assert "Aria" not in out


def test_replay_is_read_only(tmp_path, capsys):
    path = tmp_path / "game.db"
    _build_store(path)
    before_hash = _sha256(path)
    conn = sqlite3.connect(str(path))
    before_version = conn.execute("PRAGMA user_version").fetchone()[0]
    before_rows = conn.execute("SELECT COUNT(*) FROM world_entities").fetchone()[0]
    conn.close()

    assert detect_replay.main([str(path)]) == 0
    capsys.readouterr()

    assert _sha256(path) == before_hash
    conn = sqlite3.connect(str(path))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == before_version
    assert conn.execute("SELECT COUNT(*) FROM world_entities").fetchone()[0] == before_rows
    assert before_rows == 1
    assert (
        conn.execute("SELECT COUNT(*) FROM world_entities WHERE status = 'pending'").fetchone()[0]
        == 0
    )
    conn.close()


def test_replay_older_schema_and_refusals(tmp_path, capsys, monkeypatch):
    # A v1 DB: no canon column, no world_entities table, no sessions.character column.
    v1 = tmp_path / "v1.db"
    conn = sqlite3.connect(str(v1))
    conn.executescript(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);"
        "CREATE TABLE messages (seq INTEGER PRIMARY KEY, session_id TEXT NOT NULL, "
        "id TEXT NOT NULL, client_message_id TEXT, role TEXT, content TEXT, "
        "status TEXT NOT NULL, meta TEXT NOT NULL, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, UNIQUE(session_id, id));"
        "PRAGMA user_version = 1;"
    )
    conn.execute("INSERT INTO sessions (id, created_at) VALUES ('s1', '2026-01-01T00:00:00')")
    conn.execute(
        "INSERT INTO messages (session_id, id, role, content, status, meta, created_at, "
        "updated_at) VALUES ('s1', 'r1', 'assistant', ?, 'completed', '{}', "
        "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
        (F1,),
    )
    conn.commit()
    conn.close()

    assert detect_replay.main([str(v1)]) == 0
    assert "replies scanned=1" in capsys.readouterr().out

    assert detect_replay.main([str(tmp_path / "missing.db")]) == 2

    opened: list[object] = []
    real_connect = sqlite3.connect

    def spy(*args, **kwargs):
        opened.append(args)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(detect_replay.sqlite3, "connect", spy)
    assert detect_replay.main([str(ROOT / "dnd.db")]) == 2
    assert opened == []
    capsys.readouterr()
