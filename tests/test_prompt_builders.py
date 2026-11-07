"""Prompt pipeline builders in app/intelligence/prompt_builders.py (SPEC-0006 WP-2/WP-3; T-07..T-22).

T-07..T-17 cover build_system_prompt and build_chat_messages; T-18..T-22 cover load_voice_configs.
No test opens a network connection or needs Ollama.
"""

import copy
import inspect
import logging

import pytest

from app.config import PromptSettings, PromptVoiceSettings, Settings
from app.intelligence.prompt_builders import (
    DM_ROLE_PROMPT,
    VOICE_CONFIGS_PATH,
    _truncate,
    build_chat_messages,
    build_system_prompt,
    load_voice_configs,
)

LOGGER_NAME = "app.intelligence.prompt_builders"
VOICE_KEYS = {"dm_voice", "dm_analysis", "player_voice", "player_journal"}
DEFAULT_VOICE_LINE = (
    "VOICE: TONE:neutral|PERSONA:classic_dm|VERBOSITY:normal|SENSE:balanced|CONSEQ:moderate"
)
SYSTEM = build_system_prompt(Settings().prompts, {})


def _m(id, role, content, status="completed", canon=None):
    return {
        "id": id,
        "role": role,
        "content": content,
        "status": status,
        "meta": {},
        "canon": canon,
    }


def _warnings(caplog):
    return [r for r in caplog.records if r.name == LOGGER_NAME and r.levelno == logging.WARNING]


# --- system prompt (T-07..T-09) and chat messages (T-10..T-17) -------------------------


def test_dm_role_prompt_wording_is_fixed():
    assert DM_ROLE_PROMPT == (
        "You are the Dungeon Master of a D&D 5e game. Narrate the world, play its characters, "
        "and respond to the player's actions without deciding what the player does."
    )


def test_t07_system_prompt_full_order_and_voice_line():
    text = build_system_prompt(Settings().prompts, {"dm_voice": "VOICE-SENTENCE"})

    assert DM_ROLE_PROMPT in text
    assert "VOICE-SENTENCE" in text
    assert "TONE:neutral|PERSONA:classic_dm|VERBOSITY:normal|SENSE:balanced|CONSEQ:moderate" in text
    assert (
        text.index(DM_ROLE_PROMPT) < text.index("VOICE-SENTENCE") < text.index(DEFAULT_VOICE_LINE)
    )
    assert text == "\n\n".join([DM_ROLE_PROMPT, "VOICE-SENTENCE", DEFAULT_VOICE_LINE])


def test_t08_system_prompt_empty_voice_configs_add_nothing():
    base = build_system_prompt(Settings().prompts, {})

    assert isinstance(base, str) and base
    assert DM_ROLE_PROMPT in base
    assert DEFAULT_VOICE_LINE in base
    assert base == "\n\n".join([DM_ROLE_PROMPT, DEFAULT_VOICE_LINE])
    assert build_system_prompt(Settings().prompts, {"dm_voice": ""}) == base
    assert build_system_prompt(Settings().prompts, {"other": "x"}) == base


def test_t09_system_prompt_reflects_settings():
    prompts = PromptSettings(
        verbosity_default="long",
        dm_voice=PromptVoiceSettings(
            tone="grim", persona="p", sensory_focus="smell", consequence_level="harsh"
        ),
    )
    text = build_system_prompt(prompts, {})

    voice_line = "VOICE: TONE:grim|PERSONA:p|VERBOSITY:long|SENSE:smell|CONSEQ:harsh"
    assert "TONE:grim|PERSONA:p|VERBOSITY:long|SENSE:smell|CONSEQ:harsh" in text
    assert text == "\n\n".join([DM_ROLE_PROMPT, voice_line])


def test_t10_message_order_prior_then_current():
    history = [
        _m("u0", "user", "earlier"),
        _m("a0", "assistant", "answer"),
        _m("u1", "user", "now", "running"),
    ]

    messages = build_chat_messages(SYSTEM, history, "u1", "now", max_turns=6, max_field_len=240)

    assert messages == [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "now"},
    ]


def test_t11_filters_status_role_and_position():
    history = [
        _m("u0", "user", "ok-user"),
        _m("a0", "assistant", "ok-asst"),
        _m("q", "user", "queued-user", "queued"),
        _m("r", "user", "running-user", "running"),
        _m("e", "user", "error-user", "error"),
        _m("c", "assistant", "cancelled-asst", "cancelled"),
        _m("s", "system", "system-row"),
        _m("cur", "user", "now", "running"),
        _m("after", "user", "after-current"),
    ]

    messages = build_chat_messages(SYSTEM, history, "cur", "now", max_turns=6, max_field_len=240)

    assert messages == [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "ok-user"},
        {"role": "assistant", "content": "ok-asst"},
        {"role": "user", "content": "now"},
    ]


def test_t12_max_turns_keeps_last_n_oldest_first():
    history = [_m(f"m{i}", "user" if i % 2 == 0 else "assistant", f"text-{i}") for i in range(10)]

    def expected(indices):
        return [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"text-{i}"} for i in indices
        ]

    capped = build_chat_messages(SYSTEM, history, "cur", "now", max_turns=4, max_field_len=240)
    assert capped == [
        {"role": "system", "content": SYSTEM},
        *expected(range(6, 10)),
        {"role": "user", "content": "now"},
    ]
    assert len(capped) == 6

    uncapped = build_chat_messages(SYSTEM, history, "cur", "now", max_turns=100, max_field_len=240)
    assert uncapped == [
        {"role": "system", "content": SYSTEM},
        *expected(range(10)),
        {"role": "user", "content": "now"},
    ]


@pytest.mark.parametrize("max_turns", [0, -3])
def test_t13_non_positive_max_turns_keep_only_system_and_current(max_turns):
    history = [_m("u0", "user", "earlier"), _m("a0", "assistant", "answer")]

    messages = build_chat_messages(
        SYSTEM, history, "cur", "now", max_turns=max_turns, max_field_len=240
    )

    assert messages == [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "now"},
    ]


def test_t14_empty_history_and_no_campaign_parameter():
    messages = build_chat_messages(SYSTEM, [], "cur", "hello", max_turns=6, max_field_len=240)

    assert messages == [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "hello"},
    ]
    assert list(inspect.signature(build_chat_messages).parameters) == [
        "system",
        "history",
        "current_message_id",
        "current_text",
        "max_turns",
        "max_field_len",
    ]


def test_t15_truncates_prior_messages_only():
    long_prior = "p" * 500
    exact_prior = "e" * 20
    long_current = "c" * 500
    history = [
        _m("u0", "user", long_prior),
        _m("a0", "assistant", exact_prior),
        _m("cur", "user", long_current, "running"),
    ]

    messages = build_chat_messages(
        SYSTEM, history, "cur", long_current, max_turns=6, max_field_len=20
    )

    assert messages[1] == {"role": "user", "content": _truncate(long_prior, 20)}
    assert len(messages[1]["content"]) == 20
    assert messages[1]["content"].endswith("…")
    assert messages[2] == {"role": "assistant", "content": exact_prior}
    assert messages[-1] == {"role": "user", "content": long_current}


def test_t16_unknown_current_id_uses_all_eligible_messages():
    history = [
        _m("u0", "user", "first"),
        _m("a0", "assistant", "second"),
        _m("x", "user", "queued-one", "queued"),
    ]

    messages = build_chat_messages(SYSTEM, history, "ghost", "now", max_turns=6, max_field_len=240)
    assert messages == [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "now"},
    ]

    capped = build_chat_messages(SYSTEM, history, "ghost", "now", max_turns=1, max_field_len=240)
    assert capped == [
        {"role": "system", "content": SYSTEM},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "now"},
    ]


def test_t17_plain_dicts_only_and_no_mutation():
    history = [
        {"id": "u0", "role": "user", "content": "a", "status": "completed"},
        {"id": "a0", "role": "assistant", "content": "b", "status": "completed"},
        {"id": "cur", "role": "user", "content": "c", "status": "running"},
    ]
    before = copy.deepcopy(history)

    messages = build_chat_messages(SYSTEM, history, "cur", "now", max_turns=6, max_field_len=240)

    assert history == before
    assert messages == [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "now"},
    ]
    assert all(set(item) == {"role", "content"} for item in messages)


# --- canon filter (SPEC-0016 WP-3; T-20, T-21) -------------------------------------------


def test_non_canon_skipped():
    history = [
        _m("u0", "user", "keep-u0", canon=True),
        _m("a0", "assistant", "drop-a0", canon=False),
        _m("u1", "user", "keep-u1", canon=None),
        {"id": "a1", "role": "assistant", "content": "keep-a1", "status": "completed"},
        _m("u2", "user", "drop-u2", canon=False),
        _m("cur", "user", "now", "running"),
    ]

    messages = build_chat_messages(SYSTEM, history, "cur", "now", max_turns=6, max_field_len=240)

    assert messages == [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "keep-u0"},
        {"role": "user", "content": "keep-u1"},
        {"role": "assistant", "content": "keep-a1"},
        {"role": "user", "content": "now"},
    ]


def test_max_turns_counts_only_canon():
    history = [
        _m("c0", "user", "c0", canon=True),
        _m("c1", "assistant", "c1", canon=True),
        _m("c2", "user", "c2", canon=True),
        _m("x", "assistant", "non-canon", canon=False),
        _m("c3", "assistant", "c3", canon=True),
        _m("c4", "user", "c4", canon=True),
        _m("cur", "user", "now", "running"),
    ]

    messages = build_chat_messages(SYSTEM, history, "cur", "now", max_turns=3, max_field_len=240)

    assert messages == [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "c2"},
        {"role": "assistant", "content": "c3"},
        {"role": "user", "content": "c4"},
        {"role": "user", "content": "now"},
    ]


# --- voice config loader (T-18..T-22) ----------------------------------------------------


def test_t18_loader_reads_real_file():
    configs = load_voice_configs()

    assert set(configs) == VOICE_KEYS
    assert all(isinstance(v, str) and v for v in configs.values())
    assert VOICE_CONFIGS_PATH.name == "voice_configs.json"
    assert VOICE_CONFIGS_PATH.exists()


def test_t19_missing_file_returns_empty_with_one_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert load_voice_configs(tmp_path / "nope.json") == {}

    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == "voice_configs.unavailable"
    assert records[0].reason == "missing"


def test_t20_invalid_json_returns_empty_with_one_warning(tmp_path, caplog):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert load_voice_configs(path) == {}

    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].reason == "invalid_json"


def test_t21_non_object_json_returns_empty_with_one_warning(tmp_path, caplog):
    path = tmp_path / "list.json"
    path.write_text('["a", "b"]', encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert load_voice_configs(path) == {}

    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].reason == "not_object"


def test_t22_non_string_entries_dropped_with_warning_each_and_no_file_text_logged(tmp_path, caplog):
    raw = '{"dm_voice": 3, "ok": "fine", "n": null}'
    path = tmp_path / "mixed.json"
    path.write_text(raw, encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert load_voice_configs(path) == {"ok": "fine"}

    records = _warnings(caplog)
    assert len(records) == 2
    assert {r.key for r in records} == {"dm_voice", "n"}
    for r in records:
        assert r.getMessage() == "voice_configs.entry_dropped"
        assert raw not in str(vars(r))
