"""Side-chat system prompt builder in app/intelligence/prompt_builders.py (SPEC-0023 WP-2; S-1..S-4).

TOOL_GUIDE names every discovered tool, and build_sidechat_system_prompt joins the side-chat
role, the optional dm_analysis text and the guide. No test opens a network connection.
"""

from app.intelligence.prompt_builders import (
    SIDECHAT_ROLE_PROMPT,
    TOOL_GUIDE,
    build_sidechat_system_prompt,
)
from app.services.tool_service import ToolService


def test_s1_tool_guide_names_every_discovered_tool():
    assert isinstance(TOOL_GUIDE, str) and TOOL_GUIDE
    for name in ToolService(discover_on_init=True).list_tool_descriptions():
        assert f"/{name}" in TOOL_GUIDE, name


def test_s2_tool_guide_content_and_no_req_ids():
    assert "/rules" in TOOL_GUIDE
    rules_line = next(line for line in TOOL_GUIDE.splitlines() if "/rules" in line)
    assert "rule" in rules_line.lower()
    assert "grapple" in rules_line
    attack_line = next(line for line in TOOL_GUIDE.splitlines() if "/attack" in line)
    assert "vs" in attack_line
    assert "/narrate" in TOOL_GUIDE
    for prefix in ("REQ-", "SPEC-", "ADR-"):
        assert prefix not in TOOL_GUIDE
    assert len(TOOL_GUIDE.encode("utf-8")) <= 1200


def test_s3_sidechat_prompt_order_and_content():
    result = build_sidechat_system_prompt({"dm_analysis": "X-ANALYSIS"})
    assert result == "\n\n".join([SIDECHAT_ROLE_PROMPT, "X-ANALYSIS", TOOL_GUIDE])
    assert "VOICE:" not in result
    assert "not narrate" in SIDECHAT_ROLE_PROMPT


def test_s4_sidechat_prompt_without_usable_analysis():
    expected = "\n\n".join([SIDECHAT_ROLE_PROMPT, TOOL_GUIDE])
    for configs in ({}, {"dm_analysis": ""}, {"dm_analysis": 5}):
        result = build_sidechat_system_prompt(configs)
        assert result == expected
        assert "None" not in result
