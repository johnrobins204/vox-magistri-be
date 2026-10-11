import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKLOG = ROOT / ".github" / "BACKLOG.json"
REQ_LOG = ROOT / "docs" / "requirements" / "LOG.md"

STATUSES = {"backlog", "in_progress", "completed", "blocked"}
TASK_PREFIX = re.compile(r"^\[(PENDING|IN_PROGRESS|COMPLETE)\] ")
ITEM_KEYS = {
    "id",
    "title",
    "status",
    "created_at",
    "updated_at",
    "adr_id",
    "spec_path",
    "tasks",
    "follow_ups",
}


def _items():
    data = json.loads(BACKLOG.read_text())
    assert data["version"] == "1.0"
    return data["items"]


def test_backlog_items_match_schema():
    for item in _items():
        assert set(item) == ITEM_KEYS, item.get("id")
        assert re.fullmatch(r"REQ-\d{4}", item["id"])
        assert item["status"] in STATUSES
        assert all(TASK_PREFIX.match(t) for t in item["tasks"])
        if item["spec_path"]:
            assert (ROOT / item["spec_path"]).is_file()


def test_every_logged_requirement_is_in_backlog():
    logged = set(re.findall(r"^\| (REQ-\d{4}) \|", REQ_LOG.read_text(), re.M))
    assert logged <= {item["id"] for item in _items()}
