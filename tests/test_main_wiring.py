"""app/main.py honours database.url and fails loudly on unsupported URLs (SPEC-0005 WP-5).

Tests call main() directly: logging is a no-op, uvicorn is never started and every store
lives under pytest's tmp_path.
"""

import types

import pytest

from app import main as main_module
from app.services.repos import SqliteSessionStore


def _settings(url: str):
    return types.SimpleNamespace(database=types.SimpleNamespace(url=url))


@pytest.fixture
def no_logs_no_server(monkeypatch):
    monkeypatch.setattr(main_module, "init_logging", lambda **kwargs: None)

    async def _fake_uvicorn(app, host, port, reload=False):
        return None

    monkeypatch.setattr(main_module, "_run_uvicorn", _fake_uvicorn)
    return monkeypatch


def test_main_honours_database_url_and_seed_persists(tmp_path, no_logs_no_server):
    db = tmp_path / "m.db"
    no_logs_no_server.setattr(
        main_module, "get_settings", lambda: _settings(f"sqlite:///{tmp_path}/m.db")
    )
    assert not db.exists()

    assert main_module.main(["--no-tools", "--seed"]) == 0
    assert db.exists()

    store = SqliteSessionStore(str(db))
    try:
        assert len(store.list_messages("demo")) == 1
    finally:
        store.close()

    # A restart with --seed against the same file must not collide or duplicate the demo.
    assert main_module.main(["--no-tools", "--seed"]) == 0

    store = SqliteSessionStore(str(db))
    try:
        messages = store.list_messages("demo")
        assert len(messages) == 1
        assert messages[0]["id"] == "msg-1"
    finally:
        store.close()


def test_main_rejects_non_sqlite_url(no_logs_no_server):
    no_logs_no_server.setattr(main_module, "get_settings", lambda: _settings("postgresql://h/db"))

    def _must_not_be_reached(*args, **kwargs):
        pytest.fail("main() reached service construction or uvicorn with an unsupported URL")

    no_logs_no_server.setattr(main_module, "build_services", _must_not_be_reached)
    no_logs_no_server.setattr(main_module, "_run_uvicorn", _must_not_be_reached)

    with pytest.raises(ValueError):
        main_module.main(["--no-tools"])
