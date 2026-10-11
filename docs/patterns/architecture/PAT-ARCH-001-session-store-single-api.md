---
id: PAT-ARCH-001
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# One session store API; transports are thin adapters

## Problem
Two session models grew side by side: REST used uuid sessions and the `SessionStore`
Protocol, while WebSocket and `/intel` used integer run ids through a wrapper that probed
the store with `hasattr` and silently fell back to a private in-memory repo. Entries
were never persisted and snapshots were always empty, with no error anywhere.

## Context
Applies to every transport (REST, WebSocket, `/intel`) and every service that reads or
writes conversation state. Does not cover the choice of persistence backend (that is a
separate decision, REQ-0005) or the WS streaming protocol (REQ-0007).

## Solution
1. A session id is a uuid string everywhere (`str(uuid4())`, created via
   `POST /api/v1/sessions`). No integer ids; route params are named `session_id`.
2. The only API for session state is the `SessionStore` Protocol in
   `app/type_defs.py`, obtained from `get_session_store()` in `app/deps.py`. A new
   backend implements the Protocol; callers do not change.
3. Transports (REST routers, WS handler, `/intel` snapshot) are thin adapters: they
   validate input, call the store and `inference.enqueue(...)`, and serialize the
   result. They do not own conversation logic or hold their own store.
4. Writing a user message goes through one shared function used by REST and WS (create
   the message, apply `client_message_id` idempotency, enqueue). Replies are written
   only by the inference worker, as a separate `role='assistant'` message with
   `meta.reply_to` (REQ-0003). Transports read the reply back from the store.
5. A session "exists" iff `store.get_session(id) is not None`. Unknown id: REST/snapshot
   return 404; WS closes with 1008. Transports never auto-create sessions.
6. No silent fallbacks: do not probe the store with `hasattr`, and do not catch broad
   exceptions to switch to a private in-memory store. If the store lacks a method it
   is a bug and must fail loudly (logged via `get_logger`, per PAT-CODE-001).
7. Payloads sent over WS go through `fastapi.encoders.jsonable_encoder` because stored
   messages contain `datetime` values.

## Consequences
- One place to change when persistence arrives (the Protocol implementation).
- Adding capability means extending the one Protocol, not adding a parallel API; keep it
  small because every future backend must implement it.
- The in-memory store hands out live message dicts and the inference worker mutates
  them in place; backends that return copies must also provide update methods.
- Not thread-safe beyond what CPython guarantees.

## Examples
- `app/api/v1/session.py` (REST, the reference adapter) and `app/services/repos.py`
  (`InMemorySessionStore`).
- To be applied by REQ-0004 to `app/api/v1/ws.py` and `app/api/v1/intelligence.py`
  (see [ADR-0002](../../adr/0002-single-session-model.md)).
