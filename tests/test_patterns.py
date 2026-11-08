"""Pattern linter: mechanical checks for accepted patterns in docs/patterns/.

Each test names the pattern it enforces, so agents get a one-line failure instead of
re-reading the pattern docs. Add a check here when a new pattern has a checkable rule,
then mark the pattern "enforced" in docs/patterns/INDEX.md.
"""

import ast
import re
from pathlib import Path

import pytest

from app.services.messages import RESERVED_META_KEYS

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
TOOLS = APP / "intelligence" / "tools"

LOGGER = APP / "services" / "logger.py"
REPOS = APP / "services" / "repos.py"
PRINT_ALLOWED = {APP / "tst.py"}  # manual smoke script, not application code


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def _importers(files, banned: tuple[str, ...]) -> list[str]:
    hits = []
    for path in files:
        bad = sorted(
            name
            for name in _imports(path)
            if any(name == b or name.startswith(b + ".") for b in banned)
        )
        if bad:
            hits.append(f"{path.relative_to(ROOT)} imports {bad}")
    return hits


def _py(directory: Path):
    return sorted(directory.rglob("*.py"))


def test_pat_code_001_no_stdlib_logging_or_print_in_app():
    offenders = []
    for path in _py(APP):
        if path == LOGGER:
            continue
        for node in ast.walk(_parse(path)):
            where = f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "getLogger":
                    offenders.append(f"{where}: getLogger() (use get_logger)")
                if isinstance(func, ast.Name) and func.id == "print" and path not in PRINT_ALLOWED:
                    offenders.append(f"{where}: print()")
            elif isinstance(node, ast.ImportFrom) and node.module == "logging":
                if any(alias.name == "getLogger" for alias in node.names):
                    offenders.append(f"{where}: from logging import getLogger")
    assert not offenders, offenders


def test_pat_arch_002_sqlite3_only_in_the_session_store():
    files = [p for p in _py(APP) if p != REPOS]
    assert not _importers(files, ("sqlite3",))


def test_pat_arch_001_routers_never_touch_the_store_implementation():
    assert not _importers(
        _py(APP / "api"), ("sqlite3", "app.services.repos", "app.services.build_services")
    )


def test_pat_arch_003_prompt_builders_are_pure():
    banned = (
        "sqlite3",
        "httpx",
        "requests",
        "app.services.repos",
        "app.services.inference_service",
        "app.intelligence.client",
        "app.deps",
    )
    assert not _importers([APP / "intelligence" / "prompt_builders.py"], banned)


WORLD_MENTIONS = APP / "intelligence" / "world_mentions.py"


def test_pat_arch_012_world_mention_detector_is_pure():
    # Vacuous until REQ-0028 creates the module (ADR-0013 fixes this path).
    banned = (
        "sqlite3",
        "httpx",
        "requests",
        "app.services",
        "app.intelligence.client",
        "app.deps",
    )
    files = [WORLD_MENTIONS] if WORLD_MENTIONS.exists() else []
    assert not _importers(files, banned)


def test_pat_arch_013_kind_is_a_reserved_server_meta_key():
    # T-6 (SPEC-0021): clients cannot set meta.kind; the server computes it at save time.
    assert "kind" in RESERVED_META_KEYS


SLASH_TEXT_SNIFF = re.compile(r"startsWith\(['\"]/['\"]\)")


def test_pat_arch_013_no_slash_text_sniffing():
    # T-21 (SPEC-0021): the frontend classifies messages by meta.kind, never by a leading '/'.
    # lib/slash.ts is the one exception: it parses the composer draft, not a message.
    frontend_src = ROOT / "frontend" / "src"
    allowed = frontend_src / "lib" / "slash.ts"
    offenders = [
        path.relative_to(ROOT).as_posix()
        for pattern in ("*.ts", "*.tsx")
        for path in sorted(frontend_src.rglob(pattern))
        if path != allowed and SLASH_TEXT_SNIFF.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"files sniff slash text (use meta.kind / replyIndex): {offenders}"


def _tool_modules():
    return [p for p in sorted(TOOLS.glob("*.py")) if not p.name.startswith("_")]


def _top_level_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in _parse(path).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


@pytest.mark.parametrize("path", _tool_modules(), ids=lambda p: p.name)
def test_pat_arch_004_tool_modules_follow_the_contract(path):
    assert {"NAME", "DESCRIPTION", "run"} <= _top_level_names(
        path
    ), "tool needs NAME, DESCRIPTION and run()"
    bad_imports = _importers([path], ("sqlite3", "app.services.repos", "app.deps"))
    assert not bad_imports, "tools never touch the store directly"
    source = path.read_text(encoding="utf-8")
    assert "dnd_data" not in source, "tools read context['reference'], never dnd_data/"
    assert "app/reference" not in source, "tools read context['reference'], never the JSON files"


def test_pat_arch_008_migration_ladder_is_contiguous_and_additive():
    ladder = None
    for node in _parse(REPOS).body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and target.id == "_MIGRATIONS":
            ladder = ast.literal_eval(node.value)
    assert ladder, "_MIGRATIONS ladder not found"
    assert [step[0] for step in ladder] == list(range(2, 2 + len(ladder)))
    for _, table, column, ddl in ladder:
        if column is None:
            assert ddl.startswith(f"CREATE TABLE IF NOT EXISTS {table} (")
        else:
            assert ddl.upper().startswith(f"ALTER TABLE {table} ADD COLUMN {column}".upper())
    assert ladder[1][:3] == (3, "world_entities", None)


# Doc budgets: keep agent-read documents small. Older files are grandfathered.
SPEC_BUDGET_BYTES = 20_000
ADR_BUDGET_BYTES = 10_000
SPEC_FIRST_BUDGETED = 15
ADR_FIRST_BUDGETED = 10


def _numbered(directory: Path, prefix: str, first: int):
    for path in sorted(directory.glob(f"{prefix}*.md")):
        number = path.name.removeprefix(prefix).split("-")[0]
        if number.isdigit() and int(number) >= first:
            yield path


def test_new_specs_stay_within_budget():
    big = {
        p.name: p.stat().st_size
        for p in _numbered(ROOT / "docs" / "specs", "SPEC-", SPEC_FIRST_BUDGETED)
        if p.stat().st_size > SPEC_BUDGET_BYTES
    }
    assert not big, f"specs over {SPEC_BUDGET_BYTES} bytes (split or trim): {big}"


def test_new_adrs_stay_within_budget():
    big = {
        p.name: p.stat().st_size
        for p in _numbered(ROOT / "docs" / "adr", "", ADR_FIRST_BUDGETED)
        if p.stat().st_size > ADR_BUDGET_BYTES
    }
    assert not big, f"ADRs over {ADR_BUDGET_BYTES} bytes (use the lite template): {big}"
