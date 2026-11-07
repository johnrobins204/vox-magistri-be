import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("backlog_cli", ROOT / "scripts" / "backlog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    backlog = tmp_path / "BACKLOG.json"
    log = tmp_path / "LOG.md"
    shutil.copy(mod.BACKLOG, backlog)
    shutil.copy(mod.REQ_LOG, log)
    monkeypatch.setattr(mod, "BACKLOG", backlog)
    monkeypatch.setattr(mod, "REQ_LOG", log)
    return mod


def test_real_backlog_round_trips_byte_for_byte(cli):
    before = cli.BACKLOG.read_text()
    cli._save(cli._load())
    assert cli.BACKLOG.read_text() == before


def test_add_creates_item_and_log_row(cli):
    new_id = cli.next_id()
    assert cli.add("Title", "The app MUST x | y.") == new_id
    item = cli._item(cli._load(), new_id)
    assert item["status"] == "in_progress" and len(item["tasks"]) == 4
    assert f"| {new_id} |" in cli.REQ_LOG.read_text()
    assert cli.next_id() != new_id


def test_set_syncs_log_row(cli):
    new_id = cli.add("T", "R")
    cli.set_fields(new_id, status="completed", adr="ADR-0099", spec="docs/specs/TEMPLATE.md")
    item = cli._item(cli._load(), new_id)
    assert (item["status"], item["adr_id"], item["spec_path"]) == (
        "completed",
        "ADR-0099",
        "docs/specs/TEMPLATE.md",
    )
    row = next(
        line for line in cli.REQ_LOG.read_text().split("\n") if line.startswith(f"| {new_id} ")
    )
    assert row.endswith("| ADR-0099 | docs/specs/TEMPLATE.md | done |")


def test_set_rejects_missing_spec_and_bad_status(cli):
    new_id = cli.add("T", "R")
    with pytest.raises(cli.BacklogError):
        cli.set_fields(new_id, spec="docs/specs/nope.md")
    with pytest.raises(cli.BacklogError):
        cli.set_fields(new_id, status="finished")


def test_task_needs_unique_match_and_keeps_text(cli):
    new_id = cli.add("T", "R")
    assert cli.set_task(new_id, "architecture", "COMPLETE") == "[COMPLETE] Architecture review"
    with pytest.raises(cli.BacklogError):
        cli.set_task(new_id, "e", "COMPLETE")
    with pytest.raises(cli.BacklogError):
        cli.set_task(new_id, "no such task", "COMPLETE")


def test_followup_and_add_task(cli):
    new_id = cli.add("T", "R")
    cli.add_followup(new_id, "later")
    cli.add_task(new_id, "do more")
    item = cli._item(cli._load(), new_id)
    assert item["follow_ups"] == ["later"] and item["tasks"][-1] == "[PENDING] do more"


def test_main_reports_errors_with_exit_code(cli, capsys):
    assert cli.main(["show", "REQ-9999"]) == 1
    assert "unknown id" in capsys.readouterr().err
    assert cli.main(["list"]) == 0
    json.loads(cli.BACKLOG.read_text())
