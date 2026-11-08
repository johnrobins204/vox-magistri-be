"""SPEC-0018 WP-4: creatures catalog loaded once at startup, fail-soft (T-11..T-12).

No test opens a network connection or needs Ollama.
"""

import asyncio
import json
import logging
from pathlib import Path

from app.reference.creatures import Creature
from app.services.build_services import build_services
from app.services.repos import make_default_repos

RAW_CREATURES_PATH = Path(__file__).resolve().parents[1] / "app" / "reference" / "creatures.json"


def _build():
    return build_services(make_default_repos(), enable_tool_discovery=False)


# T-11
def test_t11_creatures_catalog_is_loaded_once_at_startup():
    raw = json.loads(RAW_CREATURES_PATH.read_text(encoding="utf-8"))
    services = _build()
    try:
        creatures = services["reference"]["creatures"]
        assert isinstance(creatures, list)
        assert all(isinstance(entry, Creature) for entry in creatures)
        assert len(creatures) == len(raw)
        assert services["tool"].default_context["reference"] is services["reference"]
        assert len(services["reference"]["species"]) > 0
        assert len(services["reference"]["weapons"]) > 0
        assert len(services["reference"]["rules"]) > 0
    finally:
        asyncio.run(services["inference"].shutdown())


# T-12
def test_t12_missing_creatures_file_is_fail_soft(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("app.services.build_services.CREATURES_PATH", tmp_path / "missing.json")
    with caplog.at_level(logging.WARNING):
        services = _build()
    try:
        assert services["reference"]["creatures"] == []
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert warnings[0].getMessage() == "reference.unavailable"
        assert warnings[0].dataset == "creatures"
        assert warnings[0].reason == "missing"
        assert len(services["reference"]["species"]) == 68
        assert len(services["reference"]["weapons"]) > 0
    finally:
        asyncio.run(services["inference"].shutdown())
