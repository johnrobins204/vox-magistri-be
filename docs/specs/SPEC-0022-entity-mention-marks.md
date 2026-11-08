---
id: SPEC-0022
requirement: REQ-0036
adr: ADR-0016
status: accepted
date: 2026-11-08
---

# Entity mention marks: bounding-box animation on known world entity names in chat messages

## 1. Requirement
REQ-0036; restatement in [`docs/requirements/LOG.md`](../requirements/LOG.md) (row REQ-0036). ADR:
[ADR-0016](../adr/0016-entity-mention-marks-client-side.md) (status **accepted**). Pattern:
[PAT-ARCH-014](../patterns/architecture/PAT-ARCH-014-client-derived-display-marks.md) (status **accepted**).

**Gate lifted: owner accepted ADR-0016 and PAT-ARCH-014.**

- Frontend only: no backend change, no new `meta` key, nothing stored, no backfill or re-detection (the stored message text is never altered).
- Source list: `GET /api/v1/world/entities?session_id=` (verified: bearer token required, global rows included, returns `{entities:[{id,name,aliases,kind,status,...}]}`); fetched on session load and after each WS `done`; failure = plain text, no banner.
- One pure matcher in `frontend/src/lib/mentions.ts` returns segments (never HTML); `Bubble` in `NarrativeLog.tsx` renders them as React text and `<span>`s. Not applied to admin cards, roll cards, command echoes, the diary or the edit box.
- Boxed statuses: `canon` solid, `pending` dashed; `rejected` never. One draw-in animation on mount, static under `prefers-reduced-motion`; native `title` = name, kind, status; click does nothing.
- Styles go in `frontend/src/index.css` (the only imported stylesheet; `App.css` is not imported).

## 2. Test Spec
No frontend test runner exists (`frontend/package.json` has none) and adding one is out of scope (open question 6), so
the matcher's pure logic cannot be unit-tested automatically. "Done" = `cd frontend && npm run build` passes (it runs
`tsc -b`) **plus** the manual checks below, in a browser against the running backend (`restart.sh`; frontend `npm run dev`).
Seed entities with `curl -X POST http://127.0.0.1:5000/api/v1/world/entities -H 'Authorization: Bearer dev' -H 'Content-Type: application/json' -d '{"name":"Bob","kind":"npc","aliases":["Bobby"],"status":"canon"}'`
(`status` may be `canon`, `pending` or `rejected`). Every test below is manual unless it says "build".

### WP-1
| ID | Exercises | Expected outcome | File |
|---|---|---|---|
| T1.1 | build | `npm run build` exits 0 with the new types and `getWorldEntities` | `frontend/src/lib/api.ts`, `frontend/src/types.ts` |
| T1.2 | route shape | `curl -H 'Authorization: Bearer dev' 'http://127.0.0.1:5000/api/v1/world/entities?session_id=x'` prints `{"entities":[...]}` | (no file; confirms the route the client calls) |

### WP-2
All cases: with entities as stated, `segmentText(text, entities)` returns the segments described. Cannot be run
automatically; check by reading the code and again through the browser checklist in WP-3.
| ID | Entities; text | Expected segments (marked part in brackets) |
|---|---|---|
| T2.1 | canon "Bob"; `Bob's sword` | `[Bob]` + `'s sword` |
| T2.2 | canon "Bob"; `BOB and bob` | `[BOB]` + ` and ` + `[bob]` (every occurrence, original case kept) |
| T2.3 | canon "Bob"; `Bobcat` and `xBob` | no mark (alphanumeric boundary) |
| T2.4 | canon "Silver Keep"; `silver-keep, Silver  Keep` | two marks (any non-alphanumeric run joins tokens) |
| T2.5 | canon "Bob", alias "Bobby"; `Bobby ran` | `[Bobby]` + ` ran`, mark carries the Bob entity |
| T2.6 | canon "Keep", canon "Silver Keep"; `the Silver Keep` | one mark `Silver Keep` (longest wins) |
| T2.7 | rejected "Bob"; `Bob` | one plain segment, no mark |
| T2.8 | label `!!!` (no tokens), `[]` entities, `''` text | no throw; one plain segment; joined segment text always equals the input exactly |

Target file for all: `frontend/src/lib/mentions.ts`.

### WP-3
| ID | Exercises | Expected outcome | File |
|---|---|---|---|
| T3.1 | build | `npm run build` exits 0 | `frontend/src/App.tsx`, `frontend/src/components/NarrativeLog.tsx` |
| T3.2 | canon + pending + rejected rows seeded, matching text in a DM reply | canon and pending names are wrapped in `span.entity-mark`; the rejected name is not | `NarrativeLog.tsx` |
| T3.3 | hover a mark | native tooltip reads `Bob · npc · canon` (name · kind · status); click does nothing | `NarrativeLog.tsx` |
| T3.4 | name in a player message and an alias in a DM reply | both are marked | `NarrativeLog.tsx` |
| T3.5 | reload the page with an old message containing a name | the old message is marked (no re-mining needed) | `App.tsx` |
| T3.6 | press Edit on a marked message | textarea holds raw text with no markup; after Save the new text is marked | `NarrativeLog.tsx` |
| T3.7 | `GET /api/v1/sessions/<id>/messages` after marks show | `content` identical to what was sent/generated (no marks stored) | (backend, read only) |
| T3.8 | `/roll 1d20`, an admin card, a command echo naming an entity | none of them are marked | `NarrativeLog.tsx` |
| T3.9 | block the entities request (devtools) and reload | log renders plain text, no error banner, no thrown error | `App.tsx` |
| T3.10 | entity proposed by the newest reply | marks appear after the next `done` refresh at the latest; browser console has no entity names | `App.tsx` |

### WP-4
| ID | Exercises | Expected outcome | File |
|---|---|---|---|
| T4.1 | build | `npm run build` exits 0 | `frontend/src/index.css` |
| T4.2 | canon vs pending mark | canon = solid outline, pending = dashed outline; line height and wrapping of the paragraph do not shift | `frontend/src/index.css` |
| T4.3 | a new marked message appears | the box draws in once; it then stays as a static outline and does not loop or replay on re-render | `frontend/src/index.css` |
| T4.4 | OS/browser `prefers-reduced-motion: reduce` (devtools emulation) | outline shows immediately, no animation | `frontend/src/index.css` |

## 3. Work Packages
Do WP-1 to WP-4 in order. Verification for every package: `cd frontend && npm run build` (exit 0), then that package's manual tests.

### WP-1: World entity types and API client
- **Files:** `frontend/src/types.ts`, `frontend/src/lib/api.ts`
- **Inputs:** `api.ts` already has `authHeaders()`, `parseJson<T>()`, `getApiBaseUrl()` and e.g. `listMessages(sessionId)` (same style to copy). The backend route exists: `GET {base}/api/v1/world/entities?session_id=<id>` with bearer auth, body `{entities: [...]}`; row fields `id, session_id (string|null), kind, name, aliases (string[]), notes, status, evidence (object|null), created_at, updated_at`.
- **Outputs:** in `types.ts`: `EntityKind = 'npc'|'place'|'faction'|'quest'|'item'|'other'`, `EntityStatus = 'canon'|'pending'|'rejected'`, `interface WorldEntity` (the fields above, `evidence: Record<string, unknown> | null`), `interface WorldEntityListResp { entities: WorldEntity[] }`. In `api.ts`: `export async function getWorldEntities(sessionId: string): Promise<WorldEntityListResp>` using `encodeURIComponent(sessionId)`, `headers: authHeaders()`, returning `parseJson<WorldEntityListResp>(response)`; import the new types.
- **Acceptance criteria:** the function issues one GET to the route above with the auth header and returns the parsed body; it rejects (throws) on a non-OK response via `parseJson`; no other file changes. Tests T1.1, T1.2.
- **Patterns used/created:** PAT-ARCH-014 (accepted)

### WP-2: Pure entity-mention matcher
- **Files:** `frontend/src/lib/mentions.ts` (new)
- **Inputs:** type `WorldEntity` and `EntityStatus` exist in `frontend/src/types.ts` (`name: string`, `aliases: string[]`, `status: 'canon'|'pending'|'rejected'`). Mirrors the server rule in `app/intelligence/world_mentions.py` (`_tokens`: casefolded `[a-z0-9]+` runs; `_known_labels`: name + aliases); cite that file in a header comment and note that the two must change together (PAT-ARCH-014).
- **Outputs:** `export interface Segment { text: string; entity?: WorldEntity }` and `export function segmentText(text: string, entities: WorldEntity[]): Segment[]`. No React import, no DOM, no logging, no state.
- **Acceptance criteria:** (1) entities with status `rejected` are ignored; labels = `name` + `aliases` of the rest; a label's tokens are its lowercase `[a-z0-9]+` runs, labels with no tokens are skipped. (2) A label matches case-insensitively where its tokens appear in order separated by any non-empty run of non-alphanumeric characters, and where the character before the first token and after the last token is not `[a-z0-9]` (build one `RegExp` per label, flags `gi`, lookbehind/lookahead for the boundaries; match the original text so offsets are kept, do not lowercase it). (3) Every occurrence matches. (4) Overlaps: collect all matches, sort by length descending, then start ascending, then entity list order; keep a match only if it overlaps no kept match; output in text order. (5) Output segments are contiguous, in order, plain segments have no `entity`, marked ones carry the matched `WorldEntity`, and joining all `text` values equals the input exactly. (6) No entities or no matches returns `[{ text }]`. Tests T2.1 to T2.8 (cannot be unit-tested without adding a runner, which is out of scope; verify by build and by reading).
- **Patterns used/created:** PAT-ARCH-014 (accepted)

### WP-3: Fetch entities and render marks in the narrative bubble
- **Files:** `frontend/src/App.tsx`, `frontend/src/components/NarrativeLog.tsx`
- **Inputs:** `getWorldEntities(sessionId)` in `lib/api.ts` returns `Promise<{ entities: WorldEntity[] }>`; `segmentText(text, entities): Segment[]` in `lib/mentions.ts` returns `{ text: string; entity?: WorldEntity }[]`; `WorldEntity` is in `types.ts` (`name`, `kind`, `status`). In `App.tsx` the effect keyed on `[sessionId]` defines `load()` for messages (called with `void load()`) and an `onEvent` handler whose `done` branch updates messages and calls `setIsSending(false)`. In `NarrativeLog.tsx`, `Bubble` renders `<p>{message.content ?? ''}</p>` in its non-editing branch; `NarrativeLog` renders `<Bubble ... />` for narrative messages only.
- **Outputs:** `App.tsx`: `const [entities, setEntities] = useState<WorldEntity[]>([])`; inside the `[sessionId]` effect, `setEntities([])`, then `loadEntities()` = try `getWorldEntities(sessionId)` and `if (mounted) setEntities(result.entities)`, catch and ignore (keep the current list; no banner, no `setErrorText`, no console output); call it right after `void load()` and again in the `done` branch; pass `entities={entities}` to `<NarrativeLog>`. `NarrativeLog.tsx`: add `entities: WorldEntity[]` to `NarrativeLogProps` and `BubbleProps`, pass it to `Bubble`; in the non-editing branch render `<p>{segmentText(message.content ?? '', entities).map((seg, i) => seg.entity ? <span key={i} className={`entity-mark entity-mark-${seg.entity.status}`} title={`${seg.entity.name} · ${seg.entity.kind} · ${seg.entity.status}`}>{seg.text}</span> : seg.text)}</p>` (React fragments or text children with keys as needed; no `dangerouslySetInnerHTML`, no `onClick`).
- **Acceptance criteria:** marks appear only inside `Bubble` view text (player and DM), never in the edit textarea, `AdminCard`, `RollCard` or the command echo; stored `message.content` is never modified; entity fetch failure leaves plain text with no banner; no entity names reach `console`; no change to `meta`, to message state shape, or to any backend file. Open-question defaults are applied (see section 4). Tests T3.1 to T3.10.
- **Patterns used/created:** PAT-ARCH-014 (accepted); PAT-ARCH-013 unchanged (never classify by text, no new meta key)

### WP-4: Mark styles and draw-in animation
- **Files:** `frontend/src/index.css`
- **Inputs:** WP-3 renders `<span class="entity-mark entity-mark-canon|entity-mark-pending" title="...">text</span>` inside `.bubble p` (which has `white-space: pre-wrap`). Existing theme variables: `--brass`, `--brass-bright`, `--border-strong`. Existing keyframes `pulse`, `menu-in`, `fade-in` (do not edit them). `App.css` is not imported; do not touch it.
- **Outputs:** append rules near the `.bubble p` block: `.entity-mark` (inline, `border-radius: 3px`, `outline-offset: 2px`, no padding/margin/border so layout does not shift, `animation: entity-box-in 0.6s ease-out 1 both`), `.entity-mark-canon { outline: 1px solid var(--brass-bright); }`, `.entity-mark-pending { outline: 1px dashed var(--brass); }`, one `@keyframes entity-box-in` that starts with `outline-color: transparent; outline-offset: 0.45em` and ends at the static values, and `@media (prefers-reduced-motion: reduce) { .entity-mark { animation: none; } }`.
- **Acceptance criteria:** canon boxes are solid and pending boxes are dashed; the animation runs once per mount (the `animation` shorthand lives only on `.entity-mark`, not on the status classes, so a pending-to-canon change does not replay it) and the final state is a static outline; under reduced motion there is no animation and the outline is visible at once; paragraph wrapping and line height are unchanged. Tests T4.1 to T4.4.
- **Patterns used/created:** PAT-ARCH-014 (accepted)

## 4. Other Details
- **Risks:** a short common name (e.g. "Bob") is boxed everywhere; the TS matcher can drift from `world_mentions._tokens` (ASCII tokens only; Python `casefold` vs JS `i` flag differ on rare non-ASCII letters, ignored); lookbehind needs a modern browser (Safari 16.4+); a row proposed by the latest reply may mark one refresh late.
- **Rollback plan:** revert the four files (frontend only, nothing stored or migrated).
- **Patterns applied/created:** PAT-ARCH-014 (accepted, created by ADR-0016); PAT-ARCH-012, PAT-ARCH-013 applied unchanged (accepted). No new pattern from this spec.
- **Non-goals:** backend/OpenAPI change, new meta key, backfill or re-detection of old chats, approval/rejection UI, click popover, looping animation, adding a frontend test runner.

### Open Questions
The architect's questions; each work package applies the recommended default. Do not resolve without the owner.
1. Box canon entities added by hand as well as detector-found? Recommended: **both**.
2. Box names in player messages as well as the DM's? Recommended: **both**.
3. Box every occurrence in a message, or only the first? Recommended: **every occurrence**.
4. Show pending entities to the kids before an approval screen exists? Recommended: **yes, dashed**.
5. Re-run detection over old chats? Recommended: **no**; a separate requirement if wanted.
6. (Spec writer) Add a frontend test runner (e.g. Vitest) to unit-test `segmentText`? Recommended: **no**, manual checklist only, per the charter.
