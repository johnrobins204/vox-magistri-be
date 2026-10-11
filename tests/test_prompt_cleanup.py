"""Cleanup of app/intelligence after SPEC-0006 (T-31..T-34; WP-11 extends this file).

T-33 is split in two: the writer-reference half (WP-4) and the dead-builder half (WP-3).
"""

import importlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
VOICE_CONFIGS_DIR = APP_DIR / "intelligence" / "voice_configs"
DEAD_BUILDERS = ("build_game_chat_prompt", "build_game_state_payload", "build_turn_summary")
KEPT_BUILDERS = (
    "build_narrator_prompt",
    "build_adjudicator_prompt",
    "NarratorVoiceParams",
    "_truncate",
    "_compact_json",
    "_verbosity_to_sentences",
    "load_voice_configs",
    "build_system_prompt",
    "build_chat_messages",
)


def test_t31_prompts_module_imports_and_reexports_prompting():
    prompts = importlib.import_module("app.intelligence.prompts")
    prompting = importlib.import_module("app.intelligence.prompting")

    assert prompts.build_session_prompt is prompting.build_session_prompt
    assert prompts.build_world_guidance_prompt is prompting.build_world_guidance_prompt
    assert prompts.WORLD_GUIDANCE_MODES is prompting.WORLD_GUIDANCE_MODES

    text = prompts.build_world_guidance_prompt(mode="Clarify", step_name="x", answers={})
    assert isinstance(text, str)


def test_t32_writer_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.intelligence.writer")
    assert not (APP_DIR / "intelligence" / "writer.py").exists()

    intelligence = importlib.import_module("app.intelligence")
    assert "writer" not in intelligence.__all__
    assert intelligence.__all__ == [
        "client",
        "prompt_builders",
        "tools",
        "tool_handler",
        "world_guide",
    ]


def test_t33_writer_references_gone_from_app_source():
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in APP_DIR.rglob("*.py")
        if "intelligence.writer" in p.read_text(encoding="utf-8")
        or "from .writer" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"writer still referenced in: {offenders}"


def test_t33_dead_builders_gone_and_kept_builders_present():
    prompt_builders = importlib.import_module("app.intelligence.prompt_builders")

    for name in DEAD_BUILDERS:
        assert not hasattr(prompt_builders, name), name
    for name in KEPT_BUILDERS:
        assert hasattr(prompt_builders, name), name

    world_guide = importlib.import_module("app.intelligence.world_guide")
    assert world_guide.WorldGuide is not None


def test_t33_dead_builder_names_absent_from_app_source():
    forbidden = (*DEAD_BUILDERS, "intelligence.writer")
    offenders = [
        f"{p.relative_to(REPO_ROOT)}: {name}"
        for p in APP_DIR.rglob("*.py")
        for name in forbidden
        if name in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"dead names still referenced in: {offenders}"


def test_t34_voice_file_renamed():
    renamed = VOICE_CONFIGS_DIR / "voice_configs.json"
    assert renamed.exists()
    data = json.loads(renamed.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert set(data) == {"dm_voice", "dm_analysis", "player_voice", "player_journal"}

    assert not (VOICE_CONFIGS_DIR / "voice_congfigs.json").exists()
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in APP_DIR.rglob("*.py")
        if "voice_congfigs" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"voice_congfigs still referenced in: {offenders}"
