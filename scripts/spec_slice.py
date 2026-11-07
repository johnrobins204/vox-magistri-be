#!/usr/bin/env python3
"""Print only the slice of a spec one work package needs.

    python scripts/spec_slice.py SPEC-0014 --list
    python scripts/spec_slice.py SPEC-0014 WP-3

The slice is: front matter, title, the Test Spec intro, that package's Test Spec
entries, and the package itself. It omits the Requirement and Other Details sections.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SPECS = Path(__file__).resolve().parent.parent / "docs" / "specs"
WP_HEADING = re.compile(r"^### (WP-\d+)\b")
SECTION_HEADING = re.compile(r"^## (\d+)\.")


def find_spec(spec_id: str) -> Path:
    matches = sorted(SPECS.glob(f"{spec_id}-*.md"))
    if len(matches) != 1:
        raise SystemExit(f"error: {spec_id} matches {len(matches)} spec files")
    return matches[0]


def split_sections(lines: list[str]) -> dict[str, list[str]]:
    """Map '' (preamble) and each section number to its lines."""
    sections: dict[str, list[str]] = {"": []}
    current = ""
    for line in lines:
        match = SECTION_HEADING.match(line)
        if match:
            current = match.group(1)
            sections[current] = []
        sections[current].append(line)
    return sections


def split_packages(lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """Return (lines before the first WP heading, {wp id: lines})."""
    intro: list[str] = []
    packages: dict[str, list[str]] = {}
    current: list[str] = intro
    for line in lines:
        match = WP_HEADING.match(line)
        if match:
            current = packages.setdefault(match.group(1), [])
        current.append(line)
    return intro, packages


def build_slice(text: str, wp: str) -> str:
    sections = split_sections(text.split("\n"))
    test_intro, test_by_wp = split_packages(sections.get("2", []))
    _, work_by_wp = split_packages(sections.get("3", []))
    if wp not in work_by_wp:
        raise SystemExit(f"error: {wp} not found; have {', '.join(work_by_wp) or 'none'}")
    parts = [sections[""], test_intro, test_by_wp.get(wp, []), ["## Work Package"], work_by_wp[wp]]
    return "\n".join("\n".join(part).strip("\n") for part in parts if part) + "\n"


def list_packages(text: str) -> str:
    sections = split_sections(text.split("\n"))
    _, work = split_packages(sections.get("3", []))
    return "\n".join(lines[0].removeprefix("### ")[:110] for lines in work.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_id", help="e.g. SPEC-0014")
    parser.add_argument("wp", nargs="?", help="e.g. WP-3")
    parser.add_argument("--list", action="store_true", help="list work package titles")
    args = parser.parse_args(argv)
    text = find_spec(args.spec_id).read_text(encoding="utf-8")
    if args.list or not args.wp:
        print(list_packages(text))
    else:
        sys.stdout.write(build_slice(text, args.wp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
