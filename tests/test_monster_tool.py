"""`/monster` tool module (SPEC-0018, WP-7): `NAME`, `run`, hit and training replies.

T-21..T-26: tool contract and empty input, hit rendering, true miss, training prompt builder,
store and logs, source hygiene. The model is a stub; no network, no Ollama, no files: every
catalog is built inline with make_creature.
"""

import logging
from pathlib import Path

import pytest

from app.intelligence.client import IntelligenceError
from app.intelligence.monster_blocks import render_stat_block
from app.intelligence.prompt_builders import (
    DM_ROLE_PROMPT,
    MONSTER_DIRECTIVES_TRAINING,
    build_monster_prompt,
)
from app.intelligence.tools import ToolError
from app.intelligence.tools import monster as monster_tool
from tests.creature_fixtures import make_creature

USAGE = "Usage: /monster <monster name> [2014|2024]"
TOOL_LOGGER = "app.intelligence.tools.monster"
ROOT = Path(__file__).resolve().parents[1]

GOBLIN = make_creature("Goblin", "5.5e", id="goblin", armor_class=15, hit_points=7)
RED_DRAGON = make_creature("Red Dragon", "5.5e", id="red-dragon")
BLUE_DRAGON = make_creature("Blue Dragon", "5.5e", id="blue-dragon")
CATALOG = [GOBLIN, RED_DRAGON, BLUE_DRAGON]


class FakeInference:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return "MODEL REPLY"


class _StoreThatMustNotBeTouched:
    def __getattr__(self, name):
        raise AssertionError(f"tool touched the store: {name}")


def _ctx(fake, catalog=CATALOG):
    return {"inference": fake, "reference": {"creatures": catalog}}


# T-21
def test_contract_empty_and_help():
    assert monster_tool.NAME == "monster"
    assert callable(monster_tool.run)
    fake = FakeInference()
    for empty in ("", "  ", "\n\t"):
        with pytest.raises(ToolError) as exc:
            monster_tool.run(empty, _ctx(fake))
        assert str(exc.value) == USAGE
    assert fake.prompts == []

    result = monster_tool.run("help", _ctx(fake))
    assert result == {
        "text": monster_tool.HELP,
        "meta": {"tool": "monster", "help": True},
    }
    assert fake.prompts == []


# T-22
def test_hit_renders_without_llm():
    fake = FakeInference()
    result = monster_tool.run("  goblin ", _ctx(fake))
    assert result == {
        "text": render_stat_block(GOBLIN),
        "meta": {"tool": "monster", "source": "creatures", "creature_ids": ["goblin"]},
    }
    assert fake.prompts == []


def test_ambiguity_and_typo_errors_propagate():
    fake = FakeInference()
    with pytest.raises(ToolError, match="matches several monsters"):
        monster_tool.run("dragon", _ctx(fake))
    with pytest.raises(ToolError, match="Did you mean: Goblin"):
        monster_tool.run("gobln", _ctx(fake))
    assert fake.prompts == []


# T-23
def test_true_miss_is_one_flagged_training_call():
    assert monster_tool.TRAINING_DISCLAIMER == "Not checked against the SRD monster text."
    fake = FakeInference()
    result = monster_tool.run("  Zorbax the Unknowable ", _ctx(fake))
    assert result == {
        "text": "MODEL REPLY\n\n" + monster_tool.TRAINING_DISCLAIMER,
        "meta": {"tool": "monster", "source": "training", "creature_ids": []},
    }
    assert fake.prompts == [build_monster_prompt("Zorbax the Unknowable")]


@pytest.mark.parametrize(
    "context_extra",
    [
        {},
        {"reference": {}},
        {"reference": {"creatures": None}},
        {"reference": {"creatures": []}},
    ],
    ids=["no-reference", "no-creatures-key", "none", "empty-list"],
)
def test_missing_or_empty_catalog_is_training(context_extra):
    fake = FakeInference()
    ctx = {"inference": fake, **context_extra}
    result = monster_tool.run("Zorbax the Unknowable", ctx)
    assert result["meta"] == {"tool": "monster", "source": "training", "creature_ids": []}
    assert result["text"] == "MODEL REPLY\n\n" + monster_tool.TRAINING_DISCLAIMER
    assert fake.prompts == [build_monster_prompt("Zorbax the Unknowable")]


# T-24
def test_builder_has_no_narrator_voice():
    prompt = build_monster_prompt("  Beholder ")
    assert prompt == "MONSTER: Beholder\n\n" + MONSTER_DIRECTIVES_TRAINING
    assert DM_ROLE_PROMPT not in prompt
    assert "VOICE:" not in prompt
    assert "SYS:" not in prompt


def test_builder_inference_errors_propagate():
    class FailingInference:
        def generate(self, prompt):
            raise IntelligenceError("model unavailable")

    with pytest.raises(IntelligenceError, match="model unavailable"):
        monster_tool.run("Zorbax the Unknowable", _ctx(FailingInference()))


# T-25
def test_store_is_never_touched():
    fake = FakeInference()
    ctx = {**_ctx(fake), "store": _StoreThatMustNotBeTouched()}
    assert monster_tool.run("goblin", ctx)["meta"]["source"] == "creatures"
    assert monster_tool.run("Zorbax the Unknowable", ctx)["meta"]["source"] == "training"


def test_logs_counts_and_ids_only(caplog):
    query = "Zorbax ZZMARKER"
    fake = FakeInference()
    with caplog.at_level(logging.DEBUG):
        hit = monster_tool.run("goblin", _ctx(fake))
    lookups = [r for r in caplog.records if r.name == TOOL_LOGGER]
    assert len(lookups) == 1
    assert lookups[0].getMessage() == "monster.lookup"
    assert lookups[0].source == "creatures"
    assert lookups[0].creature_count == 1
    assert lookups[0].rendered_chars == len(hit["text"])

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        miss = monster_tool.run(query, _ctx(fake))
    lookups = [r for r in caplog.records if r.name == TOOL_LOGGER]
    assert len(lookups) == 1
    assert lookups[0].getMessage() == "monster.lookup"
    assert lookups[0].source == "training"
    assert lookups[0].creature_count == 0
    assert lookups[0].rendered_chars == 0

    secrets = [
        query,
        "ZZMARKER",
        "Zorbax",
        "Goblin",
        "goblin",
        render_stat_block(GOBLIN),
        build_monster_prompt(query),
        "MONSTER:",
        "DIRECTIVES",
        "MODEL REPLY",
    ]
    for record in lookups:
        blob = " ".join(str(v) for v in record.__dict__.values()) + record.getMessage()
        for secret in secrets:
            assert secret not in blob, secret
    assert "MODEL REPLY" in miss["text"]


# T-26
@pytest.mark.parametrize(
    "path",
    [
        ROOT / "app" / "intelligence" / "tools" / "monster.py",
        ROOT / "app" / "intelligence" / "monster_blocks.py",
    ],
    ids=["tool", "renderer"],
)
def test_source_hygiene(path):
    text = path.read_text(encoding="utf-8")
    for forbidden in (
        "dnd_data",
        "open5e",
        "httpx",
        "open(",
        ".read_text(",
        "build_narrator_prompt",
    ):
        assert forbidden not in text, forbidden
    assert "from scripts" not in text
    assert "import scripts" not in text
