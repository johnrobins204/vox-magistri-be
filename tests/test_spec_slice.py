import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("spec_slice", ROOT / "scripts" / "spec_slice.py")
slicer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(slicer)

SAMPLE = """---
id: SPEC-9999
---

# Title

## 1. Requirement
long copied requirement

## 2. Test Spec
intro line

### WP-1: one
test one
### WP-2: two
test two

## 3. Work Packages
### WP-1: one
body one
### WP-2: two
body two

## 4. Other Details
risks
"""


def test_slice_keeps_only_the_requested_package():
    out = slicer.build_slice(SAMPLE, "WP-2")
    assert "id: SPEC-9999" in out and "intro line" in out
    assert "test two" in out and "body two" in out
    for dropped in ("test one", "body one", "long copied requirement", "risks"):
        assert dropped not in out


def test_unknown_package_is_an_error():
    with pytest.raises(SystemExit):
        slicer.build_slice(SAMPLE, "WP-9")


def test_list_titles():
    assert slicer.list_packages(SAMPLE) == "WP-1: one\nWP-2: two"


def test_every_spec_package_can_be_sliced_and_is_smaller_than_the_spec():
    for path in sorted((ROOT / "docs" / "specs").glob("SPEC-*.md")):
        text = path.read_text(encoding="utf-8")
        titles = slicer.list_packages(text)
        for title in filter(None, titles.split("\n")):
            wp = title.split(":")[0]
            assert len(slicer.build_slice(text, wp)) < len(text), (path.name, wp)
