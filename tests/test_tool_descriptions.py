"""Tool DESCRIPTION contract (SPEC-0020, WP-1): one plain-language line per tool module.

T-1..T-3: each discovered tool module has a single-line DESCRIPTION of at most 100
characters, the text carries no REQ-/SPEC-/ADR- ids, and the five known tools are found.
"""

import types

from fastapi.testclient import TestClient

from app.factory import create_app
from app.intelligence.tools import discover_tool_modules
from app.services.build_services import build_services
from app.services.repos import make_default_repos
from app.services.tool_service import ToolService

KNOWN_TOOLS = {"narrate", "rules", "monster", "attack", "roll"}
ID_MARKERS = ("REQ-", "SPEC-", "ADR-")


def _modules():
    return discover_tool_modules()


def test_every_tool_module_has_description():
    for mod in _modules().values():
        mod_name = mod.__name__
        description = getattr(mod, "DESCRIPTION", None)
        assert isinstance(description, str), f"{mod_name}: DESCRIPTION must be a str"
        assert description.strip(), f"{mod_name}: DESCRIPTION must be non-empty"
        assert "\n" not in description, f"{mod_name}: DESCRIPTION must be one line"
        assert len(description) <= 100, f"{mod_name}: DESCRIPTION is over 100 characters"


def test_descriptions_are_user_text():
    for mod in _modules().values():
        for marker in ID_MARKERS:
            assert (
                marker not in mod.DESCRIPTION
            ), f"{mod.__name__}: DESCRIPTION must not contain {marker}"


def test_five_known_tools_discovered():
    assert KNOWN_TOOLS <= set(_modules()), "expected narrate, rules, monster, attack, roll"


# WP-2: ToolService.list_tool_descriptions() (T-4..T-7)


def test_list_tool_descriptions_matches_list_tools():
    svc = ToolService(discover_on_init=True)
    descriptions = svc.list_tool_descriptions()
    assert descriptions.keys() == svc.list_tools().keys()
    for name in KNOWN_TOOLS:
        assert isinstance(descriptions[name], str)
        assert descriptions[name].strip(), f"{name}: description must be non-empty"


def test_manually_registered_tool_has_empty_description():
    svc = ToolService(discover_on_init=False)
    svc.register_tool("echo", lambda args, ctx: "")
    assert svc.list_tool_descriptions()["echo"] == ""


def test_non_string_description_becomes_empty():
    svc = ToolService(discover_on_init=False)
    mod = types.ModuleType("odd_tool")
    mod.DESCRIPTION = 5
    svc.register_tool("odd", lambda args, ctx: "", module=mod)
    assert svc.list_tool_descriptions()["odd"] == ""


def test_list_tools_unchanged():
    svc = ToolService(discover_on_init=True)
    tools = svc.list_tools()
    assert isinstance(tools, dict)
    assert all(isinstance(v, str) for v in tools.values())
    assert tools["roll"] == "app.intelligence.tools.roll"


# WP-3: GET /api/v1/intel/tools returns `description` (T-8..T-11)


def test_api_tools_include_description():
    services = build_services(make_default_repos(), enable_tool_discovery=True)
    client = TestClient(create_app(services=services))
    resp = client.get("/api/v1/intel/tools")
    assert resp.status_code == 200
    items = {t["name"]: t for t in resp.json()["tools"]}
    for name in KNOWN_TOOLS:
        assert items[name]["module"]
        assert items[name]["description"].strip(), f"{name}: description must be non-empty"


def test_api_tool_without_description_is_empty_string():
    services = build_services(make_default_repos(), enable_tool_discovery=True)
    services["tool"].register_tool("echo", lambda a, c: "")
    client = TestClient(create_app(services=services))
    resp = client.get("/api/v1/intel/tools")
    assert resp.status_code == 200
    echo = next(t for t in resp.json()["tools"] if t["name"] == "echo")
    assert echo["description"] == ""


def test_openapi_tool_info_has_optional_description():
    services = build_services(make_default_repos(), enable_tool_discovery=False)
    client = TestClient(create_app(services=services))
    schema = client.get("/openapi.json").json()["components"]["schemas"]["ToolInfo"]
    assert "description" in schema["properties"]
    assert "description" not in schema.get("required", [])


def test_tool_list_resp_uses_v2_config():
    from app.schemas.v1 import ToolListResp

    assert "json_schema_extra" in ToolListResp.model_config
    assert not hasattr(ToolListResp, "Config")
