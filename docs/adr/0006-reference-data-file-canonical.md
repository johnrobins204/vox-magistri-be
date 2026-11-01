---
id: ADR-0006
status: accepted
date: 2026-10-18
requirement: REQ-0018
supersedes: null
superseded_by: null
---

# Curated reference data (species, classes, ...) is file-canonical in git, normalized at ingest, loaded once at startup, and served read-only

## Context
A consultant is delivering curated tabletop reference data. The first file is
`docs/from_consultant/dnd_all_species_full_list.json`. Classes come next and backgrounds
probably after that. The system needs one standing strategy for how this data is stored,
versioned, loaded and served to two consumers:
(a) the React frontend (`frontend/`, a species browser in the character creator), and
(b) backend LLM tooling (prompts and adjudication that reference species traits).
The human does not want to "mix db and portable data". `dnd.db` holds only runtime user data
(ADR-0003, PAT-ARCH-002).

Patterns consulted: PAT-ARCH-001, -002, -003, -004 (accepted), PAT-ARCH-005 (proposed),
PAT-CODE-001 (accepted). None of them covers reference data. PAT-ARCH-003 gives the closest
precedent: voice config is loaded once, falls back to `{}`, and logs a `get_logger` warning.

**ADR triggers (docs/adr/README.md):**
- *Two or more genuinely viable approaches.* **Fired.** Static bundle, file-plus-memory and
  DB seed all work for the first dataset.
- *Changes a cross-cutting convention.* **Fired.** Every future reference dataset will follow
  this decision, and it fixes where the "user data vs curated data" boundary sits.
- *Costly or hard to reverse.* **Borderline.** REQ-0015 characters will store references
  to species. The id scheme chosen here becomes persisted user data.
- *Deviates from an accepted pattern / new dependency.* **Not fired.** No accepted pattern
  changes. pydantic and stdlib `json` are enough.

The human asked for an ADR, and the triggers above confirm that one is needed.

**Verified facts (tree on 2026-10-18):**

| # | Fact | Where |
|---|---|---|
| F1 | 68 entries. Each has exactly the keys `Name`, `Edition`, `Source`, `Creature Type`, `Description` and `Character Creation Implications`. Keys contain spaces. Edition values: 10 x `"5.5e"`, 48 x `"5e"`, 10 x `"3rd Party"` | `dnd_all_species_full_list.json` lines 4-76, 84-460, 468-540 |
| F2 | Data-quality defects. `Edition: "3rd Party"` mixes up edition and publisher. "Hollow One" is tagged `3rd Party`, but its source is "Explorer's Guide to Wildemount (Darrington Press / WotC)". Some names carry edition or variant qualifiers: "Half-Elf (Legacy 2014)", "Half-Orc (Legacy 2014)", "Genasi (Air)" ... | same file, lines 251, 259, 179-203, 505-509 |
| F3 | Precedent for loading a checked-in file at runtime: `load_voice_configs()` reads a JSON file under `app/`, never raises, logs one warning and returns `{}`. It is called once when the service is built | `app/intelligence/prompt_builders.py:30,39-64`, `app/services/inference_service.py:58` |
| F4 | `dnd.db` is gitignored and disposable, with schema via `CREATE IF NOT EXISTS` + `user_version`. It holds only sessions and messages | ADR-0003, PAT-ARCH-002 rules 5-6, `app/services/repos.py` |
| F5 | The `/api/v1/intel` router is about tools, inference status and session snapshots. It has no reference-data routes | `app/api/v1/intelligence.py:27,40,50,74,90` |
| F6 | The frontend currently fetches only sessions, messages and `/intel/status`. It has no species code | `frontend/src/lib/api.ts:28-51` |
| F7 | REQ-0015 (campaign domain: characters, quests) is in the backlog and not built. The backlog note says "ADR likely: yes (domain boundary and storage shape)" | `.github/BACKLOG.json` REQ-0015 |
| F8 | API convention (proposed): every route has a `response_model`, and collections are `{"<plural>": [...]}` | PAT-ARCH-005 |
| F9 | The name `data/` belonged to the deleted SQLAlchemy layer, so reusing it would blur that history | `.github/copilot-instructions.md` "Known gaps" |

## Decision Drivers
Weights: High = 3, Medium = 2, Low = 1. Scores run from 1 (poor) to 5 (strong). The
weighted total is the sum of score x weight, out of a maximum of 100.

| Dimension | Weight | Why it matters here |
|---|---|---|
| Simplicity / smallest-edit fit (Simp) | High (3) | constraints.md 1 |
| Reversibility (Rev) | High (3) | constraints.md. Each extra dataset multiplies the cost of a wrong choice |
| Maintainability for one part-time person (Maint) | High (3) | Consultant redeliveries must be reviewable and must not silently change behavior |
| Reuse of existing patterns/deps (Reuse) | Medium (2) | F3, F8, PAT-ARCH-002 |
| Fun / learning (Fun) | Medium (2) | constraints.md 5 |
| Performance (Perf) | Low (1) | 68 entries of about 0.5 KB each |
| Security beyond sane defaults (Sec) | Low (1) | Read-only public reference data |
| **Consumer reach (Reach)** (added) | High (3) | The requirement names two consumers, frontend and LLM tooling, and REQ-0015 will be a third (F7). An option that cannot reach a named consumer fails the requirement |
| **User-data / curated-data separation (Sep)** (added) | Medium (2) | The human's stated design instinct. Curated data must be reviewable in git, and `dnd.db` stays disposable (F4). Medium, not High, because it is a preference rather than a MUST |

Gate: an option that cannot serve both named consumers (a) and (b) is disqualified,
whatever its total.

## Considered Options
- **A. Static frontend bundle.** Copy the JSON into `frontend/src` and import it at build
  time.
- **B1. File-canonical, raw file loaded at runtime.** The backend loads the consultant file
  as delivered and normalizes it in the loader on every start.
- **B2. File-canonical, normalized at ingest, loaded once at startup.** A normalized,
  repo-owned file under `app/reference/` is the source of truth. The consultant file stays
  in `docs/from_consultant/` as a provenance record that the app never loads. The backend
  validates the file with a pydantic model once at startup and keeps it in memory. A
  read-only GET route serves the frontend, and LLM tools read the in-memory catalog.
- **C. Seed a DB table from the checked-in file.** Upsert into a `species` table on startup,
  following PAT-ARCH-002 (`CREATE IF NOT EXISTS` + `user_version` bump).
- **D. Do nothing.** Leave the file in `docs/` with no consumer.

## Rubric Scoring
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | Reach (3) | Sep (2) | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| A Static frontend bundle | 4: copy the file and add a TS type; no backend change | 4: easy to move later | 2: normalization written in TS now and again in Python when the backend needs the data, so two copies drift | 2: the frontend is not spec-governed; no backend pattern is reused | 2 | 5: no network call | 3 | 1: backend tools and REQ-0015 cannot see it | 4: kept out of the DB, but split away from the backend | 57, **disqualified** (fails consumer b) |
| B1 Raw file, runtime normalization | 4: one loader and one route | 4: no schema | 2: quirk handling (F2) grows in the loader with each dataset; a redelivery silently changes what is served; the git diff of the raw file is not what the app sees | 4: follows the F3 precedent | 3 | 4 | 3 | 5: memory serves API and tools | 5: DB untouched | **76** |
| **B2 Normalized at ingest, loaded once** | 4: one normalized JSON, one pydantic model, one loader (about the size of `load_voice_configs`), one GET route | 5: no schema or migration; moving to C later means seeding from this same file | 5: the git diff is exactly what the app serves; pydantic validates on load; a CI test catches dropped entries; redeliveries arrive as reviewable diffs | 5: F3 loading precedent, F8 response models and envelopes, pydantic already a dependency | 3: designing the ingest normalization has modest learning value | 4: about 40 KB held in memory | 3 | 5: frontend via the API, tools via memory, REQ-0015 via a stable id | 5: DB untouched, and curated data lives in git | **90** |
| C DB seed from file | 2: a new table, upsert with orphan-delete semantics, a `user_version` bump and new store methods, plus the file and normalization from B2 anyway | 3: the schema persists in user DBs (disposable, but the migration branch stays in code) | 3: two representations (file and table) must be kept in sync on every start | 4: applies PAT-ARCH-002 directly | 4: SQL and joins | 4 | 3 | 5: and real FKs for REQ-0015 | 1: puts curated data into the runtime DB, which is exactly what the human wants to avoid | **64** |
| D Do nothing | 5 | 5 | 3 | 3 | 1 | 5 | 3 | 1: no consumer | 5 | 68, **disqualified** (fails a and b) |

**Sensitivity:** C's real advantage is relational integrity for REQ-0015, and the rubric
does not score it. Adding a "relational integrity" dimension at High (3), with C = 5 and B2 =
3 (an id string checked against the catalog in Python), gives B2 99 and C 79 out of 115. B2
still wins. C would only overtake B2 if Sep were dropped and integrity were weighted 9 or
more.

## Decision Outcome
**Chosen: B2.** It wins on the rubric (90, versus 76 for B1 and 64 for C), and it is the only
option that scores top marks on both added dimensions without giving up simplicity.

The decision, at the level an ADR fixes (detailed ETL and file layout belong in the spec):

1. **Canonical home.** Normalized reference files live in git under `app/reference/`, one
   file per dataset (for example `species.json`). They sit next to the code that loads
   them, as voice configs do (F3), and not under `data/` (F9). Git is the version history.
   No `schema_version` field is added unless a spec needs one.
2. **Consultant files are provenance, not runtime inputs.** `docs/from_consultant/*` stays
   as delivered and is never read by the app.
3. **Normalization lives at ingest time, not at runtime.** When a consultant delivery is
   accepted, it is converted into the repo's schema in one reviewable commit. Whether that
   is done by hand or by a small script is a spec decision. The normalized schema MUST:
   - use snake_case keys;
   - give each entry a stable `id` slug;
   - keep edition and publisher as separate fields, so `"3rd Party"` is not an edition;
   - give each entry an explicit first-party/third-party flag;
   - strip qualifiers out of names where they duplicate a field.

   F2 lists the defects ingest must resolve. Fixing a misclassified entry, such as Hollow
   One, is a curator decision recorded in that commit.
4. **Loading.** Each dataset gets one pydantic model. The file is loaded once while the
   services are built (not at import time) and exposed through the services dict with a
   `deps` accessor, following the existing service-locator pattern. At runtime, loading
   fails soft, as `load_voice_configs` does. A missing or invalid file gives an empty
   catalog and one `get_logger` warning. An invalid entry is dropped with one warning. In
   CI, loading fails hard: a test loads the checked-in file and asserts that no entry was
   dropped.
5. **Serving.** Read-only GET routes with a `response_model` and a `{"species": [...]}`
   envelope (PAT-ARCH-005). The proposed router prefix is `/api/v1/reference` rather than
   `/api/v1/intel`, because `/intel` is about tools and inference (F5); see the open
   question below. There are no write routes. With 68 entries, the route returns everything
   and the client filters, for example to hide third-party entries.
6. **LLM tooling.** Tools and prompt builders read the in-memory catalog through the service
   or context. They never open the file directly.
7. **References from user data (REQ-0015).** User records store the reference `id` as plain
   TEXT with no SQL foreign key, and the service validates it against the catalog on write.
   Once an id is published it MUST stay stable. A rename keeps the id. Removing an id is a
   breaking data change and needs a deliberate migration.
8. **No speculative abstraction.** Species gets its own loader. A shared
   `load_reference(path, model)` helper MAY be extracted when the second dataset (classes)
   lands, because that is the second call site (constraints.md 2).

**What was traded away:**
- Real SQL foreign keys and joins between characters and reference data (C).
- Zero-network rendering in the frontend (A).
- The convenience of loading the raw consultant file as delivered (B1). B2 adds one ingest
  step per delivery.

## Consequences
- Positive:
  - `dnd.db` remains pure user data and can still be deleted at any time.
  - Curated data is diffable, reviewable and versioned in git.
  - One copy of the data reaches the frontend, the tools and future REQ-0015 records.
  - No schema, no migration and no new dependency.
- Negative:
  - Each consultant redelivery needs a manual or scripted ingest step.
  - Characters reference species by an unenforced string id.
  - A fail-soft runtime load can hide a broken file, because the catalog is just empty. The
    CI test mitigates this.
- Follow-up work and accepted risks:
  - The requirement must be logged and get a backlog entry (orchestrator and Backlog Manager).
  - The spec defines: the normalized species schema, the edition vocabulary (`5e`/`5.5e`
    versus `2014`/`2024`), the id slug rule, the ingest procedure, the route path and the
    response model.
  - The data paraphrases commercial and third-party sourcebooks. Keep entries as short
    summaries and do not ingest verbatim rules text.

**Revisit triggers. Reopen this ADR, possibly moving to C with the file still canonical,
if:**
- REQ-0015 needs queries that join or aggregate user records against reference attributes
  and are awkward to do in Python.
- Users need to author or edit their own species or classes (homebrew) at runtime. That is
  user data, so it goes to the DB under PAT-ARCH-002, and curated data stays in files.
- One reference dataset grows to thousands of entries with large payloads (for example full
  monster stat blocks), so memory or full-list responses become a real problem.
- The frontend must work offline without the backend. A then comes back as a build-time
  export generated from the same file, never edited by hand.

## Pattern Impact
- **Creates PAT-ARCH-006**, "Curated reference data: file-canonical in git, normalized at
  ingest, loaded once, served read-only" (`status: proposed`).
- **Uses** PAT-ARCH-003 (the voice-config loading precedent), PAT-ARCH-005 (response models
  and envelopes) and PAT-CODE-001 (logging).
- PAT-ARCH-002 is unchanged. Its "maybe campaign data later" scope still covers REQ-0015
  user data, and reference data is not persisted state.
- No accepted pattern is modified.
