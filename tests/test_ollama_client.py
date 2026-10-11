"""OllamaClient.chat / generate and the IntelligenceClient Protocol (SPEC-0006, T-01..T-06).

No network: httpx.post / httpx.get are monkeypatched; no sockets are opened.
"""

import httpx
import pytest

from app.intelligence.client import IntelligenceClient, IntelligenceError, OllamaClient

BASE_URL = "http://ollama.test:1"
CHAT_URL = f"{BASE_URL}/api/chat"


def _response(status: int, payload=None, text: str = "") -> httpx.Response:
    request = httpx.Request("POST", CHAT_URL)
    if payload is not None:
        return httpx.Response(status, json=payload, request=request)
    return httpx.Response(status, text=text, request=request)


class _FakeHttp:
    """Stands in for httpx.post / httpx.get. Records every POST; replies with one canned result."""

    def __init__(self):
        self.posts: list[dict] = []
        self.gets: list[str] = []
        self.reply: httpx.Response | None = None
        self.error: Exception | None = None

    def post(self, url, **kwargs):
        self.posts.append({"url": url, "json": kwargs["json"], "timeout": kwargs["timeout"]})
        if self.error is not None:
            raise self.error
        return self.reply

    def get(self, url, **kwargs):
        self.gets.append(url)
        return _response(200, payload={"models": [{"model": "m1"}]})


@pytest.fixture
def http(monkeypatch):
    fake = _FakeHttp()
    monkeypatch.setattr("app.intelligence.client.httpx.post", fake.post)
    monkeypatch.setattr("app.intelligence.client.httpx.get", fake.get)
    return fake


def _client() -> OllamaClient:
    return OllamaClient(BASE_URL, "m1", 7.0)


# T-01
def test_chat_sends_list_verbatim(http):
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a"},
    ]
    http.reply = _response(200, payload={"message": {"content": "pong"}})

    out = _client().chat(msgs)

    assert len(http.posts) == 1
    post = http.posts[0]
    assert post["url"] == CHAT_URL
    assert post["json"] == {"model": "m1", "messages": msgs, "stream": False}
    assert post["timeout"] == 7.0
    assert out == "pong"


# T-02
def test_chat_model_override(http):
    http.reply = _response(200, payload={"message": {"content": "pong"}})

    _client().chat([{"role": "user", "content": "x"}], model="m2")

    assert http.posts[0]["json"]["model"] == "m2"


# T-03
def test_generate_posts_single_user_message(http):
    http.reply = _response(200, payload={"message": {"content": "pong"}})

    out = _client().generate("hi")

    assert http.posts[0]["json"]["messages"] == [{"role": "user", "content": "hi"}]
    assert out == "pong"


def test_generate_model_override_is_posted(http):
    http.reply = _response(200, payload={"message": {"content": "pong"}})

    _client().generate("hi", model="m2")

    assert http.posts[0]["json"]["model"] == "m2"


def test_generate_delegates_to_chat_once(monkeypatch):
    client = _client()
    seen: list[tuple[tuple, dict]] = []

    def fake_chat(*args, **kwargs):
        seen.append((args, kwargs))
        return "delegated"

    monkeypatch.setattr(client, "chat", fake_chat)

    assert client.generate("hi", model="m2") == "delegated"
    assert seen == [(([{"role": "user", "content": "hi"}],), {"model": "m2"})]


# T-04
def test_chat_404_maps_to_model_not_found(http):
    http.reply = _response(404, text="no such model")

    with pytest.raises(IntelligenceError) as excinfo:
        _client().chat([{"role": "user", "content": "x"}])

    assert "model 'm1' not found" in str(excinfo.value)


def test_chat_500_maps_with_body_text(http):
    http.reply = _response(500, text="kaboom from server")

    with pytest.raises(IntelligenceError) as excinfo:
        _client().chat([{"role": "user", "content": "x"}])

    assert "kaboom from server" in str(excinfo.value)


# T-05
def test_chat_transport_error_maps_to_intelligence_error(http):
    http.error = httpx.ConnectError("connection refused")

    with pytest.raises(IntelligenceError):
        _client().chat([{"role": "user", "content": "x"}])


def test_chat_empty_content_maps_to_intelligence_error(http):
    http.reply = _response(200, payload={"message": {"content": ""}})

    with pytest.raises(IntelligenceError) as excinfo:
        _client().chat([{"role": "user", "content": "x"}])

    assert "empty response" in str(excinfo.value)


# T-06
def test_protocol_declares_chat_and_generate():
    assert hasattr(IntelligenceClient, "chat")
    assert hasattr(IntelligenceClient, "generate")


def test_ollama_client_has_chat_and_generate():
    assert callable(OllamaClient.chat)
    assert callable(OllamaClient.generate)
