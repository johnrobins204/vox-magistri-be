"""Deletions and structure of the single session model (SPEC-0004 WP-5)."""

import asyncio
import importlib
import inspect
import re
from pathlib import Path

from app.services import repos as repos_module
from app.services.build_services import build_services
from app.services.repos import (
    SqliteSessionStore,
    make_default_repos,
    seed_sample_data,
)
from app.type_defs import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"


def test_build_services_has_no_game_key():
    services = build_services(make_default_repos(), enable_tool_discovery=False)
    try:
        # SPEC-0011 T-21 amendment: ADR-0006 adds the reference catalog to the services shape.
        assert set(services) == {"session", "tool", "inference", "reference", "world"}
    finally:
        asyncio.run(services["inference"].shutdown())


def test_removed_modules_are_gone():
    for name in ("app.services.session_service", "app.services.game_service"):
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            pass
        else:
            raise AssertionError(f"{name} is still importable")

    assert not (APP_DIR / "services" / "session_service.py").exists()
    assert not (APP_DIR / "services" / "game_service.py").exists()


def test_no_references_to_removed_symbols():
    banned = ("SessionService", "GameService", "session_service", "game_service", "SessionEntry")
    for path in APP_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path.relative_to(REPO_ROOT)} mentions {token!r}"

    run_id_files = [
        *sorted((APP_DIR / "api" / "v1").glob("*.py")),
        APP_DIR / "schemas" / "v1.py",
        APP_DIR / "services" / "messages.py",
    ]
    for path in run_id_files:
        assert "run_id" not in path.read_text(
            encoding="utf-8"
        ), f"{path.relative_to(REPO_ROOT)} mentions 'run_id'"

    no_probe_files = [
        APP_DIR / "api" / "v1" / "ws.py",
        APP_DIR / "api" / "v1" / "intelligence.py",
        APP_DIR / "api" / "v1" / "session.py",
        APP_DIR / "services" / "messages.py",
    ]
    for path in no_probe_files:
        assert "hasattr(" not in path.read_text(
            encoding="utf-8"
        ), f"{path.relative_to(REPO_ROOT)} uses hasattr("


def test_make_default_repos_returns_sqlite_store():
    repos = make_default_repos()
    try:
        assert isinstance(repos["session"], SqliteSessionStore)

        seed_sample_data(repos)
        assert len(repos["session"].list_messages("demo")) == 1
    finally:
        repos["session"].close()


def test_in_memory_store_and_default_repos_removed():
    assert not hasattr(repos_module, "InMemorySessionStore")
    assert not hasattr(repos_module, "DEFAULT_REPOS")

    main_text = (APP_DIR / "main.py").read_text(encoding="utf-8")
    assert "InMemorySessionStore" not in main_text
    assert "DEFAULT_REPOS" not in main_text
    assert "database.url" in main_text


def test_protocol_update_message_status_has_optional_meta():
    from app.services.repos import SqliteSessionStore

    for owner in (SessionStore, SqliteSessionStore):
        sig = inspect.signature(owner.update_message_status)
        assert list(sig.parameters) == ["self", "session_id", "message_id", "status", "meta"]
        assert sig.parameters["meta"].default is None


def test_session_store_protocol_unchanged():
    names = {n for n in vars(SessionStore) if not n.startswith("_")}
    assert names == {
        "get_session",
        "create_session",
        "get_character",
        "create_message",
        "get_message",
        "get_by_client_id",
        "list_messages",
        "update_message_status",
    }


def test_data_layer_removed():
    for name in ("__init__.py", "models.py", "repos.py", "migrations.py"):
        assert not (REPO_ROOT / "data" / name).exists(), f"data/{name} still exists"
    assert not (REPO_ROOT / "data").exists(), "data/ directory still exists"

    import_of_data = re.compile(r"^\s*(from|import)\s+data\b", re.MULTILINE)
    for path in APP_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not import_of_data.search(text), f"{path.relative_to(REPO_ROOT)} imports data"


def test_no_new_runtime_dependency():
    requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "sqlalchemy" not in requirements
