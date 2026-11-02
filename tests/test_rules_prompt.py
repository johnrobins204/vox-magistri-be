"""Rules consult prompt builder (SPEC-0014, WP-3): `build_rules_prompt`.

T-14..T-17: grounded order, training prompt, no narrator voice, purity and verbatim text.
Pure string building only: no network, no Ollama, no files.
"""

import copy
import inspect

from app.intelligence.prompt_builders import DM_ROLE_PROMPT, build_rules_prompt

FORBIDDEN_NARRATOR_MARKERS = (
    DM_ROLE_PROMPT,
    "SYS:",
    "VOICE:",
    "TONE:",
    "PERSONA:",
    "Dungeon Master",
)


# T-14
def test_grounded_order_and_labels():
    excerpts = [
        {"name": "Cover", "edition": "5.5e", "text": "TEXT-ONE"},
        {"name": "Hiding", "edition": "5e", "text": "TEXT-TWO"},
    ]
    prompt = build_rules_prompt("Does cover stack?", excerpts)
    assert isinstance(prompt, str)
    assert (
        prompt.index("TEXT-ONE")
        < prompt.index("TEXT-TWO")
        < prompt.index("QUESTION: Does cover stack?")
        < prompt.index("DIRECTIVES:")
    )
    assert "[1] Cover (SRD 5.2 (2024))" in prompt
    assert "[2] Hiding (SRD 5.1 (2014))" in prompt


# T-15
def test_training_prompt_without_excerpts():
    question = "How far can I jump?"
    prompt = build_rules_prompt(question, [])
    assert question in prompt
    assert "DIRECTIVES:" in prompt
    assert "general knowledge" in prompt
    assert "RULES EXCERPTS" not in prompt
    assert "[1]" not in prompt
    assert prompt.index(question) < prompt.index("DIRECTIVES:")


# T-16
def test_no_narrator_voice_in_either_mode():
    grounded = build_rules_prompt(
        "Does cover stack?", [{"name": "Cover", "edition": "5.5e", "text": "TEXT-ONE"}]
    )
    training = build_rules_prompt("Does cover stack?", [])
    for prompt in (grounded, training):
        for marker in FORBIDDEN_NARRATOR_MARKERS:
            assert marker not in prompt
    source = inspect.getsource(build_rules_prompt)
    assert "NarratorVoiceParams" not in source
    assert "DM_ROLE_PROMPT" not in source
    assert "build_narrator_prompt" not in source


# T-17
def test_pure_verbatim_and_normalized_inputs():
    raw_text = "\n\n## Heading\n\n|a|b|\n|---|---|"
    excerpts = [
        {"name": "Cover", "edition": "5.5e", "text": raw_text},
        {"name": "Odd", "edition": None, "text": "x"},
        {"name": "Other", "edition": "3.5e", "text": "y"},
    ]
    before = copy.deepcopy(excerpts)
    list_before = list(excerpts)

    first = build_rules_prompt("  x  ", excerpts[:1])
    second = build_rules_prompt("  x  ", excerpts[:1])
    assert first == second
    assert excerpts == before
    assert excerpts == list_before

    assert raw_text in first
    assert "QUESTION: x\n" in first
    assert "QUESTION:  x" not in first

    unknown = build_rules_prompt("q", excerpts[1:])
    assert "Odd (edition unknown)" in unknown
    assert "Other (edition unknown)" in unknown
    assert "(SRD 5.1 (2014))" not in unknown
    assert excerpts == before
