"""`/rules` tool module (SPEC-0014, WP-7): `NAME`, `run`, grounded and training replies.

T-29..T-38: tool contract and empty input, grounded answer, training fallback, catalog
missing or empty, budget cases, both editions keeping one id, no narrator voice, meta shape
and errors, counts-only logs, source hygiene. The model is a stub; no network, no Ollama,
no files: every catalog is built inline.
"""

import logging
from pathlib import Path

import pytest

from app.config import PromptSettings, Settings
from app.intelligence import prompt_builders
from app.intelligence.client import IntelligenceError
from app.intelligence.prompt_builders import DM_ROLE_PROMPT, build_rules_prompt
from app.intelligence.tools import ToolError
from app.intelligence.tools import rules as rules_tool
from app.reference.rules import Rule

USAGE = "Usage: /rules <your rules question>"
TOOL_LOGGER = "app.intelligence.tools.rules"
ROOT = Path(__file__).resolve().parents[1]

OPP_DESC = (
    "When a creature you can see leaves your reach, you may use your reaction to make a melee "
    "attack against it. Once a turn."
)
COVER_DESC = (
    "A target with half cover gains a +2 bonus to AC and Dexterity saving throws. Three-quarters "
    "cover gives +5. Total cover blocks line of sight entirely."
)


def _rule(id, name, description, edition):
    return Rule(
        id=id,
        name=name,
        edition=edition,
        source="5e 2024 Rules" if edition == "5.5e" else "5e 2014 Rules",
        publisher="Wizards of the Coast",
        third_party=False,
        source_key=f"srd-2024_{id}" if edition == "5.5e" else f"srd-2014_{id}",
        description=description,
    )


OPP = _rule("opportunity-attacks", "Opportunity Attacks", OPP_DESC, "5.5e")
COVER = _rule("cover", "Cover", COVER_DESC, "5.5e")
COVER_5E = _rule("cover-5e", "Cover", COVER_DESC, "5e")
CATALOG = [OPP, COVER, COVER_5E]


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
    return {"inference": fake, "reference": {"rules": catalog}}


def set_budget(monkeypatch, n):
    monkeypatch.setattr(
        rules_tool,
        "get_settings",
        lambda: Settings(prompts=PromptSettings(rules_budget_chars=n)),
    )


@pytest.fixture(autouse=True)
def _default_budget(monkeypatch):
    set_budget(monkeypatch, 6000)


# T-29
def test_contract_and_empty_input():
    assert rules_tool.NAME == "rules"
    assert callable(rules_tool.run)
    fake = FakeInference()
    for empty in ("", "   ", "\n\t "):
        with pytest.raises(ToolError) as exc:
            rules_tool.run(empty, _ctx(fake))
        assert str(exc.value) == USAGE
    assert fake.prompts == []


# T-30
def test_grounded_answer():
    fake = FakeInference()
    result = rules_tool.run("  Can I use an Opportunity Attack?  ", _ctx(fake))
    assert result == {
        "text": "MODEL REPLY",
        "meta": {"tool": "rules", "source": "rules", "rule_ids": ["opportunity-attacks"]},
    }
    assert len(fake.prompts) == 1
    expected = build_rules_prompt(
        "Can I use an Opportunity Attack?",
        [{"name": "Opportunity Attacks", "edition": "5.5e", "text": OPP_DESC}],
    )
    assert fake.prompts[0] == expected
    assert OPP_DESC in fake.prompts[0]
    assert rules_tool.TRAINING_DISCLAIMER not in result["text"]


# T-31
def test_nothing_relevant_means_training():
    fake = FakeInference()
    question = "what is the airspeed of a swallow"
    result = rules_tool.run(question, _ctx(fake))
    assert rules_tool.TRAINING_DISCLAIMER == "Not checked against the SRD rules text."
    assert result["text"] == "MODEL REPLY\n\n" + rules_tool.TRAINING_DISCLAIMER
    assert result["meta"] == {"tool": "rules", "source": "training", "rule_ids": []}
    assert fake.prompts == [build_rules_prompt(question, [])]


# T-32
@pytest.mark.parametrize(
    "context_extra",
    [
        {},
        {"reference": {}},
        {"reference": {"rules": []}},
        {"reference": {"rules": None}},
    ],
    ids=["no-reference", "no-rules-key", "empty-list", "none"],
)
def test_catalog_missing_or_empty_means_training(context_extra):
    fake = FakeInference()
    question = "opportunity attacks"
    ctx = {"inference": fake, **context_extra}
    result = rules_tool.run(question, ctx)
    assert result["meta"] == {"tool": "rules", "source": "training", "rule_ids": []}
    assert result["text"] == "MODEL REPLY\n\n" + rules_tool.TRAINING_DISCLAIMER
    assert fake.prompts == [build_rules_prompt(question, [])]


# T-33
def test_budget_cases_mean_training(monkeypatch):
    question = "Can I use an Opportunity Attack?"

    set_budget(monkeypatch, 0)
    fake = FakeInference()
    result = rules_tool.run(question, _ctx(fake))
    assert result["meta"] == {"tool": "rules", "source": "training", "rule_ids": []}

    set_budget(monkeypatch, 100)
    assert len(OPP_DESC) == 120
    fake = FakeInference()
    result = rules_tool.run(question, _ctx(fake))
    assert result["meta"] == {"tool": "rules", "source": "training", "rule_ids": []}
    assert OPP_DESC not in fake.prompts[0]

    set_budget(monkeypatch, 6000)
    fake = FakeInference()
    result = rules_tool.run(question, _ctx(fake))
    assert result["meta"]["source"] == "rules"
    assert OPP_DESC in fake.prompts[0]


# T-34
def test_both_editions_keep_one_id():
    fake = FakeInference()
    result = rules_tool.run("cover", _ctx(fake))
    assert result["meta"]["rule_ids"] == ["cover"]
    assert fake.prompts[0].count(COVER_DESC) == 1


# T-35
def test_no_narrator_voice(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("build_narrator_prompt must not be called")

    monkeypatch.setattr(prompt_builders, "build_narrator_prompt", boom)
    assert not hasattr(rules_tool, "build_narrator_prompt")

    fake = FakeInference()
    assert rules_tool.run("Can I use an Opportunity Attack?", _ctx(fake))["meta"]["source"] == (
        "rules"
    )
    assert rules_tool.run("airspeed of a swallow", _ctx(fake))["meta"]["source"] == "training"
    for prompt in fake.prompts:
        assert DM_ROLE_PROMPT not in prompt
        assert "VOICE:" not in prompt
        assert "SYS:" not in prompt


# T-36
def test_meta_shape_no_store_and_errors_propagate():
    fake = FakeInference()
    ctx = {**_ctx(fake), "store": _StoreThatMustNotBeTouched()}
    result = rules_tool.run("Can I use an Opportunity Attack?", ctx)
    assert set(result["meta"]) == {"tool", "source", "rule_ids"}

    class FailingInference:
        def generate(self, prompt):
            raise IntelligenceError("model unavailable")

    with pytest.raises(IntelligenceError, match="model unavailable"):
        rules_tool.run("Can I use an Opportunity Attack?", _ctx(FailingInference()))


# T-37
def test_logs_counts_only(caplog):
    question = "opportunity attack ZZMARKER"
    secrets = [
        question,
        "ZZMARKER",
        OPP_DESC,
        "Opportunity Attacks",
        "RULES EXCERPTS",
        "DIRECTIVES",
    ]

    fake = FakeInference()
    with caplog.at_level(logging.DEBUG):
        rules_tool.run(question, _ctx(fake))
    grounded = [r for r in caplog.records if r.name == TOOL_LOGGER]
    assert len(grounded) == 1
    assert grounded[0].getMessage() == "rules.consulted"
    assert grounded[0].source == "rules"
    assert grounded[0].rule_count == 1
    assert grounded[0].excerpt_chars == len(OPP_DESC)

    caplog.clear()
    training_question = "airspeed swallow ZZMARKER"
    with caplog.at_level(logging.DEBUG):
        rules_tool.run(training_question, _ctx(fake))
    training = [r for r in caplog.records if r.name == TOOL_LOGGER]
    assert len(training) == 1
    assert training[0].getMessage() == "rules.consulted"
    assert training[0].source == "training"
    assert training[0].rule_count == 0
    assert training[0].excerpt_chars == 0

    for record in grounded + training:
        blob = " ".join(str(v) for v in record.__dict__.values()) + record.getMessage()
        for secret in secrets:
            assert secret not in blob


# T-38
def test_source_hygiene():
    text = (ROOT / "app" / "intelligence" / "tools" / "rules.py").read_text(encoding="utf-8")
    for forbidden in (
        "dnd_data",
        "open5e",
        "httpx",
        ".read_text(",
        "open(",
        "build_narrator_prompt",
        "NarratorVoiceParams",
    ):
        assert forbidden not in text, forbidden
    assert "from scripts" not in text
    assert "import scripts" not in text
