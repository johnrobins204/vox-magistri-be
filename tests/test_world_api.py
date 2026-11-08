"""World entity operator API (SPEC-0015 WP-5; T-27, T-28, T-30..T-34).

API tests use the `client` fixture (":memory:" store via build_services) and send AUTH.
"""

import asyncio
from datetime import datetime

from fastapi.testclient import TestClient

from app.factory import create_app
from app.services.build_services import build_services
from app.services.repos import make_default_repos
from app.type_defs import EntityKind, EntityStatus
from tests.session_helpers import AUTH

ENTITIES = "/api/v1/world/entities"


def _new_session(client) -> str:
    resp = client.post("/api/v1/sessions", json={})
    assert resp.status_code == 201
    return resp.json()["session_id"]


def _create(client, **body) -> dict:
    resp = client.post(ENTITIES, json=body, headers=AUTH)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_auth_required(client):
    entity_id = "some-id"
    calls = [
        ("get", ENTITIES, None),
        ("post", ENTITIES, {"name": "Aldric"}),
        ("get", f"{ENTITIES}/{entity_id}", None),
        ("patch", f"{ENTITIES}/{entity_id}", {"notes": "x"}),
        ("delete", f"{ENTITIES}/{entity_id}", None),
    ]
    for method, path, body in calls:
        resp = client.request(method, path, json=body)
        assert resp.status_code == 401, (method, path)


def test_create(client):
    session_id = _new_session(client)

    minimal = _create(client, name="Aldric")
    assert minimal["name"] == "Aldric"
    assert minimal["kind"] == "other"
    assert minimal["status"] == "canon"
    assert minimal["aliases"] == []
    assert minimal["notes"] == ""
    assert minimal["session_id"] is None
    for key in ("created_at", "updated_at"):
        ts = datetime.fromisoformat(minimal[key])
        assert ts.utcoffset() is not None and ts.utcoffset().total_seconds() == 0

    full = _create(
        client,
        name="Captain Vell",
        kind="npc",
        aliases=["The Grey Captain"],
        notes="Owes the thieves' guild a favour.",
        status="pending",
        session_id=session_id,
    )
    assert full["name"] == "Captain Vell"
    assert full["kind"] == "npc"
    assert full["aliases"] == ["The Grey Captain"]
    assert full["notes"] == "Owes the thieves' guild a favour."
    assert full["status"] == "pending"
    assert full["session_id"] == session_id


def test_create_validation(client):
    session_id = _new_session(client)
    bad_bodies = [
        {"name": "A", "kind": "dragon"},
        {"name": "A", "status": "approved"},
        {"name": ""},
        {"name": "x" * 121},
        {"name": "A", "aliases": [f"a{i}" for i in range(21)]},
        {"name": "A", "aliases": ["x" * 61]},
        {"name": "A", "aliases": [""]},
        {"name": "A", "notes": "x" * 1001},
        {"name": "A", "unexpected": True},
    ]
    for body in bad_bodies:
        resp = client.post(ENTITIES, json=body, headers=AUTH)
        assert resp.status_code == 422, body

    resp = client.post(ENTITIES, json={"name": "A", "session_id": "nope"}, headers=AUTH)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Session not found"}

    # Boundary values are accepted.
    _create(client, name="x" * 120, aliases=["y" * 60] * 20, notes="z" * 1000)
    assert session_id


def test_list(client):
    session_id = _new_session(client)
    other_session = _new_session(client)
    global_npc = _create(client, name="Global", kind="npc")
    scoped = _create(client, name="Scoped", kind="place", status="pending", session_id=session_id)
    _create(client, name="Elsewhere", session_id=other_session)

    resp = client.get(ENTITIES, headers=AUTH)
    assert resp.status_code == 200
    assert len(resp.json()["entities"]) == 3

    in_session = client.get(ENTITIES, params={"session_id": session_id}, headers=AUTH).json()
    assert {e["id"] for e in in_session["entities"]} == {global_npc["id"], scoped["id"]}

    pending = client.get(ENTITIES, params={"status": "pending"}, headers=AUTH).json()
    assert [e["id"] for e in pending["entities"]] == [scoped["id"]]

    npcs = client.get(ENTITIES, params={"kind": "npc"}, headers=AUTH).json()
    assert [e["id"] for e in npcs["entities"]] == [global_npc["id"]]

    for params in ({"status": "approved"}, {"kind": "dragon"}):
        assert client.get(ENTITIES, params=params, headers=AUTH).status_code == 422


def test_get_patch_delete(client):
    created = _create(client, name="Aldric", aliases=["Al"])
    url = f"{ENTITIES}/{created['id']}"

    got = client.get(url, headers=AUTH)
    assert got.status_code == 200
    assert got.json()["id"] == created["id"]

    missing = client.get(f"{ENTITIES}/nope", headers=AUTH)
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Entity not found"}

    patched = client.patch(url, json={"notes": "Met at the docks."}, headers=AUTH)
    assert patched.status_code == 200
    body = patched.json()
    assert body["notes"] == "Met at the docks."
    assert body["name"] == "Aldric"
    assert body["aliases"] == ["Al"]
    assert body["kind"] == "other"

    unchanged = client.patch(url, json={}, headers=AUTH)
    assert unchanged.status_code == 200
    assert unchanged.json() == body

    assert client.patch(url, json={"status": "approved"}, headers=AUTH).status_code == 422
    assert client.patch(url, json={"session_id": None}, headers=AUTH).status_code == 422
    assert client.patch(url, json={"name": None}, headers=AUTH).status_code == 422
    assert client.patch(f"{ENTITIES}/nope", json={"notes": "x"}, headers=AUTH).status_code == 404

    deleted = client.delete(url, headers=AUTH)
    assert deleted.status_code == 204
    assert client.get(url, headers=AUTH).status_code == 404


def _resolve(spec: dict, schema: dict) -> dict:
    while "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def test_openapi_world_routes(client):
    # T-43 (SPEC-0015 WP-7)
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]

    collection = paths[ENTITIES]
    assert {"get", "post"} <= set(collection)
    item = paths[f"{ENTITIES}/{{entity_id}}"]
    assert {"get", "patch", "delete"} <= set(item)

    list_params = {p["name"]: p for p in collection["get"]["parameters"]}
    for name, enum in (("kind", EntityKind), ("status", EntityStatus)):
        schema = _resolve(spec, list_params[name]["schema"])
        if "anyOf" in schema:  # optional query params render as anyOf[enum, null]
            schema = _resolve(spec, next(s for s in schema["anyOf"] if "enum" in s or "$ref" in s))
        assert set(schema["enum"]) == {m.value for m in enum}, name

    for model in ("WorldEntityResp", "WorldEntityCreateReq"):
        props = spec["components"]["schemas"][model]["properties"]
        for name, enum in (("kind", EntityKind), ("status", EntityStatus)):
            schema = _resolve(spec, props[name])
            assert set(schema["enum"]) == {m.value for m in enum}, (model, name)


# T-06 (SPEC-0019 WP-2)
def test_entity_resp_exposes_evidence_read_only(session_store):
    app = create_app(services={"session": session_store, "world": session_store})
    evidence = {"source": "reply", "message_id": "m1", "snippet": "Rusty Anchor"}
    with TestClient(app) as c:
        api_id = _create(c, name="Aldric")["id"]
        stored_id = session_store.create_entity(name="Rusty Anchor", evidence=evidence)["id"]

        assert c.get(f"{ENTITIES}/{api_id}", headers=AUTH).json()["evidence"] is None
        assert c.get(f"{ENTITIES}/{stored_id}", headers=AUTH).json()["evidence"] == evidence
        listed = c.get(ENTITIES, headers=AUTH).json()["entities"]
        assert {e["id"]: e["evidence"] for e in listed} == {api_id: None, stored_id: evidence}

        assert c.post(ENTITIES, json={"name": "A", "evidence": {}}, headers=AUTH).status_code == 422
        url = f"{ENTITIES}/{api_id}"
        assert c.patch(url, json={"evidence": {}}, headers=AUTH).status_code == 422

        spec = c.get("/openapi.json").json()["components"]["schemas"]
    assert "evidence" in spec["WorldEntityResp"]["properties"]
    assert "evidence" not in spec["WorldEntityCreateReq"]["properties"]
    assert "evidence" not in spec["WorldEntityPatchReq"]["properties"]


def test_world_store_missing(session_store):
    app = create_app(services={"session": session_store})
    with TestClient(app) as c:
        resp = c.get(ENTITIES, headers=AUTH)
        assert resp.status_code == 503
        assert resp.json() == {"detail": "World store unavailable"}

        resp = c.post(ENTITIES, json={"name": "Aldric"}, headers=AUTH)
        assert resp.status_code == 503
        assert resp.json() == {"detail": "World store unavailable"}


def test_services_shape():
    services = build_services(make_default_repos(), enable_tool_discovery=False)
    try:
        assert set(services) == {"session", "tool", "inference", "reference", "world"}
        assert services["world"] is services["session"]
    finally:
        asyncio.run(services["inference"].shutdown())
