---
id: ADR-0015
status: accepted
date: 2026-11-08
requirement: REQ-0035
supersedes: null
superseded_by: null
---

# Narrative vs admin messages: server-owned `meta.kind` set at creation, `narrative_only` stored on the user message, filter in the pure chat builder

## Context
REQ-0035 (`docs/requirements/LOG.md`). Patterns opened: PAT-ARCH-003, PAT-ARCH-010; others from the INDEX.

| Fact | Where |
|---|---|
| No kind column on `messages`; ladder head is v5 | `app/services/repos.py` `_MIGRATIONS` |
| Tool replies carry server-owned `meta.tool`; chat replies do not | `inference_service._worker_loop`, `_append_reply` |
| The user's slash row has no stored tool signal, only `/` text | `messages.submit_user_message`, `tool_handler.detect_tool` |
| The client already sniffs `content.startsWith('/')` and `meta.tool === 'roll'` | `frontend/src/components/NarrativeLog.tsx` |
| History = completed canon user/assistant rows, last `max_turns`; tool rows included | `prompt_builders.build_chat_messages` |
| Prompt is built at run time from the store; regenerate and restart re-enqueue the stored user row | PAT-ARCH-003 rule 5, `messages.regenerate_reply` |
| Mining already splits tools: chat and `/narrate` only | `inference_service` guard, PAT-ARCH-012 |
| The client posts via WS `user_message` (`meta: None`); REST meta is client-settable minus `RESERVED_META_KEYS` | `app/api/v1/ws.py`, `messages.py` |

| Trigger | Fired | Fact |
|---|---|---|
| Two viable approaches | yes | D1 meta key vs column; D2 flag scope |
| Accepted-pattern change | yes (additive) | PAT-ARCH-003 rule 2 gains a kind filter |
| Cross-cutting convention | yes | every reader classifies by a stored field, never by text |
| Hard to reverse / new dependency | no | D1-A needs no migration, no package |

## Decision Drivers
Scores 1-5; High 3, Medium 2, Low 1 (`docs/constraints.md`). Max 90.

| Dimension | W | Why |
|---|---|---|
| Simplicity, Reversibility, Maintainability | 3 each | standing |
| Reuse, Fun/learning | 2 each | standing |
| Performance, Security | 1 each | standing, de-prioritised |
| Requirement fit (added) | 3 | MUSTs: stored per message, not inferred from text; owner decisions applied |

## Considered Options
D1, classification storage:
- **D1-A** Server-owned `meta.kind` (`MessageKind` StrEnum: narrative/admin) set at creation on the user row (`submit_user_message`) and the reply (worker); `kind` joins `RESERVED_META_KEYS`.
- **D1-B** Nullable `messages.kind` column (ladder v6), top-level `kind` on `MessageResp`.
- **D1-C** Derive at read time from `meta.tool` and the `/` prefix.

D2, narrative-only flag:
- **D2-A** Optional `narrative_only` on WS `user_message` and `MessageCreateReq`, stored as reserved `meta.narrative_only` on that user row; the worker reads it from the current row.
- **D2-B** Flag only on the in-memory job (new `enqueue` parameter).
- **D2-C** Persisted per session (`sessions` column v6 + PATCH route).

D3, where history is filtered:
- **D3-A** Server: `build_chat_messages` skips admin rows when the flag is set.
- **D3-B** Client: toggle marks admin rows not canon.

## Rubric Scoring
Order: Simp, Rev, Maint (x3); Reuse, Fun (x2); Perf, Sec (x1); Fit (x3).

| Option | Scores and one-line facts | Total |
|---|---|---|
| D1-A | 5 one reserved key, two write sites, no migration; 5 inert key; 4 sits with server-owned `tool`/`reply_to`, untyped in OpenAPI; 4 reuses reserved-key strip and meta merge; 3; 4; 4 clients cannot set it; 5 stored at write time | **79** |
| D1-B | 3 ladder tuple, old-file test, mapper, insert, `MessageResp`, OpenAPI, TS type; 4 one-way `user_version` bump on `dnd.db`; 5 typed like `canon`; 5 PAT-ARCH-008 as designed; 3; 4; 4; 5 | 75 |
| D1-C | 4 no writes; 5 nothing stored; 2 tool map duplicated in Python and TS; 4 `meta.tool` exists; 2; 4; 4; 1 user slash rows have only `/` text, which the MUST forbids | 56 |
| D2-A | 4 one field on two inputs, one reserved key; 5 inert key; 4 regenerate/restart replay the same context; 5 enqueue and regenerate paths unchanged; 3; 4; 4 set only from a typed field; 5 toggle stays a client choice | **78** |
| D2-B | 3 `InferenceService.enqueue` Protocol change plus fakes; 5; 3 regenerate and restart requeue drop the flag; 3 against PAT-ARCH-003 rule 5; 3; 4; 4; 4 | 65 |
| D2-C | 2 v6 step, session route and model, OpenAPI, client fetch; 3 one-way bump; 4 single source; 4 ladder/PATCH precedent; 3; 4; 4; 2 makes the toggle per-session, owner chose per-browser | 55 |
| D3-A | 5 one kwarg, one condition; 5; 5 one pure function, literal-dict tests; 5 `_inject_world` inherits the built list; 3; 4; 4; 5 backend MUST met directly | **84** |
| D3-B | 3 N PATCHes per toggle; 2 rewrites stored canon, undo must remember which; 1 conflates kind with canon (PAT-ARCH-010); 3; 2; 3; 4; 1 admin rows leave context only by abusing canon | 38 |

## Decision Outcome
**D1-A (79) + D2-A (78) + D3-A (84).** ADR-0011 chose a column for `canon` because the
operator mutates it via PATCH; `kind` is write-once and server-owned like `meta.tool`, so a
ladder step buys only typing. Traded away: a typed top-level `kind` in OpenAPI and
server-side memory of the toggle.

The spec must implement:
1. `message_kind(tool_name)` beside `detect_tool`: `None` and names in one `NARRATIVE_TOOLS`
   frozenset are narrative; any other name (unknown, future, help, failed) is admin. Owner
   decision: `NARRATIVE_TOOLS = {"narrate","attack","roll"}`; `rules`, `monster` are admin.
   Call sites: `submit_user_message` (classifies the command syntax once, at write time) and
   the worker. World mining stays on `{"narrate"}` only (PAT-ARCH-012 unchanged); its guard
   MUST NOT reuse `NARRATIVE_TOOLS`, so `/roll` and `/attack` replies are not mined.
2. Regenerate refreshes `meta.kind` with `meta.tool`. Missing `kind` (older rows) = narrative.
3. Readers (builder, client) use `meta.kind` only; the client drops its `/`-prefix sniff.
4. `narrative_only` is optional, default false; WS doc and OpenAPI updated (PAT-ARCH-005).
5. The builder filters only when the current user row has `meta.narrative_only` true, and
   before the `max_turns` slice so admin rows do not crowd out narrative turns. Canon
   filtering is unchanged and independent.
6. Client: one collapsible admin card per command (command row + reply via `meta.reply_to`),
   expanded by default, collapse state per card in component state, not saved; the toggle
   persists in `localStorage` only, hides admin cards and is sent on every `user_message`.
   `/roll` and `/attack` show a compact command echo; the diary omits admin entries and roll
   results.
7. Tests: builder with literal dicts (flag on/off, missing kind, canon interplay); submit and
   worker set `kind`; client-sent `kind`/`narrative_only` meta is stripped; frontend
   `npm run build` plus a manual checklist.

## Consequences
- Positive: no migration, no Protocol change; classification lives in one set; regenerate
  replays the same context.
- Negative: `kind` values are documented in the WS doc, not in the OpenAPI schema.
- Risk: existing rows lack `kind`, so old tool output stays narrative (bubbles, in context).
  Owner decision: no backfill; old rows count as narrative.

## Pattern Impact
- Creates **PAT-ARCH-013** (accepted): message kind is a server-owned meta key set at
  creation; readers never classify by text.
- **Amendment to PAT-ARCH-003 rule 2 (owner-approved, applied in SPEC-0021 WP-7):** append
  "When the current user message has `meta.narrative_only` true, prior messages with
  `meta.kind` admin are also skipped, before the `max_turns` slice (ADR-0015)."
- **Amendment to PAT-ARCH-004 rule 3 (owner-approved, applied in WP-7):** replies also
  carry `meta.kind` (PAT-ARCH-013).
- Uses PAT-ARCH-005, PAT-ARCH-010 and PAT-ARCH-012 unchanged (mining stays narrate-only).
