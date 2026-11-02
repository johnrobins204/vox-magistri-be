"""SPEC-0014 WP-6: rules catalog loaded once at startup, fail-soft (T-27..T-28).

No test opens a network connection or needs Ollama.
"""

import asyncio
import json
import logging
from pathlib import Path

from app.reference.rules import Rule
from app.services.build_services import build_services
from app.services.repos import make_default_repos

RAW_RULES_PATH = Path(__file__).resolve().parents[1] / "app" / "reference" / "rules.json"


def _build():
    return build_services(make_default_repos(), enable_tool_discovery=False)


# T-27
def test_t27_catalog_is_loaded_once_at_startup():
    raw = json.loads(RAW_RULES_PATH.read_text(encoding="utf-8"))
    services = _build()
    try:
        rules = services["reference"]["rules"]
        assert isinstance(rules, list)
        assert all(isinstance(entry, Rule) for entry in rules)
        assert len(rules) == len(raw)
        assert services["tool"].default_context["reference"] is services["reference"]
        assert len(services["reference"]["species"]) > 0
        assert len(services["reference"]["weapons"]) > 0
    finally:
        asyncio.run(services["inference"].shutdown())


# T-28
def test_t28_missing_rules_file_is_fail_soft(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("app.services.build_services.RULES_PATH", tmp_path / "missing.json")
    with caplog.at_level(logging.WARNING):
        services = _build()
    try:
        assert services["reference"]["rules"] == []
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert warnings[0].getMessage() == "reference.unavailable"
        assert warnings[0].dataset == "rules"
        assert warnings[0].reason == "missing"
        assert len(services["reference"]["species"]) == 68
        assert len(services["reference"]["weapons"]) > 0
    finally:
        asyncio.run(services["inference"].shutdown())
