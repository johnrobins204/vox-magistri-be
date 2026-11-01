from app.services import inference_service as inf
from tests.session_helpers import make_stub_service


def test_enqueue_returns_false_when_queue_full(monkeypatch, session_store):
    svc = make_stub_service()
    try:
        # Stop the worker from draining, then shrink the queue to one slot.
        svc._shutdown_flag.set()
        svc._worker.join(timeout=2)
        svc._queue = inf.Queue(maxsize=1)

        session_store.create_session("s1")
        for mid in ("m1", "m2"):
            session_store.create_message("s1", mid, {"content": "x"})
        assert svc.enqueue(session_id="s1", message_id="m1", prompt="x", store=session_store)
        assert not svc.enqueue(session_id="s1", message_id="m2", prompt="x", store=session_store)

        m2 = [m for m in session_store.list_messages("s1") if m["id"] == "m2"][0]
        assert m2["status"] == "error"
        assert svc.queue_position("m1") == 0
        assert svc.queue_position("missing") is None
    finally:
        svc._shutdown_flag.set()
