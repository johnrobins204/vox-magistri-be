---
id: PAT-ARCH-005
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# HTTP/WS API contract: FastAPI defaults, explicit models, UTC at the edge, a checked-in OpenAPI snapshot

## Problem
The JSON contract grew without a convention. Error bodies came in three shapes: FastAPI's
`{"detail"}`, an ad-hoc 429 body, and `ToolInvokeResp` with `error`. Some routes had no
`response_model`. A pagination model was defined but never used. Schema docs used a status
vocabulary the code never emits. Naive datetimes went out without an offset. REST and WS
enforced different input limits. Nothing recorded the contract, so a frontend author had to
read Python to learn it, and nothing noticed when it changed.

## Context
This pattern applies to every route under `/api/v1/...` (REST and `/intel`) and to every
WebSocket event. It builds on [PAT-ARCH-001](./PAT-ARCH-001-session-store-single-api.md):
transports are thin adapters, and WS payloads go through `jsonable_encoder`. It keeps
[PAT-ARCH-002](./PAT-ARCH-002-stdlib-sqlite-store.md) and ADR-0003 as they are: storage stays
naive-UTC ISO TEXT. It was decided in [ADR-0005](../../adr/0005-frontend-ready-api-contract.md)
(REQ-0010).

It does not cover token streaming (REQ-0007), auth/CORS (REQ-0009), or global handling of
unexpected 500s.

## Solution
1. **Errors use FastAPI's default body.** Raise `HTTPException(status, detail="<human-readable
   string>")`. Do not return error bodies with `JSONResponse` and do not add error fields to
   success models. Request-validation failures keep FastAPI's 422 `{"detail": [{loc, msg,
   type, ...}]}`. Document error responses on routes with `responses={404: {"model":
   ErrorResp}, ...}`, where `ErrorResp` is `{detail: str}`.
2. **Every route declares its response model.** A collection endpoint returns an object with
   a named plural key, such as `{"messages": [...]}` or `{"sessions": [...]}`, never a bare
   list. Add pagination fields such as `next_cursor` only when pagination exists. Adding a
   field later does not break clients.
3. **Shared vocabularies live in `app/type_defs.py` as `StrEnum`s,** for example
   `MessageStatus`. Schemas, services and transports import them from there. A member is equal
   to its string, so stored TEXT and the Protocol's `status: str` do not change. Docstrings
   must not restate a vocabulary.
4. **Datetimes are aware UTC at the API edge only.** The store keeps naive-UTC values (ADR-0003).
   Schemas type every datetime field as `UtcDatetime` (`Annotated[datetime,
   AfterValidator(...)]`, which attaches `UTC` to naive values). The JSON output is ISO 8601
   with offset 0. WS events serialize message and snapshot payloads through the same pydantic
   models (`Model.model_validate(d).model_dump(mode="json")`) before `ws_send`. That way REST,
   `/intel` and WS emit identical item shapes and timestamps.
5. **Input limits are defined once,** as a module constant next to the shared write helper
   (`app/services/messages.py`). The helper enforces the limit for every transport. Schema
   `Field` constraints reference the same constant so the limit appears in OpenAPI. Schema
   constraints must not depend on settings, so the OpenAPI document stays deterministic.
6. **Use pydantic v2 idioms only:** `model_config = ConfigDict(...)`,
   `json_schema_extra={"examples": [...]}`, `model_dump()`, and `model_validate()`. Do not use
   `class Config`, `orm_mode`, `schema_extra`, `.dict()` or `constr`. Add
   `from_attributes=True` only when a model is really built from objects. The store returns
   dicts.
7. **The contract is checked in.** `docs/api/openapi.json` is generated from
   `app.openapi()` (stdlib `json`, `indent=2`, `sort_keys=True`, trailing newline).
   `tests/test_openapi_snapshot.py` fails when the live schema differs from the file. Regenerate
   it with one command, `UPDATE_OPENAPI_SNAPSHOT=1 ./venv-dnd-server/bin/python -m pytest
   tests/test_openapi_snapshot.py`. WS events, which OpenAPI cannot describe, are documented in
   `docs/api/websocket.md` and refer to OpenAPI component names (`MessageResp`). Any contract
   change updates both files in the same change.

## Consequences
- No custom exception handlers. `app/factory.py` is not touched, so its deprecated `on_event`
  hooks are left for REQ-0012.
- The frontend switches on HTTP status and shows `detail`. There is no machine-readable
  error `code`. If one is needed later, adding `code` next to `detail` does not break clients.
- 422 is the one place where `detail` is a list, not a string. This is FastAPI's documented
  `HTTPValidationError`, and it appears in OpenAPI automatically.
- Unhandled exceptions still produce Starlette's plain-text 500. A global handler is out of
  scope.
- Every contract change produces an `openapi.json` diff. That diff is the review signal.

## Examples
None yet. Planned for REQ-0010 (ADR-0005): `app/schemas/v1.py` (`UtcDatetime`, `ErrorResp`,
`MessageListResp`, `SessionResp`, `SessionListResp`), `app/type_defs.py` (`MessageStatus`),
`app/services/messages.py` (`MAX_MESSAGE_CHARS`), `docs/api/openapi.json`,
`docs/api/websocket.md`, `tests/test_openapi_snapshot.py`.
