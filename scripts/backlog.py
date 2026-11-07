#!/usr/bin/env python3
"""Deterministic editor for .github/BACKLOG.json and docs/requirements/LOG.md.

Agents call this instead of reading or rewriting the (large) files by hand.
Run `python scripts/backlog.py --help` for the commands. Output is deliberately terse.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKLOG = ROOT / ".github" / "BACKLOG.json"
REQ_LOG = ROOT / "docs" / "requirements" / "LOG.md"

STATUSES = ("backlog", "in_progress", "completed", "blocked")
TASK_STATES = ("PENDING", "IN_PROGRESS", "COMPLETE")
DEFAULT_TASKS = [
    "[COMPLETE] Restate requirement",
    "[IN_PROGRESS] Architecture review",
    "[PENDING] Spec drafting",
    "[PENDING] Implementation",
]
LOG_STATUS = {"completed": "done"}
LOG_ROW = re.compile(r"^\| (REQ-\d{4}) \|")
LOG_TAIL = re.compile(r"\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|$")


class BacklogError(Exception):
    pass


def _load() -> dict:
    return json.loads(BACKLOG.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    BACKLOG.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _item(data: dict, req_id: str) -> dict:
    for item in data["items"]:
        if item["id"] == req_id:
            return item
    raise BacklogError(f"unknown id {req_id}")


def _log_lines() -> list[str]:
    return REQ_LOG.read_text(encoding="utf-8").split("\n")


def _log_seg(value: str) -> str:
    return f"| {value} " if value else "| "


def _update_log_row(req_id: str, adr=None, spec=None, status=None) -> None:
    lines = _log_lines()
    for idx, line in enumerate(lines):
        if not line.startswith(f"| {req_id} |"):
            continue
        match = LOG_TAIL.search(line)
        if not match:
            raise BacklogError(f"cannot parse LOG row for {req_id}")
        cur_adr, cur_spec, cur_status = match.groups()
        new = (
            adr if adr is not None else cur_adr,
            spec if spec is not None else cur_spec,
            LOG_STATUS.get(status, status) if status is not None else cur_status,
        )
        lines[idx] = line[: match.start()] + "".join(_log_seg(v) for v in new) + "|"
        REQ_LOG.write_text("\n".join(lines), encoding="utf-8")
        return
    raise BacklogError(f"{req_id} has no LOG row")


def next_id() -> str:
    data = _load()
    ids = [int(i["id"][4:]) for i in data["items"]]
    ids += [int(m.group(1)[4:]) for m in map(LOG_ROW.match, _log_lines()) if m]
    return f"REQ-{max(ids, default=0) + 1:04d}"


def add(title: str, restatement: str, req_id: str | None = None) -> str:
    req_id = req_id or next_id()
    data = _load()
    if any(i["id"] == req_id for i in data["items"]):
        raise BacklogError(f"{req_id} already exists")
    today = date.today().isoformat()
    data["items"].append(
        {
            "id": req_id,
            "title": title,
            "status": "in_progress",
            "created_at": today,
            "updated_at": today,
            "adr_id": None,
            "spec_path": None,
            "tasks": list(DEFAULT_TASKS),
            "follow_ups": [],
        }
    )
    _save(data)
    text = _log_lines()
    while text and not text[-1]:
        text.pop()
    cell = restatement.replace("\n", " ").replace("|", "/")
    text.append(f"| {req_id} | {today} | {cell} | | | in_progress |")
    REQ_LOG.write_text("\n".join(text), encoding="utf-8")
    return req_id


def set_fields(req_id: str, status=None, adr=None, spec=None) -> None:
    if status is not None and status not in STATUSES:
        raise BacklogError(f"status must be one of {STATUSES}")
    data = _load()
    item = _item(data, req_id)
    if status is not None:
        item["status"] = status
    if adr is not None:
        item["adr_id"] = adr or None
    if spec is not None:
        if spec and not (ROOT / spec).is_file():
            raise BacklogError(f"spec path not found: {spec}")
        item["spec_path"] = spec or None
    item["updated_at"] = date.today().isoformat()
    _save(data)
    _update_log_row(req_id, adr=adr, spec=spec, status=status)


def set_task(req_id: str, needle: str, state: str, note: str | None = None) -> str:
    if state not in TASK_STATES:
        raise BacklogError(f"state must be one of {TASK_STATES}")
    data = _load()
    item = _item(data, req_id)
    hits = [i for i, t in enumerate(item["tasks"]) if needle.lower() in t.lower()]
    if len(hits) != 1:
        raise BacklogError(f"'{needle}' matches {len(hits)} tasks; need exactly 1")
    body = re.sub(r"^\[[A-Z_]+\] ", "", item["tasks"][hits[0]])
    item["tasks"][hits[0]] = f"[{state}] {note if note is not None else body}"
    item["updated_at"] = date.today().isoformat()
    _save(data)
    return item["tasks"][hits[0]]


def add_task(req_id: str, text: str) -> None:
    data = _load()
    item = _item(data, req_id)
    if not re.match(r"^\[(PENDING|IN_PROGRESS|COMPLETE)\] ", text):
        text = f"[PENDING] {text}"
    item["tasks"].append(text)
    item["updated_at"] = date.today().isoformat()
    _save(data)


def add_followup(req_id: str, text: str) -> None:
    data = _load()
    _item(data, req_id)["follow_ups"].append(text)
    _item(data, req_id)["updated_at"] = date.today().isoformat()
    _save(data)


def show(req_id: str) -> str:
    item = _item(_load(), req_id)
    out = [f"{item['id']} [{item['status']}] {item['title']}"]
    out.append(f"adr={item['adr_id']} spec={item['spec_path']} updated={item['updated_at']}")
    out += [f"  {t[:160]}" for t in item["tasks"]]
    out += [f"  follow-up: {f[:160]}" for f in item["follow_ups"]]
    return "\n".join(out)


def list_items(status: str | None = None) -> str:
    rows = [i for i in _load()["items"] if status in (None, i["status"])]
    return "\n".join(f"{i['id']} {i['status']:<11} {i['title'][:90]}" for i in rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("next-id", help="print the next free REQ id")
    p = sub.add_parser("list", help="one line per item")
    p.add_argument("--status", choices=STATUSES)
    p = sub.add_parser("show", help="terse view of one item")
    p.add_argument("req_id")
    p = sub.add_parser("add", help="create backlog item + LOG row (in_progress)")
    p.add_argument("--title", required=True)
    p.add_argument("--restatement", required=True, help="RFC 2119 restatement, one line")
    p.add_argument("--id", dest="req_id")
    p = sub.add_parser("set", help="set status / ADR id / spec path (LOG row kept in sync)")
    p.add_argument("req_id")
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--adr", help="e.g. ADR-0010; empty string clears")
    p.add_argument("--spec", help="repo-relative spec path; empty string clears")
    p = sub.add_parser("task", help="change one task's state by unique substring")
    p.add_argument("req_id")
    p.add_argument("needle")
    p.add_argument("state", choices=TASK_STATES)
    p.add_argument("--note", help="replace the task text")
    p = sub.add_parser("add-task", help="append a task (defaults to [PENDING])")
    p.add_argument("req_id")
    p.add_argument("text")
    p = sub.add_parser("followup", help="append a follow-up")
    p.add_argument("req_id")
    p.add_argument("text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "next-id":
            print(next_id())
        elif args.cmd == "list":
            print(list_items(args.status))
        elif args.cmd == "show":
            print(show(args.req_id))
        elif args.cmd == "add":
            print(add(args.title, args.restatement, args.req_id))
        elif args.cmd == "set":
            set_fields(args.req_id, args.status, args.adr, args.spec)
            print("ok")
        elif args.cmd == "task":
            print(set_task(args.req_id, args.needle, args.state, args.note))
        elif args.cmd == "add-task":
            add_task(args.req_id, args.text)
            print("ok")
        elif args.cmd == "followup":
            add_followup(args.req_id, args.text)
            print("ok")
    except BacklogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
