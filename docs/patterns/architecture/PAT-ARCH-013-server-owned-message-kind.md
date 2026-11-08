---
id: PAT-ARCH-013
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# Message kind: a server-owned meta key set at creation; readers never classify by text

## Problem
The client and the chat builder need to tell narrative messages from admin (tool) output
(REQ-0035). Sniffing `content` (a leading `/`) or keeping per-tool lists in Python and
TypeScript drifts and breaks the requirement that classification is stored per message.

## Context
Applies to every message the server writes (user rows in `submit_user_message`, replies in the
worker) and to every reader that renders or filters by kind. Decided in
[ADR-0015](../../adr/0015-narrative-admin-message-kind.md). Not for `canon`, which is an
operator-mutable column (PAT-ARCH-010); kind is write-once.

## Solution
1. `meta.kind` is a `MessageKind` StrEnum value (`narrative` | `admin`, `app/type_defs.py`)
   and a reserved meta key (`RESERVED_META_KEYS`), so clients cannot set it.
2. It is computed once, at write time, by one helper beside `detect_tool`: tools in the
   single `NARRATIVE_TOOLS` set are narrative; every other tool name is admin, and so is no
   tool at all: plain chat is the admin side-chat (ADR-0017).
3. Both rows of a slash command (the user command and its reply) carry the same kind;
   regenerate refreshes it with `meta.tool`.
4. Readers use `meta.kind` only, never `content`; a missing key means narrative.
5. The narrative-only request flag is the reserved `meta.narrative_only` on the user row that
   triggers the call, so regenerate and restart replay the same context.

## Consequences
- No migration; values are documented in `docs/api/websocket.md`, not OpenAPI.
- Rows written before ADR-0015 are narrative; there is no backfill. Plain-chat rows written
  before ADR-0017 keep their stored kind (narrative).
- `NARRATIVE_TOOLS` is for classification only; world mining (PAT-ARCH-012) keeps its own
  narrate-only guard and MUST NOT reuse it.
- Mechanical checks (e.g. `kind` in `RESERVED_META_KEYS`, no `startsWith('/')` in
  `frontend/src`) are added to `tests/test_patterns.py` by the implementing spec; they would
  fail today.

## Examples
None yet. Planned for REQ-0035: `app/intelligence/tool_handler.py`, `app/services/messages.py`,
`app/services/inference_service.py`, `app/intelligence/prompt_builders.build_chat_messages`,
`frontend/src/components/NarrativeLog.tsx`.
