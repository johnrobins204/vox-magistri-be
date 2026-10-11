"""Deletions and structure of the single session model (SPEC-0004 WP-5)."""

import asyncio
import importlib
from pathlib import Path

from app.services.build_services import build_services
from app.services.repos import (
    DEFAULT_REPOS,
    InMemorySessionStore,
    make_default_repos,
    seed_sample_data,
)
from app.type_defs import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"


def test_build_services_has_no_game_key():
    services = build_services(make_default_repos(), enable_tool_discovery=False)
    try:
        assert set(services) == {"session", "tool", "inference"}
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


def test_default_repos_names_stable():
    assert isinstance(DEFAULT_REPOS, dict)

    repos = make_default_repos()
    assert isinstance(repos["session"], InMemorySessionStore)

    seed_sample_data(repos)
    assert len(repos["session"].list_messages("demo")) == 1


def test_session_store_protocol_unchanged():
    names = {n for n in vars(SessionStore) if not n.startswith("_")}
    assert names == {
        "get_session",
        "create_session",
        "create_message",
        "get_by_client_id",
        "list_messages",
        "update_message_status",
    }
