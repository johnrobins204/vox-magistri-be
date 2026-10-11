import logging

from fastapi.testclient import TestClient

from app.factory import create_app
from app.intelligence import tools as tools_pkg
from app.intelligence.tool_handler import get_registry
from app.services.build_services import build_services
from app.services.repos import make_default_repos
from app.services.tool_service import ToolService


def test_discovery_registers_narrate():
    tools = ToolService(discover_on_init=True).list_tools()
    assert tools.get("narrate") == "app.intelligence.tools.narrate"


def test_discovery_skips_non_contract_modules():
    tools = ToolService(discover_on_init=True).list_tools()
    assert "roll" not in tools
    assert "clear" not in tools


def test_single_discovery_path():
    registry_names = set(get_registry(refresh=True))
    service_names = set(ToolService().list_tools())
    assert registry_names == service_names
    assert "narrate" in registry_names


def test_invoke_passes_string_args_and_merged_context():
    sentinel = object()
    svc = ToolService(default_context={"repos": sentinel}, discover_on_init=False)
    svc.register_tool("echo", lambda args, ctx: (args, ctx))

    args, ctx = svc.invoke("echo", "hello", {"extra": 1})

    assert args == "hello"
    assert ctx["repos"] is sentinel
    assert ctx["extra"] == 1


def test_invoke_unknown_tool_returns_message():
    svc = ToolService(discover_on_init=False)
    assert svc.invoke("nope") == "Unknown tool: nope"


def test_invoke_exception_returns_error_string():
    def bad(args, ctx):
        raise ValueError("boom")

    svc = ToolService(discover_on_init=False)
    svc.register_tool("bad", bad)

    assert svc.invoke("bad") == "Tool bad error: boom"


def test_discovery_failure_is_logged_not_silent(monkeypatch, caplog):
    monkeypatch.setattr(tools_pkg, "TOOLS_PACKAGE", "app.no_such_tools")

    with caplog.at_level(logging.ERROR):
        svc = ToolService(discover_on_init=True)

    assert svc.list_tools() == {}
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_api_lists_and_invokes_registered_tool():
    services = build_services(make_default_repos(), enable_tool_discovery=True)
    app = create_app(services=services)
    client = TestClient(app)
    services["tool"].register_tool("echo", lambda a, c: f"echo:{a}")

    listing = client.get("/api/v1/intel/tools")
    assert listing.status_code == 200
    assert "narrate" in [t["name"] for t in listing.json()["tools"]]

    invoke = client.post("/api/v1/intel/tools/echo/invoke", json={"args": "hi"})
    assert invoke.status_code == 200
    assert invoke.json()["text"] == "echo:hi"


def test_build_services_injects_inference_into_tool_context():
    repos = make_default_repos()
    services = build_services(repos, enable_tool_discovery=False)

    assert services["tool"].default_context["inference"] is services["inference"]
    assert services["tool"].default_context["repos"] is repos
