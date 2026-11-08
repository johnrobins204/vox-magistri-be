---
id: PAT-ARCH-014
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# Display-only text marks: derived in the client at render time from REST read models; never stored

## Problem
The client wants to decorate message text with facts the server already exposes (REQ-0036:
world entity names). Storing spans in message meta goes stale after corrections, needs a
backfill, and adds post-write mutation of rows the client has already received.

## Context
Applies to purely visual highlighting of message text from data served by an existing GET
route. Does not apply to anything the server must act on (classification is PAT-ARCH-013,
prompt input is PAT-ARCH-003/012). Decided in
[ADR-0016](../../adr/0016-entity-mention-marks-client-side.md).

## Solution
1. Fetch the read model from its existing route; on failure render plain text.
2. One pure matcher function in `frontend/src/lib/` returns text segments; components render
   them as React text and elements, never as HTML strings.
3. Stored `content` and `meta` are never changed; edit boxes show raw content.
4. A match rule that mirrors a server rule names its source in a comment (for entity marks:
   `app/intelligence/world_mentions._tokens`); change both together.
5. Names and matched text are never written to `console` output (mirrors PAT-ARCH-012 rule 6).

## Consequences
- Old messages and edits are covered without migration; nothing to back out.
- Mirrored rules can drift; the frontend has no test runner, so the spec's manual checklist
  carries the match cases.

## Examples
None yet. Planned for REQ-0036: `frontend/src/lib/api.ts`, a matcher in `frontend/src/lib/`,
`frontend/src/components/NarrativeLog.tsx` (`Bubble`), `frontend/src/index.css`.
