---
id: ADR-0016
status: accepted
date: 2026-11-08
requirement: REQ-0036
supersedes: null
superseded_by: null
---

# Entity mention marks: matched in the client at render time against the REST entity list; nothing stored

## Context
REQ-0036 (`docs/requirements/LOG.md`). Patterns opened: PAT-ARCH-012, PAT-ARCH-013; others from the INDEX.

| Fact | Where |
|---|---|
| Detector returns matched entity ids and new candidates, no character offsets | `app/intelligence/world_mentions.detect_mentions` |
| Known-name match = casefolded `[a-z0-9]+` token sequence of name or alias, first hit only | `world_mentions._tokens`, `_known_labels` |
| Only `pending` rows get `evidence.message_ids` bumps (cap 20); canon and manual rows get none | `app/services/world_mining.mine_reply` |
| Mining runs after the user row is `completed`; WS sends reply + `done` once it sees `completed` | `inference_service._worker_loop`, `app/api/v1/ws._await_reply` |
| `GET /api/v1/world/entities?session_id=` returns `{entities:[{id,name,aliases,kind,status,evidence,...}]}`, global rows included | `app/api/v1/world.py`, `app/schemas/world.py`, `repos.list_entities` |
| Statuses: canon, pending, rejected | `app/type_defs.EntityStatus` |
| No entity client, no entity UI, no frontend test runner | `frontend/src/lib/api.ts`, `frontend/package.json` |
| Narrative text renders as one plain `<p>` in `Bubble`; admin/roll rows use other components | `frontend/src/components/NarrativeLog.tsx` |
| PAT-ARCH-012 rule 6 restricts logs only; names are already served by REST | PAT-ARCH-012, `WorldEntityResp` |

| Trigger | Fired | Fact |
|---|---|---|
| Two viable approaches | yes | client match vs server spans (stored or on read) |
| Cross-cutting convention | yes | first client-derived decoration; a server option would add a reserved meta key |
| Accepted-pattern change / hard to reverse / new dependency | no (for the chosen option) | frontend-only, nothing persisted |

## Decision Drivers
Scores 1-5; High 3, Medium 2, Low 1 (`docs/constraints.md`). Max 90.

| Dimension | W | Why |
|---|---|---|
| Simplicity, Reversibility, Maintainability | 3 each | standing |
| Reuse, Fun/learning | 2 each | standing |
| Performance, Security | 1 each | standing, de-prioritised |
| Requirement fit (added) | 3 | MUSTs (mark spans, text untouched, rejected never) plus the owner's "past entities" |

## Considered Options
- **D1 span source.** A: client matches name+aliases from the REST list over each rendered narrative bubble. A2: as A, only in messages listed in `evidence.message_ids`. B: worker stores spans in a new reserved reply meta key. C: new read route computes spans server-side per session. D: do nothing.
- **D2 boxed statuses.** S1 canon only. S2 pending+canon, pending dashed, canon solid. S3 pending+canon, one style.
- **D3 animation.** N1 one pulse, then no mark. N2 box draws in once on mount, then a static outline. N3 looping animation.
- **D4 hover/click.** H1 none. H2 native `title` (name, kind, status). H3 click popover with notes/evidence.
- **D5 backfill.** B1 render-time matching covers old messages; no re-mining. B2 also re-run detection over history to propose rows.

## Rubric Scoring
Order: Simp, Rev, Maint (x3); Reuse, Fun (x2); Perf, Sec (x1); Fit (x3).

| Option | Scores and one-line facts | Total |
|---|---|---|
| D1-A | 5 api.ts fn, one pure TS matcher, Bubble, index.css, App fetch; no backend/OpenAPI; 5 nothing stored; 3 match rule copied into TS, manual check only; 4 existing route/envelope; 4; 4 entities x 6 visible turns; 5 no new exposure, no logs; 4 every occurrence, edits reflected, old messages covered | **76** |
| D1-A2 | 4 extra evidence filter; 5; 3; 4; 4; 4; 5; 2 canon/manual rows never bumped, 20 cap, nothing before mining | 67 |
| D1-B | 1 detector emits no offsets, new post-`completed` meta write, reserved key, client refetch (reply already sent); 2 persisted keys, backfill needs re-mining; 2 stale after corrections edit (not re-mined); 3 extends PAT-ARCH-012/013; 3; 5; 5; 3 exact at write time, no backfill | 46 |
| D1-C | 3 route, schema, OpenAPI regen, offset fn, pytest, same client work; 4 additive route; 4 one Python matcher; 4 PAT-ARCH-005; 3; 3 rescans session per call; 5; 5 same tokenizer as detector | 70 |
| D1-D | 5; 5; 5; 3; 1; 5; 5; 1 fails the MUST (excluded) | 66 |
| D2-S1 | 5; 5; 5; 4; 3; 5; 5; 2 no approval UI, detector rows stay pending, few boxes | 75 |
| D2-S2 | 4 one extra class; 5; 5; 4; 4; 5; 5; 5 detector output visible, unreviewed distinct, rejected excluded | **83** |
| D2-S3 | 5; 5; 5; 4; 3; 5; 5; 3 false positives look like canon | 78 |
| D3-N1 | 5; 5; 5; 4 existing `@keyframes pulse`; 3; 5; 5; 2 mark vanishes, owner wants past entities shown | 75 |
| D3-N2 | 4 one keyframe, reduced-motion = static; 5; 5; 4; 4; 5; 5; 5 animated and persistent | **83** |
| D3-N3 | 4; 5; 4; 4; 4; 3 constant repaints; 5; 3 distracting in a 6-turn log | 72 |
| D4-H1 | 5; 5; 5; 3; 2; 5; 5; 3 nothing says what is marked | 74 |
| D4-H2 | 5 one attribute; 5; 5; 4 browser tooltip; 3; 5; 5; 4 identifies the entity | **81** |
| D4-H3 | 2 new component, no entity UI to reuse; 4; 3; 2; 5; 5; 5; 4 would show raw evidence snippets to children | 63 |
| D5-B1 | 5 free with D1-A; 5; 5; 5; 3; 4; 5; 4 entities only named before mining existed stay unknown | **82** |
| D5-B2 | 2 script plus writes; 2 new rows in `dnd.db`; 3; 3; 3; 3; 5; 5 | 56 |

## Decision Outcome
**D1-A (76) + D2-S2 (83) + D3-N2 (83) + D4-H2 (81) + D5-B1 (82).** C ties the matcher to
the detector's Python and adds tests, but costs a route, schema and OpenAPI drift step for a
display-only feature; B is costly and goes stale after edits. Traded away: one match rule
in two languages without an automated frontend test.

The spec must implement:
1. `getWorldEntities(sessionId)` in `api.ts`; fetch on session load and after each WS
   `done`. Failure = plain text, no banner. A row proposed by the latest reply may appear
   one refresh late (mining finishes after `completed`).
2. One pure matcher in `frontend/src/lib/`: labels = name + aliases of non-rejected rows;
   tokens = lowercase `[a-z0-9]+` runs (mirrors `world_mentions._tokens`); tokens joined by
   any non-alphanumeric run; alphanumeric boundaries; case-insensitive; every occurrence;
   overlaps go to the longest, then earliest, match. Returns segments, not HTML.
3. `Bubble` view text renders segments as React text and `<span>` marks (no
   `dangerouslySetInnerHTML`); the edit box and stored text stay raw. Not applied to admin
   cards, roll cards, command echoes or the diary.
4. CSS in `index.css`: canon solid and pending dashed outline, one draw-in keyframe on
   mount, static under `prefers-reduced-motion`. `title` = name, kind and status.
5. No backend change, no meta key, no names in `console` output. Verification:
   `npm run build` plus a manual checklist (canon, pending, rejected, alias, possessive,
   edit, old message, reduced motion).

## Consequences
- Positive: frontend-only and fully reversible; old messages and edits handled for free.
- Negative: the TS matcher can drift from `world_mentions._tokens`; recorded in PAT-ARCH-014.
- Risk: a short common name (e.g. an entity named "Bob") is marked everywhere it appears.

## Pattern Impact
- Creates **PAT-ARCH-014** (accepted): display-only text marks derived in the client from
  REST read models; never stored in content or meta; mirrored match rules cite their source.
- Uses PAT-ARCH-012 and PAT-ARCH-013 unchanged (rule 5 limits prompt injection, not display;
  no new meta key).
