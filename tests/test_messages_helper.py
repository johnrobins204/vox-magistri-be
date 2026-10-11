import uuid

from app.services.messages import build_snapshot, submit_user_message
from app.services.repos import InMemorySessionStore
from tests.session_helpers import FakeInference


def _store_with_session(session_id: str = "s1") -> InMemorySessionStore:
    store = InMemorySessionStore()
    store.create_session(session_id)
    return store


def _payload(content: str = "hi", client_message_id=None) -> dict:
    return {
        "client_message_id": client_message_id,
        "role": "user",
        "content": content,
        "meta": None,
    }


def test_submit_creates_user_message_and_enqueues():
    store = _store_with_session("s1")
    inference = FakeInference()

    msg, created, queued = submit_user_message(
        store=store, inference=inference, session_id="s1", payload=_payload("hi")
    )

    assert created is True
    assert queued is True
    assert msg["role"] == "user"
    assert msg["content"] == "hi"
    uuid.UUID(msg["id"])
    stored = store.list_messages("s1")
    assert len(stored) == 1
    assert stored[0]["id"] == msg["id"]
    assert len(inference.calls) == 1
    call = inference.calls[0]
    assert call["session_id"] == "s1"
    assert call["message_id"] == msg["id"]
    assert call["prompt"] == "hi"
    assert call["store"] is store


def test_submit_idempotent_on_client_message_id():
    store = _store_with_session("s1")
    inference = FakeInference()
    payload = _payload("hi", client_message_id="c1")

    m1, created1, queued1 = submit_user_message(
        store=store, inference=inference, session_id="s1", payload=payload
    )
    m2, created2, queued2 = submit_user_message(
        store=store, inference=inference, session_id="s1", payload=payload
    )

    assert (created1, queued1) == (True, True)
    assert (created2, queued2) == (False, False)
    assert m2["id"] == m1["id"]
    assert len(store.list_messages("s1")) == 1
    assert len(inference.calls) == 1


def test_submit_reports_queue_full():
    store = _store_with_session("s1")
    inference = FakeInference(accept=False)

    msg, created, queued = submit_user_message(
        store=store, inference=inference, session_id="s1", payload=_payload("hi")
    )

    assert created is True
    assert queued is False
    stored_ids = [m["id"] for m in store.list_messages("s1")]
    assert stored_ids == [msg["id"]]


def test_build_snapshot_returns_copies():
    store = _store_with_session("s1")
    store.create_message("s1", "u1", {"role": "user", "content": "hello", "meta": {"k": "v"}})

    snap = build_snapshot(store, "s1")

    assert snap["session_id"] == "s1"
    assert len(snap["entries"]) == 1
    assert isinstance(snap["snapshot_at"], float)

    snap["entries"][0]["content"] = "changed"
    snap["entries"][0]["meta"]["k"] = "changed"
    snap["entries"].append({})

    stored = store.list_messages("s1")
    assert len(stored) == 1
    assert stored[0]["content"] == "hello"
    assert stored[0]["meta"]["k"] == "v"


def test_build_snapshot_unknown_session_is_none():
    store = _store_with_session("s1")

    assert build_snapshot(store, "nope") is None
    assert build_snapshot(store, "1") is None
    assert store.get_session("nope") is None
