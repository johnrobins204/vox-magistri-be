---
id: ADR-0011
status: accepted
date: 2026-11-07
requirement: REQ-0027
supersedes: null
superseded_by: null
---

# Message corrections: a `canon` column on messages (ladder v4), edit and regenerate revise the reply in place with prior text kept in `meta.revisions`

## Context
REQ-0027 (`docs/requirements/LOG.md`). Patterns consulted: PAT-ARCH-001, 003, 005 (opened),
002/004/008 (INDEX summary and enforced rules only).

| Fact | Where |
|---|---|
| `messages` has `content`, `status`, `meta` JSON; no correction state | `app/services/repos.py` base schema; ladder head is v3 |
| The worker appends one `role='assistant'` reply per user message (`meta.reply_to`); the job, its status and the WS wait are keyed on the user message id | `inference_service.py` `_append_reply`, `_worker_loop`; `ws.py` `_find_reply` |
| History = completed user/assistant messages before the current id, last `max_turns`; world selection reads that same list | `prompt_builders.build_chat_messages`, `_inject_world` |
| Slash replies are stored exactly like chat replies plus `meta.tool` | `_worker_loop` tool branch |
| Clients may send meta; server keys are stripped via `RESERVED_META_KEYS` | `app/services/messages.py` |
| `MessageResp` declares fields explicitly, so REST drops undeclared keys; WS sends raw store dicts | `app/schemas/v1.py`, `ws.ws_send` |
| No world extraction exists yet (`extract` has no hits in `app/`) | grep |

| Trigger (`docs/adr/README.md`) | Fired | Fact |
|---|---|---|
| Hard to reverse | partly | a column step bumps `user_version` on the owner's `dnd.db` (never downgraded) |
| Deviates from accepted pattern | yes | PAT-ARCH-001 rule 4 (only the worker writes replies) and PAT-ARCH-003 rule 2 (history filter) |
| Two or more viable approaches | yes | canon in meta vs column; regenerate in place vs append-and-retcon |
| Cross-cutting convention | yes | every history consumer must now skip non-canon messages |
| New dependency | no | stdlib only |

## Decision Drivers
Scores 1-5; weights High 3, Medium 2, Low 1 (`docs/constraints.md`). Max 90.

| Dimension | W | Why it matters here |
|---|---|---|
| Simplicity / smallest edit | 3 | solo, part-time |
| Reversibility | 3 | the real `dnd.db` must keep working |
| Maintainability | 3 | one maintainer, a separate React client reads the contract |
| Reuse of patterns/deps | 2 | ladder, enqueue path and WS `entry`/`done` flow exist |
| Fun / learning | 2 | constraint 5 |
| Performance | 1 | household scale |
| Security | 1 | dev token only |
| Context integrity (added) | 3 | owner's top pain is the DM contradicting itself; a retcon must reliably leave the prompt and any later extraction |

## Considered Options
- **A. Meta only**: `meta.canon` + `meta.revisions`, regenerate revises the reply in place. No schema change.
- **B. `canon` column (v4) + `meta.revisions`, in-place regenerate**: `ALTER TABLE messages ADD COLUMN canon INTEGER DEFAULT 1` (nullable, NULL/1 = canon); prior texts in `meta.revisions`; a re-run of an answered user message updates its existing reply.
- **C. `canon` column + `message_revisions` table** (v4 + v5), in-place regenerate.
- **D. Append-and-retcon**: regenerate appends a second reply and marks the old one not canon (canon column).
- Status quo was rejected: it cannot satisfy any MUST in REQ-0027.

## Rubric Scoring
| Dim (W) | A | B | C | D |
|---|---|---|---|---|
| Simplicity (3) | 5: no migration, one new store write | 4: plus one ladder tuple, old-file test, one row-mapper line | 2: two steps, new table, join or extra read for snapshots | 3: `_find_reply` must pick the latest canon reply; out-of-order rows when an older reply is regenerated |
| Reversibility (3) | 5: inert meta keys if dropped | 4: column stays in `dnd.db` but is nullable and inert | 3: table plus column stay | 4: column stays; extra reply rows stay |
| Maintainability (3) | 3: canon hidden in a client-shared dict typed `dict[str, Any]` | 5: typed `canon: bool` on `MessageResp`, in OpenAPI, not settable through create payloads | 3: more SQL for display-only data | 3: "which reply is current" rule spread across ws, frontend, future extraction |
| Reuse (2) | 4: meta merge, enqueue path | 5: PAT-ARCH-008 column step as designed, enqueue path, `entry` upsert by id | 4: same plus a table step | 4: `_append_reply` unchanged |
| Fun (2) | 3 | 4: first column step on `messages` | 4 | 3 |
| Performance (1) | 4: Python filter | 4 | 4 | 4 |
| Security (1) | 3: needs `canon` added to reserved keys | 4: column unreachable from client meta | 4 | 4 |
| Context integrity (3) | 4: filter works; extraction must parse meta per row | 5: explicit field for builder and extraction | 5 | 3: breaks REQ-0003 one reply per user message; two writes per regenerate |
| **Weighted total** | **72** | **80** | **63** | **61** |

## Decision Outcome
**Option B (80/90).** It wins on maintainability and context integrity at the cost of
one additive ladder step. Traded away: A's zero-migration reversibility and C's
queryable revision history (revisions are display-only, so meta is enough).

Decisions the spec must implement:
1. **Canon**: v4 step adds `canon` to `messages`; the row mapper emits `canon: bool`
   (NULL counts as true); `MessageResp` gains `canon: bool = True`. Any message may be
   toggled; no cascade between a user message and its reply (the operator toggles each).
2. **History filter**: `build_chat_messages` also skips `canon` false. `_inject_world`
   inherits this because it reads the built list.
3. **Revisions**: one new `SessionStore` method updates `content` and/or `canon` in one
   transaction; a content change appends `{content, replaced_at, reason: edit|regenerate}`
   to `meta.revisions` (the original is `revisions[0]`). `revisions` joins
   `RESERVED_META_KEYS`. Nothing is ever deleted. Call sites: edit, canon toggle, worker.
4. **Edit**: assistant replies only (400 otherwise); 409 while its user message is
   queued or running. The prompt sees the edited `content`.
5. **Regenerate**: a shared helper in `app/services/messages.py` re-enqueues the
   reply's `meta.reply_to` user message with its own content. `_append_reply` becomes an
   upsert: if that user message already has a reply, revise it (refreshing `meta.tool`
   and tool meta) instead of creating one. The job id, statuses
   (queued/running/completed/error/cancelled) and the `InferenceService` Protocol are
   unchanged; `find_reply` moves to `messages.py` (worker and WS both use it). 409 if the
   user message is queued or running; 429 on a full queue as `post_message` does.
6. **REST (PAT-ARCH-005)**: `PATCH /api/v1/sessions/{session_id}/messages/{message_id}`
   with `{content?, canon?}` returns `MessageResp`; `POST .../messages/{message_id}/regenerate`
   (reply id) returns 202 shaped like `post_message`. Errors are `HTTPException` details.
7. **WS**: new action `regenerate` `{message_id}` reuses the `user_message` wait and emits
   the existing `entry` (same reply id, so the client upserts) and `done` events. Snapshot
   and `entry` carry `canon` and `meta.revisions` with no new event type.
8. **Frontend (in scope, minimal)**: the operator only uses the React app, and REST drops
   `canon` until types change. Add Edit/Regenerate on assistant replies, a canon toggle on
   every message, dimmed non-canon rows and an "edited" badge (`NarrativeLog.tsx`,
   `lib/api.ts`, `lib/ws.ts`). No hide-and-reveal or whispers.
9. **Tests**: `FakeInference`/stub client only: migration from a v3 file DB, builder
   filter, edit/canon/regenerate via REST and WS, failed regenerate keeps the old text.

## Consequences
- Positive: one reply per user message still holds; the WS client needs no new event types;
  later extraction gets one documented field to filter on.
- Negative: a failed or cancelled regenerate leaves the user message in `error`/`cancelled`,
  so that turn drops out of history until the operator regenerates again (old reply text kept).
- Risk accepted: regenerating `/roll` re-rolls; this is the operator's choice.
- `GET .../messages` still returns a bare list (existing PAT-ARCH-005 drift, not in scope).

## Pattern Impact
- Creates **PAT-ARCH-010** (accepted 2026-11-07): message corrections are non-destructive, history
  consumers filter `canon`.
- Uses PAT-ARCH-008 unchanged (nullable column step passes `test_pat_arch_008_*`) and PAT-ARCH-005.
- **Human sign-off given 2026-11-07, applied**: PAT-ARCH-001 rule 4 reads "replies are
  created and regenerated only by the worker; operator edits and canon changes go through
  one shared helper in `app/services/messages.py`"; PAT-ARCH-003 rule 2 adds
  "and `canon` is true".
