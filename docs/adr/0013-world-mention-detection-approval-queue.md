---
id: ADR-0013
status: accepted
date: 2026-11-07
requirement: REQ-0028
supersedes: null
superseded_by: null
---

# World mention detection: a fail-soft step in the worker after the reply is completed, pending candidates in `world_entities` with a v5 `evidence` JSON column

## Context
REQ-0028 (`docs/requirements/LOG.md`). Patterns opened: PAT-ARCH-010; others from the INDEX.

| Fact | Where |
|---|---|
| `world_entities` has name, aliases JSON, notes, status (default canon), nullable session_id; no provenance column; ladder head v4 | `repos.py` `_MIGRATIONS` |
| Only `status == "canon"` is injected; `_entity_line` renders kind, name, aliases, notes | `prompt_builders.select_world_entities`, `_entity_line` |
| `session_id` is not editable after create | `repos.py` `_ENTITY_EDITABLE` |
| List filters by status/kind and PATCH sets status already exist | `app/api/v1/world.py` |
| One FIFO worker; reply visible once the user message is `completed`; WS polls for that | `_worker_loop`; `ws.py` `_wait_for_terminal` |
| An exception in the job `try` marks the user message `error` | `_worker_loop` |
| Regenerate revises the same reply id in place; `canon` is on every message dict | `_append_reply`, PAT-ARCH-010 |
| Tool replies carry `meta.tool`; catalogs (species, weapons, rules, creatures) are in memory | `_worker_loop`, `build_services.py` |

| Trigger | Fired | Fact |
|---|---|---|
| Hard to reverse / core schema | partly | v5 bumps `user_version` on the owner's `dnd.db`; additive |
| Cross-cutting | yes | first post-reply step in the shared worker |
| Two viable approaches | yes | placement (D1) and evidence storage (D2) |
| New dependency / accepted-pattern deviation | no | stdlib `re`; PAT-ARCH-010 rule 5 is honoured |

## Decision Drivers
Scores 1-5; High 3, Medium 2, Low 1 (`docs/constraints.md`).

| Dimension | W | Why |
|---|---|---|
| Simplicity, Reversibility, Maintainability | 3 each | solo part-time; real `dnd.db` |
| Reuse, Fun/learning | 2 each | standing |
| Performance, Security | 1 each | standing, de-prioritised |
| Reply isolation (D1 only) | 3 | MUST not delay or fail a reply |
| Forward compat REQ-0029/0030 (D2 only) | 2 | UI queue and LLM proposals reuse the record |
| Prompt hygiene (D2 only) | 3 | provenance must never reach the narrator |

## Considered Options
- D1 placement: **P1** inline in the worker after `completed`, own try; **P2** separate detector thread + queue; **P3** operator-triggered scan route.
- D2 evidence: **E1** text in `notes` (no schema change); **E2** v5 nullable `evidence TEXT` JSON column; **E3** new `world_mentions` table.

## Rubric Scoring
D1 (max 90). Order: Simp, Rev, Maint, Reuse, Fun, Perf, Sec, Isolation.

| Opt | Scores with reasons | Total |
|---|---|---|
| P1 | 5 one method like `_inject_world`; 5 delete one call; 5 one thread, existing worker tests; 5 mirrors `_inject_world` fail-soft; 3 plain; 4 ms of regex delay the next job only; 3; 4 runs after `completed`, own try | **80** |
| P2 | 2 second Queue, thread, shutdown join; 4; 2 tests must wait on a 2nd thread; 3 copies `_worker_loop`; 4 concurrency practice; 5 no next-job delay; 3; 5 fully decoupled | 61 |
| P3 | 3 route plus "already mined" state; 4; 3 extra state; 2 new route shape; 3; 3; 3; 2 breaks "after each reply" | 52 |

D2 (max 100). Order: Simp, Rev, Maint, Reuse, Fun, Perf, Sec, Fwd, Hygiene.

| Opt | Scores with reasons | Total |
|---|---|---|
| E1 | 5 no ladder step; 4 free text hard to strip later; 3 operator must clean notes on approve; 4 existing field; 2; 3; 3; 2 no structured count/source, collides with LLM notes; 1 ids and raw snippets injected via `_entity_line` once canon | 61 |
| E2 | 4 one column step, JSON like `aliases`; 4 additive nullable, ignorable; 4 one object; 5 PAT-ARCH-008 column step + PAT-ARCH-002 JSON TEXT; 3; 3; 3; 5 `detector` field lets slice C write `llm`; 5 `_entity_line` never reads it | **83** |
| E3 | 2 table step, 2-3 store methods, delete cleanup (no cascade); 4; 2 more Protocol surface; 4 table step exists; 4; 3; 3; 4 full history, more than needed; 5 | 69 |

## Decision Outcome
**P1 + E2.** Traded away: a few ms per reply added to the next job's start (P2), and a per-mention history table (E3).

| # | Decision |
|---|---|
| D1 | `_detect_mentions(job, reply_id, text)` is called on the worker thread after the user message is set `completed` and after `job.completed` is logged (ETA unaffected), for chat replies and for `/narrate` replies (human sign-off 2026-11-07: story text is where new NPCs and places appear); never for other slash tools (`/roll`, `/attack`, `/rules`, `/monster`). Own `try/except` -> `world.detect_failed` warning; never touches message status. Skipped when the world store is None, the switch is off, or the reply's `canon` is False. |
| D2 | v5: `ALTER TABLE world_entities ADD COLUMN evidence TEXT` (NULL for manual rows). JSON: `detector` (`deterministic`), `session_id`, `source_message_id`, `snippet` (sentence, <=160 chars), `first_seen_at`, `message_ids` (distinct, <=20; mention count = length). Store create/update accept `evidence`; `WorldEntityResp.evidence: dict | None` read-only; not in create/PATCH requests. OpenAPI regenerated. |
| D3 | Pure stdlib module `app/intelligence/world_mentions.py`. Known match: casefold + `[a-z0-9]+` (the selector's rule), contiguous whole-token match of name or any alias, against all statuses visible to the session (`list_entities(session_id)`). |
| D4 | New candidates: runs of 1-4 Capitalised words, lowercase `of`/`the` allowed inside; single words >= 3 chars and dropped when only seen sentence-initially. Stoplist: small built-in set (pronouns, days, God/Gods...), the session character's name tokens, catalog names (species, weapons, rules, creatures, built once in `build_services`). Suppressed if equal to or inside any known name/alias of any status, so a rejected name is never re-proposed (deleting the row forgets it). Cap per reply. No quoted-name rule. |
| D5 | Kind: title word first (Lord, Lady, Sir, Captain, King, Queen, Master, Mistress, Elder, Brother, Sister) -> `npc`; else `other`. Operator sets kind on approval via PATCH. |
| D6 | Known mentions: a pending entity re-mentioned in another reply gets that reply id appended to `message_ids` (regenerate keeps the same id, so idempotent). Canon/rejected rows are not written (no `updated_at` churn in selector ranking). Revised-away or retconned sources: candidate left for the operator. |
| D7 | Scope: candidates are created campaign-wide (`session_id` NULL); source session is kept in `evidence`. Reason: `session_id` is not editable, and a session-scoped approval would vanish next session (ADR-0010 D1). Pending rows are never injected, so no cross-session prompt leak. |
| D8 | API: none new. Queue = `GET /api/v1/world/entities?status=pending`; approve/reject = existing PATCH. No bulk route, WS event or snapshot count (REQ-0029 may ask). |
| D9 | Settings (world): `detect_mentions` bool default true; `max_candidates_per_reply` int default 3, `ge=0` (0 = match only). Log `world.detected` counts only (matched, proposed, bumped, duration_ms). |
| D10 | Tests: pure detector unit tests; worker tests with stub inference and `:memory:` store (tool reply, non-canon, exception -> still `completed`, regenerate idempotent, rejected not re-proposed, pending not injected); v5 old-file-DB test. Playtest: script runs the pure detector over canon non-tool replies in a temp COPY of `dnd.db` (read-only, ~80 messages), owner labels candidates; keep default-on only if precision >= 50% and <= 1.5 candidates per reply, else tune stoplist/cap first. |

## Consequences
- Positive: no new thread, route or dependency; queue works through Swagger today; slice C reuses `evidence` and the pending flow.
- Negative: v5 cannot be downgraded; heuristic will produce false positives; output of other slash tools (`/roll`, `/attack`, `/rules`, `/monster`) is not mined.
- Risks: duplicate candidate if the operator creates the same name mid-detection (single worker, accepted); stoplist needs playtest tuning.

## Pattern Impact
- Creates PAT-ARCH-012 (accepted 2026-11-07): post-reply world mining in the worker, with a purity check in `tests/test_patterns.py`.
- Uses PAT-ARCH-002, 003, 005, 008, 010 unchanged. No accepted pattern is modified.
