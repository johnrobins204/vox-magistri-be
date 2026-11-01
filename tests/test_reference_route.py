"""SPEC-0011 WP-4: read-only species route under /api/v1/reference (T-22..T-28).

No test opens a network connection or needs Ollama.
"""

import asyncio
import sqlite3

from fastapi.testclient import TestClient

from app.factory import create_app
from app.reference.species import load_species
from app.services.build_services import build_services
from app.services.repos import make_default_repos

SPECIES_KEYS = {
    "id",
    "name",
    "edition",
    "source",
    "publisher",
    "third_party",
    "creature_type",
    "description",
    "character_creation_implications",
}
SPECIES_URL = "/api/v1/reference/species"


def test_t22_species_route_returns_68_entries_with_expected_keys(client):
    resp = client.get(SPECIES_URL)

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"species"}
    assert len(body["species"]) == 68
    assert all(set(item) == SPECIES_KEYS for item in body["species"])


def test_t23_species_route_round_trips_the_loaded_catalog(client):
    resp = client.get(SPECIES_URL)

    assert resp.json()["species"] == [s.model_dump() for s in load_species()]


def test_t24_species_route_is_read_only(client):
    assert client.post(SPECIES_URL, json={}).status_code == 405
    assert client.put(SPECIES_URL, json={}).status_code == 405


def test_t25_no_detail_or_other_reference_routes_yet(client):
    assert client.get("/api/v1/reference/classes").status_code == 404
    assert client.get("/api/v1/reference/species/aasimar").status_code == 404


def test_t26_missing_reference_service_returns_503_with_detail():
    app = create_app(services={"session": make_default_repos()["session"]})
    with TestClient(app) as c:
        resp = c.get(SPECIES_URL)

    assert resp.status_code == 503
    assert "detail" in resp.json()


def test_t27_empty_catalog_returns_200_with_empty_list():
    app = create_app(services={"reference": {"species": []}})
    with TestClient(app) as c:
        resp = c.get(SPECIES_URL)

    assert resp.status_code == 200
    assert resp.json() == {"species": []}


def test_t28_sqlite_holds_no_reference_tables(tmp_path):
    db_path = tmp_path / "t.db"
    repos = make_default_repos(f"sqlite:///{db_path}")
    services = build_services(repos, enable_tool_discovery=False)
    try:
        create_app(services=services)
    finally:
        asyncio.run(services["inference"].shutdown())
        repos["session"].close()

    with sqlite3.connect(db_path) as conn:
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

    assert not any("species" in name or "reference" in name for name in names)
