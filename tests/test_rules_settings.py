import json
from pathlib import Path

import pydantic
import pytest

from app.config import PromptSettings, Settings

ROOT = Path(__file__).resolve().parents[1]


# T-01
def test_rules_budget_chars_default_is_6000_int():
    value = PromptSettings().rules_budget_chars
    assert value == 6000
    assert type(value) is int


# T-02
def test_rules_budget_chars_bounds():
    assert PromptSettings(rules_budget_chars=0).rules_budget_chars == 0
    with pytest.raises(pydantic.ValidationError):
        PromptSettings(rules_budget_chars=-1)


# T-03
def test_settings_json_has_rules_budget_chars():
    data = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
    assert data["prompts"]["rules_budget_chars"] == 6000
    assert Settings(**data).prompts.rules_budget_chars == 6000
