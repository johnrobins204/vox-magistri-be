from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
LOGGER_MODULE = APP_DIR / "services" / "logger.py"
TOOL_SERVICE = APP_DIR / "services" / "tool_service.py"


def _app_sources() -> list[Path]:
    return [p for p in APP_DIR.rglob("*.py") if p != LOGGER_MODULE]


def test_no_stdlib_getlogger_outside_logger_module():
    offenders = [
        str(p.relative_to(APP_DIR.parent))
        for p in _app_sources()
        if "logging.getLogger(" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"stdlib logging.getLogger( found in: {offenders}"


def test_tool_service_has_no_print_calls():
    assert "print(" not in TOOL_SERVICE.read_text(encoding="utf-8")
