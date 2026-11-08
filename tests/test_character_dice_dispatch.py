"""Character-aware dice end to end through the production graph (SPEC-0017 WP-4, REQ-0022)."""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.factory import create_app
from app.services.build_services import build_services
from app.services.repos import make_default_repos
from tests.session_helpers import AUTH, wait_idle

ARIA = {
    "name": "ARIA",
    "abilities": {"STR": 12, "DEX": 16, "CON": 13, "INT": 11, "WIS": 15, "CHA": 10},
}


class ScriptedRng:
    """Scripted random source: randint(1, sides) pops the next scripted value."""

    def __init__(self, values):
        self._values = list(values)
        self.calls = []

    def randint(self, a, b):
        assert a == 1
        self.calls.append((a, b))
        return self._values.pop(0)


@contextmanager
def _dice_env(monkeypatch, character, values):
    """Production composition behind the real app; session s1 with `character`; chat is a stub."""
    repos = make_default_repos()
    store = repos["session"]
    store.create_session("s1", character=deepcopy(character))
    services = build_services(repos, enable_tool_discovery=True)
    services["tool"].default_context["rng"] = ScriptedRng(values)
    svc = services["inference"]
    chat_calls: list[list[dict]] = []

    def _chat(messages, **kw):
        chat_calls.append(messages)
        return "stub reply"

    monkeypatch.setattr(svc.client, "chat", _chat)
    app = create_app(services=services)
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client, svc=svc, store=store, chat_calls=chat_calls, services=services
        )
    asyncio.run(svc.shutdown())
    store.close()


def _post(env, content: str):
    resp = env.client.post("/api/v1/sessions/s1/messages", json={"content": content}, headers=AUTH)
    assert resp.status_code == 202
    wait_idle(env.svc)
    return env.store.list_messages("s1")


# SPEC-0017 T-4.2: /attack over the real catalog, with the character read-only.
def test_attack_slash_command_creates_tool_reply(monkeypatch):
    with _dice_env(monkeypatch, ARIA, [14, 3]) as env:
        msgs = _post(env, "/attack Dagger vs 12")
        stored = env.store.get_character("s1")

    user, reply = msgs
    assert user["role"] == "user"
    assert user["status"] == "completed"
    assert reply["role"] == "assistant"
    assert reply["meta"]["tool"] == "attack"
    assert reply["meta"]["reply_to"] == user["id"]
    assert env.chat_calls == []
    assert stored == ARIA


# SPEC-0017 T-4.3: /roll with an ability term, end to end.
def test_roll_ability_term_slash_command_creates_tool_reply(monkeypatch):
    with _dice_env(monkeypatch, ARIA, [14]) as env:
        msgs = _post(env, "/roll 1d20+dex")

    reply = msgs[1]
    assert reply["content"] == "1d20+dex: [14] + DEX(+3) = 17"
    assert reply["meta"]["tool"] == "roll"
    assert env.chat_calls == []


# SPEC-0017 T-4.4: no character on the session marks the message error; the worker survives.
def test_character_tools_without_character_error_and_worker_survives(monkeypatch):
    with _dice_env(monkeypatch, None, [4]) as env:
        attack_msgs = _post(env, "/attack Dagger")
        roll_msgs = _post(env, "/roll dex")
        ok_msgs = _post(env, "/roll 1d6")

    assert attack_msgs[0]["status"] == "error"
    assert "No character" in attack_msgs[0]["meta"]["error"]
    assert roll_msgs[1]["status"] == "error"
    assert "No character" in roll_msgs[1]["meta"]["error"]
    assert ok_msgs[-1]["role"] == "assistant"
    assert ok_msgs[-1]["content"] == "1d6: [4] = 4"
    assert env.chat_calls == []


# SPEC-0017 T-4.5: unknown weapon is a user error; /attack help completes with usage text.
def test_attack_unknown_weapon_and_help(monkeypatch):
    with _dice_env(monkeypatch, ARIA, []) as env:
        bad_msgs = _post(env, "/attack nonsense")
        help_msgs = _post(env, "/attack help")

    assert bad_msgs[0]["status"] == "error"
    assert (
        bad_msgs[0]["meta"]["error"]
        == 'Unknown weapon "nonsense". Check the spelling or use a more exact name.'
    )
    user, reply = help_msgs[1], help_msgs[2]
    assert user["status"] == "completed"
    assert reply["meta"]["tool"] == "attack"
    assert "proficiency" in reply["content"]
    assert env.chat_calls == []
