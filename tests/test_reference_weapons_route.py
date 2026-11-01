"""SPEC-0012 WP-4: weapons pilot, wiring and read-only route (T-27..T-31).

No test opens a network connection or needs Ollama.
"""

import asyncio
import json
import logging

from fastapi.testclient import TestClient

from app.factory import create_app
from app.reference.loader import load_entries
from app.reference.weapons import WEAPONS_PATH, Weapon
from app.services.build_services import build_services
from app.services.repos import make_default_repos

WEAPONS_URL = "/api/v1/reference/weapons"
WEAPON_KEYS = {
    "id",
    "name",
    "edition",
    "source",
    "publisher",
    "third_party",
    "source_key",
    "damage_dice",
    "damage_type",
    "properties",
    "range",
    "long_range",
    "distance_unit",
    "is_simple",
    "is_improvised",
}


def _raw_count() -> int:
    return len(json.loads(WEAPONS_PATH.read_text(encoding="utf-8")))


def test_t27_checked_in_weapons_load_without_warnings(caplog):
    with caplog.at_level(logging.WARNING):
        weapons = load_entries(WEAPONS_PATH, Weapon, "weapons")

    assert len(weapons) == _raw_count()
    assert all(isinstance(w, Weapon) for w in weapons)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_t28_services_reference_holds_the_weapons_catalog():
    services = build_services(make_default_repos(), enable_tool_discovery=False)
    try:
        assert len(services["reference"]["weapons"]) == _raw_count()
        assert services["tool"].default_context["reference"] is services["reference"]
    finally:
        asyncio.run(services["inference"].shutdown())


def test_t29_weapons_route_returns_catalog_with_expected_keys(client):
    resp = client.get(WEAPONS_URL)

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"weapons"}
    assert all(set(item) == WEAPON_KEYS for item in body["weapons"])
    assert body["weapons"] == [
        w.model_dump() for w in load_entries(WEAPONS_PATH, Weapon, "weapons")
    ]


def test_t30_weapons_route_is_read_only(client):
    assert client.post(WEAPONS_URL, json={}).status_code == 405
    assert client.put(WEAPONS_URL, json={}).status_code == 405


def test_t31_missing_weapons_key_returns_503_with_detail():
    app = create_app(services={"reference": {"species": []}})
    with TestClient(app) as c:
        resp = c.get(WEAPONS_URL)

    assert resp.status_code == 503
    assert "detail" in resp.json()
