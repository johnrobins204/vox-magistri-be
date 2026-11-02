"""SPEC-0012 WP-3: CI budget, no-dropped-entries and no-runtime-upstream checks.

OPEN5E_MODELS registers each open5e-ingested dataset with its model. WP-4 adds weapons.
"""

import ast
import importlib
import json
import logging
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
REFERENCE_DIR = APP_DIR / "reference"
MAX_BYTES = 2_000_000
MAX_ENTRIES = 2_000
FORBIDDEN_IMPORTS = {"scripts", "sync_open5e", "ingest_open5e"}
UPSTREAM_HOST = b"api.open5e.com"

OPEN5E_MODELS: dict[str, tuple[str, str]] = {
    "weapons": ("app.reference.weapons", "Weapon"),
    "rules": ("app.reference.rules", "Rule"),
}

REFERENCE_FILES = sorted(REFERENCE_DIR.glob("*.json"))


def _entry_count(path: Path) -> int:
    return len(json.loads(path.read_text(encoding="utf-8")))


def test_t24_glob_is_non_empty_and_includes_species():
    names = {p.name for p in REFERENCE_FILES}

    assert REFERENCE_FILES
    assert "species.json" in names


@pytest.mark.parametrize("path", REFERENCE_FILES, ids=lambda p: p.name)
def test_t24_committed_reference_file_is_within_budget(path):
    assert path.stat().st_size <= MAX_BYTES
    assert _entry_count(path) <= MAX_ENTRIES


@pytest.mark.parametrize(
    "dataset",
    list(OPEN5E_MODELS) or [pytest.param(None, marks=pytest.mark.skip(reason="none committed"))],
    ids=lambda d: d or "none-committed",
)
def test_t25_open5e_file_drops_no_entries(dataset, caplog):
    loader = importlib.import_module("app.reference.loader")
    module_name, model_name = OPEN5E_MODELS[dataset]
    model = getattr(importlib.import_module(module_name), model_name)
    path = REFERENCE_DIR / f"{dataset}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))

    with caplog.at_level(logging.WARNING):
        loaded = loader.load_entries(path, model, dataset)

    assert len(loaded) == len(raw)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# SPEC-0014 T-24: the committed rules catalog is present and within budget.
def test_t24_rules_file_is_committed_and_within_budget():
    path = REFERENCE_DIR / "rules.json"

    assert path in REFERENCE_FILES
    assert path.stat().st_size <= MAX_BYTES
    assert 1 <= _entry_count(path) <= MAX_ENTRIES


def test_t26_no_file_under_app_names_the_upstream_host():
    offenders = [
        str(path.relative_to(ROOT))
        for path in APP_DIR.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and UPSTREAM_HOST in path.read_bytes()
    ]

    assert offenders == []


def test_t26_no_app_module_imports_scripts():
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name.split(".")[0] in FORBIDDEN_IMPORTS for name in names):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert offenders == []
