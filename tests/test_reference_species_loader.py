"""SPEC-0011 WP-2: Species model and fail-soft loader in app/reference/species.py (T-09..T-18).

Mirrors the voice config loader tests in tests/test_prompt_builders.py (T-18..T-22).
No test opens a network connection or needs Ollama.
"""

import json
import logging

from app.reference.species import SPECIES_PATH, Species, load_species

LOGGER_NAME = "app.reference.species"
MARKER = "SECRET-MARKER-XYZ"


def _entry(**overrides):
    entry = {
        "id": "aasimar",
        "name": "Aasimar",
        "edition": "5.5e",
        "source": "Player's Handbook (2024)",
        "publisher": None,
        "third_party": False,
        "creature_type": "Humanoid",
        "description": "d",
        "character_creation_implications": "c",
    }
    entry.update(overrides)
    return entry


def _write(tmp_path, data, name="species.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _warnings(caplog):
    return [r for r in caplog.records if r.name == LOGGER_NAME and r.levelno == logging.WARNING]


def test_t09_checked_in_file_loads_68_species_without_warnings(caplog):
    assert SPECIES_PATH.name == "species.json"
    assert SPECIES_PATH.exists()

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        species = load_species()

    assert len(species) == 68
    assert all(isinstance(s, Species) for s in species)
    assert _warnings(caplog) == []


def test_t10_missing_file_returns_empty_with_one_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert load_species(tmp_path / "nope.json") == []

    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == "reference.unavailable"
    assert records[0].reason == "missing"


def test_t11_invalid_json_returns_empty_with_one_warning(tmp_path, caplog):
    path = tmp_path / "bad.json"
    path.write_text("[{not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert load_species(path) == []

    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == "reference.unavailable"
    assert records[0].reason == "invalid_json"


def test_t12_top_level_not_a_list_returns_empty_with_one_warning(tmp_path, caplog):
    path = _write(tmp_path, {"species": [_entry()]})

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert load_species(path) == []

    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == "reference.unavailable"
    assert records[0].reason == "not_list"


def test_t13_bad_entry_dropped_with_one_warning_and_no_file_text_logged(tmp_path, caplog):
    path = _write(
        tmp_path,
        [
            _entry(id="aasimar", name="Aasimar"),
            _entry(id="bad-one", name=MARKER, publisher=["not", "a", "str"]),
            _entry(id="dragonborn", name="Dragonborn"),
        ],
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        species = load_species(path)

    assert [s.id for s in species] == ["aasimar", "dragonborn"]
    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == "reference.entry_dropped"
    assert records[0].index == 1
    for record in caplog.records:
        assert MARKER not in record.getMessage()
        assert MARKER not in str(vars(record))


def test_t14_extra_key_drops_entry_with_one_warning(tmp_path, caplog):
    path = _write(tmp_path, [_entry(id="aasimar"), _entry(id="dragonborn", unexpected="x")])

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        species = load_species(path)

    assert [s.id for s in species] == ["aasimar"]
    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == "reference.entry_dropped"
    assert records[0].index == 1


def test_t15_third_party_edition_label_drops_entry_with_one_warning(tmp_path, caplog):
    path = _write(tmp_path, [_entry(id="aasimar"), _entry(id="hollow-one", edition="3rd Party")])

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        species = load_species(path)

    assert [s.id for s in species] == ["aasimar"]
    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == "reference.entry_dropped"
    assert records[0].index == 1


def test_t16_duplicate_id_keeps_first_and_drops_second_with_one_warning(tmp_path, caplog):
    path = _write(
        tmp_path,
        [_entry(id="aasimar", name="First"), _entry(id="aasimar", name="Second")],
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        species = load_species(path)

    assert [(s.id, s.name) for s in species] == [("aasimar", "First")]
    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == "reference.entry_dropped"
    assert records[0].index == 1


def test_t17_non_slug_id_drops_entry_with_one_warning(tmp_path, caplog):
    path = _write(tmp_path, [_entry(id="Aasimar"), _entry(id="dragonborn")])

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        species = load_species(path)

    assert [s.id for s in species] == ["dragonborn"]
    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == "reference.entry_dropped"
    assert records[0].index == 0


def test_t18_ci_guard_checked_in_file_drops_no_entries(caplog):
    raw = json.loads(SPECIES_PATH.read_text(encoding="utf-8"))

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        species = load_species()

    assert len(species) == len(raw)
    assert _warnings(caplog) == []
