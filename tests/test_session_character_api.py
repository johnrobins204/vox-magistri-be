"""REST contract for the optional character on POST /api/v1/sessions (SPEC-0013 WP-3)."""

import copy

import pytest

from app.deps import get_session_store

ARIA = {
    "id": "hero-1",
    "name": "Aria",
    "lineage": "Wood Elf",
    "species_id": "elf",
    "char_class": "Ranger",
    "level": 3,
    "hp_current": 24,
    "hp_max": 28,
    "ac": 14,
    "abilities": {"STR": 12, "DEX": 16, "CON": 13, "INT": 11, "WIS": 15, "CHA": 10},
    "conditions": ["Blessed"],
}

LEGACY = {
    "name": "Aria",
    "lineage": "Wood Elf",
    "level": 3,
    "hp_current": 24,
    "hp_max": 28,
    "ac": 14,
    "abilities": ARIA["abilities"],
}


def _stored_character(client, session_id):
    return get_session_store().get_character(session_id)


def _post_body(client, body):
    return client.post("/api/v1/sessions", json=body)


def _char(**changes):
    """Body with ARIA plus overrides (each override replaces one key)."""
    return lambda c: {"character": {**c, **changes}}


def test_no_body_returns_201_and_no_character(client):
    resp = client.post("/api/v1/sessions")
    assert resp.status_code == 201
    assert resp.headers["Location"] == f"/api/v1/sessions/{resp.json()['session_id']}"
    assert set(resp.json()) == {"session_id", "capabilities"}
    assert _stored_character(client, resp.json()["session_id"]) is None


@pytest.mark.parametrize("body", [{}, {"character": None}])
def test_empty_or_null_character_returns_201(client, body):
    resp = _post_body(client, body)
    assert resp.status_code == 201
    assert _stored_character(client, resp.json()["session_id"]) is None


def test_valid_character_is_stored_stripped_and_not_echoed(client):
    body = {"character": {**ARIA, "name": f"  {ARIA['name']}  "}}
    resp = _post_body(client, body)
    assert resp.status_code == 201
    assert set(resp.json()) == {"session_id", "capabilities"}
    assert _stored_character(client, resp.json()["session_id"]) == ARIA


def test_legacy_shaped_payload_gets_defaults(client):
    resp = _post_body(client, {"character": LEGACY})
    assert resp.status_code == 201
    stored = _stored_character(client, resp.json()["session_id"])
    assert stored["species_id"] is None
    assert stored["id"] == ""
    assert stored["char_class"] == ""
    assert stored["conditions"] == []


REJECTIONS = [
    ("name-empty", _char(name="")),
    ("name-61", _char(name="x" * 61)),
    ("name-whitespace", _char(name="   ")),
    ("lineage-61", _char(lineage="x" * 61)),
    ("class-41", _char(char_class="x" * 41)),
    ("level-0", _char(level=0)),
    ("level-21", _char(level=21)),
    ("hp-current-negative", _char(hp_current=-1)),
    ("hp-max-0", _char(hp_max=0)),
    ("hp-max-1000", _char(hp_max=1000)),
    ("ac-31", _char(ac=31)),
    ("ac-negative", _char(ac=-1)),
    ("ability-0", _char(abilities={**ARIA["abilities"], "STR": 0})),
    ("ability-31", _char(abilities={**ARIA["abilities"], "STR": 31})),
    (
        "ability-missing",
        _char(abilities={k: v for k, v in ARIA["abilities"].items() if k != "CHA"}),
    ),
    ("ability-extra-key", _char(abilities={**ARIA["abilities"], "LUCK": 10})),
    ("conditions-9", _char(conditions=["Blessed"] * 9)),
    ("condition-41", _char(conditions=["x" * 41])),
    ("species-not-a-slug", _char(species_id="Not A Slug")),
    ("species-65", _char(species_id="a" * 65)),
    ("character-unknown-key", _char(inventory=[])),
    ("body-unknown-key", lambda c: {"character": c, "extra": 1}),
]


@pytest.mark.parametrize("build", [b for _, b in REJECTIONS], ids=[i for i, _ in REJECTIONS])
def test_invalid_character_returns_422(client, build):
    resp = _post_body(client, build(copy.deepcopy(ARIA)))
    assert resp.status_code == 422


BOUNDARIES = [
    {"name": "n" * 60},
    {"lineage": "l" * 60},
    {"char_class": "c" * 40},
    {"id": "i" * 64},
    {"species_id": "a" * 64},
    {"level": 1},
    {"level": 20},
    {"hp_current": 0},
    {"hp_max": 999},
    {"ac": 0},
    {"ac": 30},
    {"abilities": {k: 1 for k in ARIA["abilities"]}},
    {"abilities": {k: 30 for k in ARIA["abilities"]}},
    {"conditions": ["c" * 40] * 8},
]


@pytest.mark.parametrize("override", BOUNDARIES)
def test_boundary_values_accepted(client, override):
    resp = _post_body(client, {"character": {**ARIA, **override}})
    assert resp.status_code == 201


def test_session_created_log_has_flag_and_no_content(client, caplog):
    sentinel = "SENTINEL-c0de"
    with caplog.at_level("INFO"):
        bare = client.post("/api/v1/sessions")
        with_char = _post_body(client, {"character": {**ARIA, "name": sentinel}})
    assert bare.status_code == 201 and with_char.status_code == 201

    created = [r for r in caplog.records if r.getMessage() == "session.created"]
    assert [r.__dict__["has_character"] for r in created] == [False, True]
    for rec in caplog.records:
        assert sentinel not in rec.getMessage()
        assert not any(sentinel in repr(v) for v in rec.__dict__.values())
