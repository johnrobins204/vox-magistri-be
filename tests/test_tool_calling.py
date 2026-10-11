import importlib.util
import logging
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.factory import create_app
from app.intelligence import tools as tools_pkg
from app.intelligence.client import IntelligenceError
from app.intelligence.prompt_builders import NarratorVoiceParams, build_narrator_prompt
from app.intelligence.tool_handler import get_registry
from app.intelligence.tools import ToolError
from app.intelligence.tools import narrate as narrate_tool
from app.services.build_services import build_services
from app.services.repos import make_default_repos
from app.services.tool_service import ToolService, UnknownToolError


def test_discovery_registers_narrate():
    tools = ToolService(discover_on_init=True).list_tools()
    assert tools.get("narrate") == "app.intelligence.tools.narrate"


def test_discovery_registers_roll_and_narrate():
    tools = ToolService(discover_on_init=True).list_tools()
    assert tools.get("roll") == "app.intelligence.tools.roll"
    assert tools.get("narrate") == "app.intelligence.tools.narrate"


def test_discovery_skips_non_contract_modules(tmp_path, monkeypatch):
    pkg_name = f"vm_fixture_tools_{uuid.uuid4().hex}"
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "good.py").write_text('NAME = "good"\n\ndef run(args, context):\n    return "ok"\n')
    (pkg_dir / "bad.py").write_text("def run(args, context):\n    return 'no NAME'\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(tools_pkg, "TOOLS_PACKAGE", pkg_name)

    tools = ToolService(discover_on_init=True).list_tools()

    assert set(tools) == {"good"}


def test_single_discovery_path():
    registry_names = set(get_registry(refresh=True))
    service_names = set(ToolService().list_tools())
    assert registry_names == service_names
    assert "narrate" in registry_names


def test_invoke_passes_string_args_and_merged_context():
    sentinel = object()
    seen = {}

    def echo(args, ctx):
        seen.update(args=args, ctx=ctx)
        return "ok"

    svc = ToolService(default_context={"repos": sentinel}, discover_on_init=False)
    svc.register_tool("echo", echo)

    result = svc.invoke("echo", "hello", {"extra": 1})

    assert seen["args"] == "hello"
    assert seen["ctx"]["repos"] is sentinel
    assert seen["ctx"]["extra"] == 1
    assert result == {"text": "ok", "meta": {}}


def test_invoke_unknown_tool_raises():
    svc = ToolService(discover_on_init=False)

    with pytest.raises(UnknownToolError) as exc_info:
        svc.invoke("nope")

    assert str(exc_info.value) == "Unknown tool: nope"


def test_invoke_exception_propagates():
    def boom(args, ctx):
        raise ValueError("boom")

    def bad_input(args, ctx):
        raise ToolError("bad input")

    svc = ToolService(discover_on_init=False)
    svc.register_tool("boom", boom)
    svc.register_tool("bad_input", bad_input)

    with pytest.raises(ValueError) as value_exc:
        svc.invoke("boom")
    assert str(value_exc.value) == "boom"

    with pytest.raises(ToolError) as tool_exc:
        svc.invoke("bad_input")
    assert str(tool_exc.value) == "bad input"


def test_invoke_normalizes_results():
    svc = ToolService(discover_on_init=False)
    svc.register_tool("plain", lambda args, ctx: "plain")
    svc.register_tool("full", lambda args, ctx: {"text": "t", "meta": {"a": 1}})
    svc.register_tool("bare", lambda args, ctx: {"text": "t"})
    svc.register_tool("number", lambda args, ctx: 42)

    assert svc.invoke("plain") == {"text": "plain", "meta": {}}
    assert svc.invoke("full") == {"text": "t", "meta": {"a": 1}}
    assert svc.invoke("bare") == {"text": "t", "meta": {}}
    with pytest.raises(TypeError):
        svc.invoke("number")


class _Evil:
    def __repr__(self) -> str:
        return "EVIL-VALUE"


def test_client_context_cannot_override_server_keys(caplog):
    real = object()
    real_repos = object()
    evil = _Evil()
    seen = {}

    def echo(args, ctx):
        seen.update(ctx)
        return "ok"

    svc = ToolService(
        default_context={"inference": real, "repos": real_repos}, discover_on_init=False
    )
    svc.register_tool("echo", echo)

    with caplog.at_level(logging.WARNING, logger="app.services.tool_service"):
        svc.invoke(
            "echo",
            "",
            {"session_id": "s1"},
            client_context={
                "inference": evil,
                "repos": evil,
                "store": evil,
                "session_id": "evil",
                "message_id": "evil",
                "logger": evil,
                "rng": evil,
                "extra": 1,
            },
        )

    assert seen["inference"] is real
    assert seen["repos"] is real_repos
    assert seen["session_id"] == "s1"
    assert seen["extra"] == 1
    for key in ("store", "message_id", "rng"):
        assert key not in seen
    assert seen["logger"] is not evil

    warnings = [
        r
        for r in caplog.records
        if r.name == "app.services.tool_service" and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    for key in ("inference", "repos", "store", "message_id", "logger", "rng", "session_id"):
        assert key in message
    assert "EVIL-VALUE" not in message


def test_client_context_cannot_override_default_context_keys(caplog):
    seen = {}

    def echo(args, ctx):
        seen.update(ctx)
        return "ok"

    svc = ToolService(default_context={"custom": "server"}, discover_on_init=False)
    svc.register_tool("echo", echo)

    with caplog.at_level(logging.WARNING, logger="app.services.tool_service"):
        svc.invoke("echo", "", client_context={"custom": "client", "fresh": 2})

    assert seen["custom"] == "server"
    assert seen["fresh"] == 2
    warnings = [
        r
        for r in caplog.records
        if r.name == "app.services.tool_service" and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "custom" in warnings[0].getMessage()


def test_tool_runs_outside_the_registry_lock():
    release = threading.Event()
    started = threading.Event()

    def slow(args, ctx):
        started.set()
        release.wait(timeout=10)
        return "slow"

    svc = ToolService(discover_on_init=False)
    svc.register_tool("slow", slow)
    svc.register_tool("fast", lambda args, ctx: "fast")
    slow_result = {}
    slow_thread = threading.Thread(target=lambda: slow_result.update(svc.invoke("slow")))
    slow_thread.start()
    try:
        assert started.wait(timeout=2)
        outcome = {}

        def fast_and_list():
            outcome["fast"] = svc.invoke("fast")
            outcome["list"] = svc.list_tools()

        worker = threading.Thread(target=fast_and_list, daemon=True)
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive(), "invoke/list_tools blocked behind a running tool"
        assert outcome["fast"] == {"text": "fast", "meta": {}}
        assert "slow" in outcome["list"]
    finally:
        release.set()
        slow_thread.join(timeout=5)
    assert slow_result == {"text": "slow", "meta": {}}


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


# T-19
def test_build_services_wires_tool_service_into_inference():
    repos = make_default_repos()
    services = build_services(repos, enable_tool_discovery=False)

    assert set(services) == {"session", "tool", "inference"}
    assert services["inference"]._tool_service is services["tool"]
    assert services["tool"].default_context["inference"] is services["inference"]
    assert services["tool"].default_context["repos"] is repos


def _endpoint_client():
    services = build_services(make_default_repos(), enable_tool_discovery=True)
    app = create_app(services=services)
    return services, TestClient(app)


def test_invoke_endpoint_success_passes_meta():
    services, client = _endpoint_client()
    services["tool"].register_tool("hi", lambda a, c: {"text": "hi", "meta": {"k": 1}})

    resp = client.post("/api/v1/intel/tools/hi/invoke", json={"args": ""})

    assert resp.status_code == 200
    assert resp.json() == {"text": "hi", "meta": {"k": 1}, "error": None}


def test_invoke_endpoint_unknown_tool_is_404():
    _services, client = _endpoint_client()

    resp = client.post("/api/v1/intel/tools/nope/invoke", json={"args": ""})

    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "Unknown tool: nope"
    assert body["detail"] == "Unknown tool: nope"
    assert body["text"] is None
    assert body["meta"] is None


def test_invoke_endpoint_tool_error_is_400():
    services, client = _endpoint_client()

    def bad(args, ctx):
        raise ToolError("bad dice")

    services["tool"].register_tool("bad", bad)

    resp = client.post("/api/v1/intel/tools/bad/invoke", json={"args": ""})

    assert resp.status_code == 400
    assert resp.json()["error"] == "bad dice"
    assert resp.json()["text"] is None


def test_invoke_endpoint_intelligence_error_is_502():
    services, client = _endpoint_client()

    def down(args, ctx):
        raise IntelligenceError("ollama down")

    services["tool"].register_tool("down", down)

    resp = client.post("/api/v1/intel/tools/down/invoke", json={"args": ""})

    assert resp.status_code == 502
    assert resp.json()["error"] == "ollama down"


def test_invoke_endpoint_other_exception_is_500(caplog):
    services, client = _endpoint_client()

    def broken(args, ctx):
        raise RuntimeError("boom")

    services["tool"].register_tool("broken", broken)

    with caplog.at_level(logging.ERROR):
        resp = client.post("/api/v1/intel/tools/broken/invoke", json={"args": ""})

    assert resp.status_code == 500
    assert resp.json()["error"] == "boom"
    assert any(r.levelno == logging.ERROR and r.exc_info for r in caplog.records)


def test_invoke_endpoint_ignores_client_supplied_service_objects():
    repos = make_default_repos()
    services = build_services(repos, enable_tool_discovery=True)
    app = create_app(services=services)
    client = TestClient(app)
    seen = {}

    def record(args, ctx):
        seen.update(ctx)
        return "ok"

    services["tool"].register_tool("record", record)

    resp = client.post(
        "/api/v1/intel/tools/record/invoke",
        json={"args": "", "context": {"inference": "evil", "repos": "evil", "extra": 1}},
    )

    assert resp.status_code == 200
    assert seen["inference"] is services["inference"]
    assert seen["repos"] is repos
    assert seen["extra"] == 1


class FakeInference:
    """Stand-in for the injected inference service: records prompts, never touches Ollama."""

    def __init__(self, reply="The tavern hums."):
        self.prompts = []
        self._reply = reply

    def generate(self, prompt):
        self.prompts.append(prompt)
        return self._reply


def test_narrate_empty_args_raises_tool_error():
    fake = FakeInference()

    for blank in ("", "   "):
        with pytest.raises(ToolError) as exc_info:
            narrate_tool.run(blank, {"inference": fake})
        assert str(exc_info.value) == "Usage: /narrate <what happens>"

    assert fake.prompts == []


def test_narrate_builds_current_prompt_and_uses_inference():
    p = get_settings().prompts
    expected_params = NarratorVoiceParams(
        tone=p.dm_voice.tone,
        dm_persona=p.dm_voice.persona,
        verbosity=p.verbosity_default,
        sensory_focus=p.dm_voice.sensory_focus,
        consequence_level=p.dm_voice.consequence_level,
    )
    expected_prompt = build_narrator_prompt("describe the tavern", expected_params, None)
    fake = FakeInference()

    result = narrate_tool.run("  describe the tavern  ", {"inference": fake})

    assert fake.prompts == [expected_prompt]
    assert result == {"text": "The tavern hums.", "meta": {"tool": "narrate"}}
    assert "prompt" not in result["meta"]


def test_narrate_via_tool_service_uses_injected_inference():
    fake = FakeInference()
    svc = ToolService(default_context={"inference": fake}, discover_on_init=True)

    result = svc.invoke("narrate", "a storm")

    assert result["text"] == "The tavern hums."
    assert len(fake.prompts) == 1
    assert result["meta"] == {"tool": "narrate"}


def test_clear_module_file_is_deleted():
    clear_path = Path(tools_pkg.__file__).parent / "clear.py"

    assert not clear_path.exists()
    assert importlib.util.find_spec("app.intelligence.tools.clear") is None


def test_clear_is_not_registered():
    assert "clear" not in ToolService(discover_on_init=True).list_tools()
    assert "clear" not in tools_pkg.discover_tool_modules()
    assert "clear" not in tools_pkg.discover_tools()
    assert "roll" in ToolService(discover_on_init=True).list_tools()
    assert "narrate" in ToolService(discover_on_init=True).list_tools()


def test_invoke_endpoint_clear_is_unknown_tool_404():
    _services, client = _endpoint_client()

    resp = client.post("/api/v1/intel/tools/clear/invoke", json={"args": ""})

    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "Unknown tool: clear"
    assert body["detail"] == "Unknown tool: clear"
    assert body["text"] is None
    assert body["meta"] is None
