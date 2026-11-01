---
id: ADR-0007
status: proposed
date: 2026-10-31
requirement: REQ-TBD  # placeholder: the orchestrator assigns the REQ id when it logs the requirement in docs/requirements/LOG.md
supersedes: null
superseded_by: null
---

# open5e bulk reference data: sync offline, project and allowlist at ingest into ADR-0006 files; derived read-only SQLite only as a per-dataset fallback

## Context
The project pulled bulk reference data from the open5e API (`https://api.open5e.com`) into
`dnd_data/`. The measured profile has 12 endpoints and about 37 MB in total:

| Dataset | Entries | Size |
|---|---|---|
| creatures | 3,541 | 24 MB |
| spells | 1,955 | 5.4 MB |
| magicitems | 2,322 | 4.6 MB |
| classes | not counted | 1.5 MB |
| species | 63 | 168 KB |
| backgrounds, conditions, feats, armor, weapons, rules, sections | not counted | under 400 KB each |

The open question is whether the app should call open5e at runtime, extract the data once
and store it, or do something in between, and which storage form to use.

This ADR **extends** ADR-0006 and does not amend it. ADR-0006 is accepted and was decided
for a different kind of source: a hand-curated consultant delivery of 68 entries and 32 KB.
That ADR is still correct for its own scope. This decision adds:
- a new kind of source (a bulk upstream API, used as a build-time input only);
- new artifacts (a sync script, a document allowlist, an attribution file);
- a size budget;
- a pre-agreed fallback storage tier.

An amendment would rewrite an accepted record. A new ADR keeps ADR-0006 intact. The few
places where PAT-ARCH-006's wording needs a clarification are listed under Pattern Impact
for human sign-off and are not applied here.

Patterns consulted:
- PAT-ARCH-001 to PAT-ARCH-004, PAT-ARCH-006 and PAT-CODE-001 (accepted);
- PAT-ARCH-005 (proposed).

The relevant ones are PAT-ARCH-006 (the reference-data pattern), PAT-ARCH-002 (the
mechanics of the fallback tier) and PAT-ARCH-005 (envelopes).

**ADR triggers (docs/adr/README.md):**

| Trigger | Result | Reason |
|---|---|---|
| Two or more viable approaches | Fired | See the options below |
| Introduces an external service | Fired | open5e becomes a data source. Option A would make it a runtime dependency |
| Costly or hard to reverse | Fired | Committing 24 MB of JSON to git is permanent without a history rewrite. The id namespace becomes persisted user data for REQ-0015 |
| Touches an accepted pattern | Borderline | Two wording clarifications of PAT-ARCH-006 are needed (see Pattern Impact). They are flagged for sign-off, not applied |
| Revisit trigger in ADR-0006 | Fired | "A dataset grows to thousands of large entries" |

**Verified facts (tree on 2026-10-31):**

| # | Fact | Where |
|---|---|---|
| F1 | `dnd_data/` is **not** gitignored. `.gitignore` only lists `*.db`, `dev.db`, `logs/` and others, with no `dnd_data` entry. A plain `git add .` would commit 37 MB | `.gitignore` lines 23-25 |
| F2 | Every open5e entry carries `document{key, display_name, publisher{key,name}, gamesystem{key,name}, permalink}`. **No entry carries a license field**, so license data must be fetched separately | `dnd_data/creatures.json` lines 5-19, `dnd_data/classes.json` lines 2212-2226. A search for `licen[cs]e"` in `dnd_data/**` finds nothing |
| F3 | open5e mixes publishers and game systems. The first creature is `a5e-mm_aboleth` (EN Publishing, "Advanced 5th Edition"). Species are 1 x `open5e`, 9 x `srd-2024`, 13 x `srd-2014` and 40 x `toh` (Tome of Heroes, a third-party book) | `dnd_data/creatures.json` lines 3-19, `dnd_data/species.json` (document keys) |
| F4 | open5e keys have a document prefix and are not consistent: `srd-2024_dwarf` and `srd_dwarf` (the document key is `srd-2014`). The app's published ids are bare slugs: `dwarf`, `elf`, `human`. The same species appears in both the 2014 and the 2024 edition | `dnd_data/species.json` lines 138 and 904, `app/reference/species.json` lines 25, 36 and 80 |
| F5 | Creature records duplicate data: `speed`/`speed_all`, `saving_throws`/`saving_throws_all`, `skill_bonuses`/`skill_bonuses_all`. `modifiers` can be derived from `ability_scores`. Each record also repeats the full `document` object and `crossreferences` | `dnd_data/creatures.json` lines 30-112 |
| F6 | The reference wiring is one dict: `reference = {"species": load_species()}`. It goes into `tool_service.default_context["reference"]` and the services dict, and is read through `deps.get_reference()` | `app/services/build_services.py` lines 30-38, `app/deps.py` lines 43-45 |
| F7 | **No tool or prompt builder reads `context["reference"]` yet.** The only consumer is `GET /api/v1/reference/species` | grep over `app/intelligence/**`, `app/api/v1/reference.py` lines 7-14 |
| F8 | The ingest precedent `scripts/ingest_species.py` is about 80 lines: normalize, slug, curator `OVERRIDES` and write. The loader `load_species()` is fail-soft with per-entry drops | `scripts/ingest_species.py`, `app/reference/species.py` lines 37-69 |
| F9 | The repo has no fetch script. The user's curl script lives outside the tree | grep for `api.open5e` and `curl` in `*.sh`, `*.py` and `*.md` (venv and node_modules excluded) |
| F10 | `httpx` is already a runtime dependency | `requirements.txt`, `app/intelligence/client.py` |
| F11 | Average entry sizes in the snapshots are about 6.8 KB per creature, 2.8 KB per spell and 2.0 KB per magic item. These come from the measured profile above | derived |

## Decision Drivers
Weights: High = 3, Medium = 2, Low = 1. Scores run from 1 (poor) to 5 (strong). The maximum
total is 100.

| Dimension | Weight | Why it matters here |
|---|---|---|
| Simplicity / smallest edit (Simp) | High (3) | constraints.md 1. F7: the bulk data has no consumer yet |
| Reversibility (Rev) | High (3) | Blobs committed to git are permanent (F1). The id namespace becomes user data |
| Maintainability for one person (Maint) | High (3) | Upstream refreshes must be reviewable and must not silently change behavior |
| Reuse of patterns and dependencies (Reuse) | Medium (2) | PAT-ARCH-006 and F6/F8 already exist; httpx (F10) |
| Fun / learning (Fun) | Medium (2) | constraints.md 5 |
| Performance (Perf) | Low (1) | De-prioritized, but 24 MB loaded at startup or returned as a full list is a real cost |
| Security beyond sane defaults (Sec) | Low (1) | Read-only public data. Remote text flows into LLM prompts |
| **Local-first operation (Local)** (added) | High (3) | Stated project property: local Ollama, local SQLite, works offline. **Gate:** an option that needs the network during play is disqualified |
| **Content stability and reproducibility (Stab)** (added) | Medium (2) | No drift mid-campaign. A fresh clone gets the same data. Ids stay permanent (ADR-0006 rule 7). Medium because the household tolerates some manual steps |

Licensing is a requirement for **every** option: an attribution artifact (see the Decision
Outcome). It is not a scoring dimension, because no option avoids it. Options that pass
fewer documents through (D) make the attribution list shorter, and that is noted rather than
scored.

## Considered Options
- **A. Runtime API.** The app calls open5e live through httpx, possibly with a cache.
- **B. Full extraction into ADR-0006 files.** All 12 datasets go into `app/reference/*.json`
  in git, with every document and every field.
- **C. Two-tier hybrid.** Datasets under about 500 KB follow ADR-0006. Creatures, spells,
  magic items and classes go into a gitignored, regenerable `reference.db` built from the
  snapshots. It is read-only at runtime and uses PAT-ARCH-002 mechanics.
- **D. Curated slim projection with a document allowlist into ADR-0006 files** (added). A
  Python sync script writes the raw snapshots to gitignored scratch. A dataset is ingested
  into `app/reference/<dataset>.json` only when a consumer needs it. Ingest keeps only the
  allowlisted documents (by default SRD 5.1 and/or SRD 5.2) and only the fields the app
  uses, and it must stay within a size budget. If a dataset cannot fit the budget, that
  dataset alone falls back to C's derived read-only SQLite.

"Do nothing" was not scored. The human asked for a decision on where the data lives. F7
does shape D, though: datasets are ingested when a consumer needs them, not all at once.

## Rubric Scoring
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | Local (3) | Stab (2) | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| A Runtime API | 3: no ingest, but it needs pagination over the v2 endpoints, timeouts and a cache in the adjudication path | 5: nothing is persisted | 2: upstream schema changes break play at runtime instead of at ingest review | 3: httpx is reused (F10), but PAT-ARCH-006 is not, and the frontend needs a proxy | 3 | 2: a network round trip per lookup, on top of Ollama latency; rate limits unknown | 2: remote content goes into prompts without review | 1: fails offline | 1: content and keys can drift mid-campaign | 51, **disqualified** (Local gate) |
| B Full extraction to git JSON | 3: same shape as F8, but full pydantic models for deeply nested creature records (F5) are heavy | 2: 37 MB in git history is permanent, and each refresh adds a multi-MB diff | 2: nobody reviews a 24 MB diff; models track every upstream field | 5: exactly PAT-ARCH-006 | 2: bulk copying | 2: about 37 MB parsed and validated on every start; the full-list rule (PAT-ARCH-006 rule 5) gives a 24 MB response | 3 | 5: offline | 5: pinned in git | 65 |
| C Two-tier hybrid (reference.db) | 2: a new store class, a schema for 4 datasets, a build script, a second wiring path and query/paging routes, alongside the ADR-0006 path | 4: the DB is derived and gitignored, but its code surface persists | 3: two storage forms for one concept; content changes are not diffable because the DB is binary | 4: PAT-ARCH-002 plus PAT-ARCH-006 | 5: SQL, FTS5 search | 5: indexed queries | 3 | 5: offline once built | 2: a fresh clone cannot rebuild without the network (snapshots are not in git); a re-sync can silently drop ids that user data references | 72 |
| **D Slim projection + allowlist into git JSON, with a per-dataset C fallback** | 4: one script and one model per dataset, shaped like F8; no new storage; the C fallback is built only if the budget is exceeded | 4: git growth is capped by the budget; moving one dataset to C later loads the same canonical file | 4: diffs stay reviewable at budget size; models cover only the projected fields; the allowlist and projection are curator decisions to make | 5: PAT-ARCH-006 plus F6 wiring, unchanged | 3: projection and ETL design | 3: budget-capped memory and responses | 3: content is reviewed at ingest before it reaches prompts | 5: offline | 5: pinned in git; ids are repo-owned | **83** |

**Sensitivity:**

| Change to the rubric | D | C | Winner |
|---|---|---|---|
| Fun raised to High and Perf to Medium (the scenario most favorable to C) | 89 | 82 | D |
| Stab dropped entirely | 73 | 68 | D |

C overtakes D only when the household wants all 3,541 creatures across all publishers. In
that case D's budget fails for creatures, and D already says to use C for that dataset. The
real dividing line is the allowlist, not the storage engine.

**Budget feasibility (estimate; the spec MUST measure it).** SRD 5.1 and SRD 5.2 each hold
about 300-350 monsters (general knowledge, not measured here). At about 6.8 KB per creature
(F11), both SRDs come to about 4.4 MB with every field. Removing the F5 duplicates and the
repeated document objects plausibly saves 30-50%, which leaves about 2-3 MB for both SRDs
and about 1-1.5 MB for one. **Creatures for both SRDs sit at the budget line.** Choosing one
ruleset, or the fallback, resolves it. Spells (about 0.9 MB per SRD at full fields) and
magic items (about 0.5 MB per SRD) fit comfortably.

## Decision Outcome
**Chosen: D** (83, against 72 for C, 65 for B, and 51 for A, which is disqualified).

D keeps one storage form (ADR-0006), keeps content pinned and reviewable in git, and keeps
play offline. It also does no work before a consumer exists (F7). C's genuine strengths,
indexed search and scale, are kept as a pre-agreed per-dataset fallback, so they need no new
ADR.

The decision, at the level an ADR fixes (field lists, the slug algorithm and file layout
belong in the spec):

1. **No runtime calls to open5e.** The app never contacts open5e. The API is a build-time
   input only.
2. **Sync is a Python script, run on demand.** `scripts/sync_open5e.py` replaces the
   out-of-tree curl script (F9).
   - It uses httpx (F10) or stdlib `urllib`; the spec chooses.
   - It pages through the v2 endpoints and writes raw snapshots to `dnd_data/`.
   - It writes `dnd_data/_manifest.json` with the endpoint, `fetched_at` and the count for
     each file.
   - It fetches the document and license metadata (`/v2/documents/`), because entries
     carry no license field (F2).
   - **`dnd_data/` MUST be added to `.gitignore`** (F1). The snapshots are local provenance,
     as `docs/from_consultant/` is for the consultant, but they stay out of git because of
     their size.
3. **Ingest = allowlist + projection + normalization**, one script or function per dataset,
   in the shape of `scripts/ingest_species.py` (F8).
   - **Allowlist.** An explicit list of open5e `document.key` values per dataset. The
     default is the SRD documents only; which SRD (2014, 2024 or both) is an open question.
     Third-party documents (`toh`, `a5e-*`, ...) are excluded unless the curator adds them.
   - **Projection.** Keep only the fields a named consumer needs. Drop the F5 duplicates and
     derivable fields. Collapse `document` into flat `source`, `publisher`, `edition` and
     `third_party` fields, as ADR-0006 rule 3 requires.
   - Each record keeps `source_key` (the open5e `key`) for provenance and re-sync matching.
4. **Size budget.** A canonical file SHOULD stay under **2 MB** and **2,000 entries**. A CI
   test asserts the budget, alongside the "no entry dropped" test. A dataset that cannot fit
   after allowlisting and projection moves to the fallback tier (point 8). The budget
   applies to datasets ingested under this ADR. It does not apply retroactively.
5. **Id namespace and precedence.**
   - Ids are **repo-owned bare slugs** (ADR-0006 rule 7). open5e keys are never ids (F4).
   - Already published ids win. An open5e entry that describes the same thing (same name
     and same edition) maps onto the existing id.
   - When a slug collides across editions (2014 vs 2024 dwarf), the spec defines the
     edition-disambiguation rule once, for all datasets.
   - **Curated overlay beats the bulk baseline.** Where a consultant entry and an open5e
     entry share an id, the consultant's curated fields win. open5e only adds fields and
     entries the curator did not provide.
   - Merging happens **at ingest, into one file per dataset**, never at runtime.
   - The field-level merge rule is delegated to the spec. Species stays consultant-sourced
     unless a consumer needs open5e's structured traits.
6. **Attribution artifact.** Ingest generates `app/reference/ATTRIBUTION.md`, committed next
   to the data it covers.
   - For every allowlisted document it lists the title, publisher, license and permalink,
     taken from the F2/`/v2/documents/` metadata.
   - CC-BY-4.0 needs an attribution notice. OGL 1.0a needs the full license text and the
     Section 15 notices, so the full text goes in `app/reference/LICENSE-OGL.txt` when any
     OGL document is allowlisted.
   - Exposing attribution in the frontend is a spec or frontend decision. It matters only if
     the app is ever distributed beyond the household.
7. **Wiring is unchanged.** Each new dataset adds one key to the existing `reference` dict
   in `build_services.py` (F6). Tools read it through `context["reference"]` and routes read
   it through `get_reference()`. When the second dataset lands, the shared loader is
   extracted (PAT-ARCH-006 rule 8, now justified).
   - Full-list GET routes as in PAT-ARCH-005.
   - If a dataset under budget is still too large for the frontend as one response, the
     spec MAY add a summary list (id, name and a few key fields) plus a GET by id, without
     a new ADR.
8. **Fallback tier (per dataset, only if point 4 fails).** That dataset is built into a
   gitignored, derived, read-only `reference.db`, separate from `dnd.db`.
   - The build is a script, from the canonical projected file if one is committed, or from
     the snapshots otherwise.
   - It uses PAT-ARCH-002 mechanics, opened read-only (`file:...?mode=ro`, `uri=True`), with
     the path from a new `reference.url` setting.
   - The service object goes under the **same** `reference["<dataset>"]` key, so consumers
     do not change.
   - The fallback pattern is written up when it is first used (constraints.md 4), not now.

**What was traded away:**
- The full open5e corpus (3,541 creatures, third-party books) is not available by default.
- Indexed SQL search over reference data. Python filtering over at most about 2,000 entries
  is the substitute.
- Zero-effort refresh. Each refresh is sync, then ingest, then a reviewed commit.

## Consequences
- Positive:
  - Play stays fully offline, and data is pinned per commit.
  - One storage form for all reference data, with no new store, schema or dependency.
  - The attribution list is short and auditable, because only allowlisted documents ship.
  - The fallback is pre-decided, so growth needs no new ADR.
- Negative:
  - The curator has to choose fields and documents per dataset.
  - Creatures for both SRDs may sit at the budget line (see the estimate).
  - Projection can drop a field that a later consumer wants. The fix is to re-run ingest
    from the local snapshots, or to re-sync.
- Follow-up work and accepted risks:
  - Add `dnd_data/` to `.gitignore`, **and check whether it is already tracked** (F1). If it
    is, untrack it (`git rm -r --cached dnd_data`) and decide whether a history rewrite is
    worth it.
  - The spec defines:
    - the allowlist per dataset;
    - the projected field list per consumer;
    - the edition-disambiguation rule;
    - the sync script's paging, retry and manifest format;
    - the generation of `ATTRIBUTION.md`;
    - the budget CI test.
  - The order of ingest follows the consumers, for example a monster-lookup tool brings in
    creatures. Datasets with no consumer stay in `dnd_data/` only.
  - The consultant summaries of commercial books remain the legally sensitive artifact
    (already raised with the human). They are not covered by the open5e attribution, and
    they SHOULD NOT be published if the repo ever becomes public.

**Revisit triggers. Reopen if:**
- a dataset that a consumer needs cannot fit the 2 MB / 2,000-entry budget with a sensible
  allowlist. Apply the point 8 fallback first, and reopen if a second dataset also needs it
  (that would be two call sites for a shared SQLite reference store);
- the household wants third-party content (Tome of Heroes, A5e) at scale;
- a consumer needs full-text or multi-attribute search, for example "undead with CR at most
  3", that is awkward in Python over the in-memory list;
- REQ-0015 needs SQL joins against reference data. This is also an ADR-0006 trigger;
- open5e changes its API or licensing in a way that breaks sync, or the project starts
  distributing the app beyond the household (attribution in the UI then becomes a MUST).

## Pattern Impact
- **Creates PAT-ARCH-007** (`proposed`): "Bulk upstream reference sources: sync to
  gitignored scratch, allowlist and project at ingest into PAT-ARCH-006 files".
- **Uses** PAT-ARCH-006 (storage, loading, serving and ids), PAT-ARCH-005 (envelopes),
  PAT-CODE-001 (logging) and, only in the fallback, PAT-ARCH-002.
- **Clarifications to PAT-ARCH-006 (accepted), flagged for human sign-off and NOT applied:**
  1. Rule 2 says "raw deliveries are provenance only; keep them as delivered (for example in
     `docs/from_consultant/`)". The clarification adds: "Bulk upstream snapshots MAY be kept
     as gitignored local provenance with a manifest, when their size makes committing them
     impractical (PAT-ARCH-007)."
  2. The Context says "small enough to keep in memory (up to roughly thousands of entries)".
     The clarification replaces this with the explicit budget: "a canonical file under 2 MB
     and 2,000 entries. Above that, see ADR-0007's fallback tier."
  3. Rule 5 says "Return the full list and let the client filter". The clarification adds:
     "a summary list plus GET by id is allowed for a dataset that is within budget but too
     heavy for one response."
