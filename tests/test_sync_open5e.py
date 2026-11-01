"""SPEC-0012 WP-1: open5e sync script, paging, retry, atomic writes and manifest.

No test touches the network. Every HTTP call goes through an httpx.MockTransport.
"""

import importlib.util
import json
import socket
from datetime import datetime
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_open5e.py"

_spec = importlib.util.spec_from_file_location("sync_open5e", SCRIPT)
sync_open5e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_open5e)

BASE = sync_open5e.BASE_URL
HTML_BODY = "<!doctype html><html><body>docs</body></html>"
HTML_HEADERS = {"content-type": "text/html; charset=utf-8"}
ALL_NAMES = {
    "armor",
    "backgrounds",
    "classes",
    "conditions",
    "creatures",
    "feats",
    "magicitems",
    "rules",
    "sections",
    "species",
    "spells",
    "weapons",
}


class FakeOpen5e:
    """Serves paged v2 responses. `queued` maps a full URL to statuses returned first."""

    def __init__(self, pages: dict[str, list[list[dict]]], documents: list[dict] | None = None):
        self.pages = pages
        self.documents = documents if documents is not None else [_doc("srd-2024")]
        self.queued: dict[str, list[int | str]] = {}
        self.calls: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        if self.queued.get(url):
            item = self.queued[url].pop(0)
            if item == "html":
                return httpx.Response(200, text=HTML_BODY, headers=HTML_HEADERS)
            return httpx.Response(item)
        path = request.url.path
        if path == "/v2/documents/":
            return httpx.Response(200, json=_page(self.documents, None))
        name = path.strip("/").split("/")[1]
        pages = self.pages[name]
        number = int(request.url.params.get("page", "1"))
        next_url = f"{BASE}{path}?page={number + 1}" if number < len(pages) else None
        return httpx.Response(200, json=_page(pages[number - 1], next_url))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


def _page(results: list[dict], next_url: str | None) -> dict:
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


def _doc(key: str) -> dict:
    return {
        "key": key,
        "name": f"Document {key}",
        "display_name": f"Display {key}",
        "publisher": {"name": "Wizards of the Coast", "key": "wotc"},
        "gamesystem": {"name": "5e", "key": "5e"},
        "permalink": f"https://example.invalid/{key}",
        "license": "CC-BY-4.0",
    }


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(sync_open5e.time, "sleep", lambda _s: None)


@pytest.fixture
def block_sockets(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("real network connection attempted")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def test_t01_endpoints_are_the_twelve_datasets():
    assert set(sync_open5e.ENDPOINTS) == ALL_NAMES


def test_t02_paging_follows_absolute_next_url(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"conditions"}))
    pages = {
        "conditions": [
            [{"key": "a5e-ag_a", "name": "A"}, {"key": "srd-2024_b", "name": "B"}],
            [{"key": "srd-2024_c", "name": "C"}],
        ]
    }
    fake = FakeOpen5e(pages)

    sync_open5e.sync(tmp_path, transport=fake.transport())

    written = json.loads((tmp_path / "conditions.json").read_text(encoding="utf-8"))
    assert [r["name"] for r in written] == ["A", "B", "C"]
    assert f"{BASE}/v2/conditions/?page=2" in fake.calls


def test_t03_manifest_has_one_record_per_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"conditions", "species"}))
    fake = FakeOpen5e(
        {
            "conditions": [[{"name": "A"}, {"name": "B"}], [{"name": "C"}]],
            "species": [[{"name": "Elf"}]],
        }
    )

    sync_open5e.sync(tmp_path, transport=fake.transport())

    manifest = json.loads((tmp_path / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.0"
    assert datetime.fromisoformat(manifest["synced_at"]).tzinfo is not None
    by_file = {record["file"]: record for record in manifest["files"]}
    assert set(by_file) == {"conditions.json", "species.json", "_documents.json"}
    for dataset, file_name in (("conditions", "conditions.json"), ("species", "species.json")):
        record = by_file[file_name]
        assert record["dataset"] == dataset
        assert record["endpoint"] == f"{BASE}/v2/{dataset}/"
        assert datetime.fromisoformat(record["fetched_at"]).tzinfo is not None
        actual = json.loads((tmp_path / file_name).read_text(encoding="utf-8"))
        assert record["count"] == len(actual)
    assert by_file["conditions.json"]["count"] == 3


def test_t04_documents_keep_metadata_verbatim(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset())
    doc = _doc("srd-2014")
    fake = FakeOpen5e({}, documents=[doc])

    sync_open5e.sync(tmp_path, transport=fake.transport())

    documents = json.loads((tmp_path / "_documents.json").read_text(encoding="utf-8"))
    assert documents == [doc]
    for field in ("key", "name", "publisher", "gamesystem", "permalink", "license"):
        assert field in documents[0]


def test_t05_retries_429_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"conditions"}))
    fake = FakeOpen5e({"conditions": [[{"name": "A"}]]})
    fake.queued[f"{BASE}/v2/conditions/?limit=50"] = [429]

    sync_open5e.sync(tmp_path, transport=fake.transport())

    assert fake.calls.count(f"{BASE}/v2/conditions/?limit=50") == 2
    assert (tmp_path / "conditions.json").exists()


def test_t05_three_5xx_raise_sync_error(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"conditions"}))
    fake = FakeOpen5e({"conditions": [[{"name": "A"}]]})
    url = f"{BASE}/v2/conditions/?limit=50"
    fake.queued[url] = [500, 502, 503]

    with pytest.raises(sync_open5e.SyncError):
        sync_open5e.sync(tmp_path, transport=fake.transport())

    assert fake.calls.count(url) == 3
    assert not (tmp_path / "conditions.json").exists()


def test_t06_failed_page_leaves_previous_file_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"conditions"}))
    pages = {"conditions": [[{"name": "A"}], [{"name": "B"}]]}
    sync_open5e.sync(tmp_path, transport=FakeOpen5e(pages).transport())
    before = (tmp_path / "conditions.json").read_bytes()

    fresh = FakeOpen5e(pages)
    fresh.queued[f"{BASE}/v2/conditions/?page=2"] = [500, 500, 500]
    with pytest.raises(sync_open5e.SyncError):
        sync_open5e.sync(tmp_path, transport=fresh.transport())

    assert (tmp_path / "conditions.json").read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_t07_writes_stay_under_output_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"conditions"}))
    app_dir = ROOT / "app"
    before = sorted(p for p in app_dir.rglob("*") if p.is_file())
    fake = FakeOpen5e({"conditions": [[{"name": "A"}]]})

    sync_open5e.sync(tmp_path, transport=fake.transport())

    after = sorted(p for p in app_dir.rglob("*") if p.is_file())
    assert before == after
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert {"conditions.json", "_documents.json", "_manifest.json"} <= {p.name for p in written}
    manifest = json.loads((tmp_path / "_manifest.json").read_text(encoding="utf-8"))
    for record in manifest["files"]:
        assert (tmp_path / record["file"]).resolve().is_relative_to(tmp_path.resolve())


def test_t08_injected_transport_makes_no_real_connection(tmp_path, monkeypatch, block_sockets):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"conditions"}))
    fake = FakeOpen5e({"conditions": [[{"name": "A"}]]})

    result = sync_open5e.sync(tmp_path, transport=fake.transport())

    assert isinstance(result, dict)
    assert fake.calls


def test_t09_first_page_request_carries_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"conditions"}))
    fake = FakeOpen5e({"conditions": [[{"name": "A"}]]})

    sync_open5e.sync(tmp_path, transport=fake.transport())

    assert fake.calls[0] == f"{BASE}/v2/documents/?limit=50"
    assert f"{BASE}/v2/conditions/?limit=50" in fake.calls
    assert f"{BASE}/v2/conditions/" not in fake.calls


def test_t10_html_200_retries_then_sync_error_names_url_and_content_type(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"conditions"}))
    fake = FakeOpen5e({"conditions": [[{"name": "A"}]]})
    url = f"{BASE}/v2/conditions/?limit=50"
    fake.queued[url] = ["html"] * sync_open5e.MAX_ATTEMPTS

    with pytest.raises(sync_open5e.SyncError) as excinfo:
        sync_open5e.sync(tmp_path, transport=fake.transport())

    assert fake.calls.count(url) == sync_open5e.MAX_ATTEMPTS
    assert url in str(excinfo.value)
    assert "text/html" in str(excinfo.value)
    assert not (tmp_path / "conditions.json").exists()


def test_t11_html_200_once_then_json_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"conditions"}))
    fake = FakeOpen5e({"conditions": [[{"name": "A"}]]})
    url = f"{BASE}/v2/conditions/?limit=50"
    fake.queued[url] = ["html"]

    sync_open5e.sync(tmp_path, transport=fake.transport())

    assert fake.calls.count(url) == 2
    assert json.loads((tmp_path / "conditions.json").read_text(encoding="utf-8")) == [{"name": "A"}]


def test_t12_sections_come_from_v1_and_other_datasets_from_v2(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"sections", "species"}))
    fake = FakeOpen5e({"sections": [[{"name": "S"}]], "species": [[{"name": "Elf"}]]})

    sync_open5e.sync(tmp_path, transport=fake.transport())

    assert f"{BASE}/v1/sections/?limit=50" in fake.calls
    assert f"{BASE}/v2/species/?limit=50" in fake.calls
    assert not any("/v2/sections/" in call for call in fake.calls)
    manifest = json.loads((tmp_path / "_manifest.json").read_text(encoding="utf-8"))
    by_file = {record["file"]: record for record in manifest["files"]}
    assert by_file["sections.json"]["endpoint"] == f"{BASE}/v1/sections/"


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_t13_dataset_past_deadline_raises_sync_error_naming_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"magicitems"}))
    fake = FakeOpen5e({"magicitems": [[{"name": "A"}], [{"name": "B"}]]})
    clock = FakeClock()

    def trickling(request: httpx.Request) -> httpx.Response:
        if "/magicitems/" in str(request.url):
            clock.now += sync_open5e.DATASET_DEADLINE_SECONDS + 1
        return fake.handle(request)

    with pytest.raises(sync_open5e.SyncError, match="magicitems"):
        sync_open5e.sync(tmp_path, transport=httpx.MockTransport(trickling), clock=clock)

    assert not (tmp_path / "magicitems.json").exists()


def test_t14_dataset_within_deadline_is_not_cut_off(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_open5e, "ENDPOINTS", frozenset({"conditions"}))
    fake = FakeOpen5e({"conditions": [[{"name": "A"}], [{"name": "B"}]]})
    clock = FakeClock()

    def slow_but_ok(request: httpx.Request) -> httpx.Response:
        clock.now += sync_open5e.DATASET_DEADLINE_SECONDS / 3
        return fake.handle(request)

    sync_open5e.sync(tmp_path, transport=httpx.MockTransport(slow_but_ok), clock=clock)

    written = json.loads((tmp_path / "conditions.json").read_text(encoding="utf-8"))
    assert [r["name"] for r in written] == ["A", "B"]
