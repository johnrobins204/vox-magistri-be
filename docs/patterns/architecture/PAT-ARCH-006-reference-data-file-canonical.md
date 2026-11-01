---
id: PAT-ARCH-006
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# Curated reference data: file-canonical in git, normalized at ingest, loaded once, served read-only

## Problem
Curated tabletop reference data (species, classes, backgrounds, ...) is read by the frontend,
by LLM tools and prompts, and later by user records (REQ-0015). It changes only when a
curator updates it. If it goes into the runtime DB, curated and user data get mixed, and a
schema/seed surface appears. If it is shipped only to the frontend, the backend cannot see
it. If raw third-party files are loaded at runtime, their quirks leak into the code, and a
redelivery can quietly change what the app serves.

## Context
This pattern applies to read-only, curator-maintained datasets that are small enough to keep
in memory (a canonical file under 2 MB and 2,000 entries; above that, see ADR-0007's fallback tier).

It does not apply to:
- Data that users create or edit at runtime, including homebrew. That data is user data and
  uses PAT-ARCH-002.
- Data that must be joined in SQL against user records. Reopen ADR-0006 in that case.

## Solution
1. **Canonical file.** Store one normalized JSON file per dataset in git under
   `app/reference/`. Git is the version history.
2. **Raw deliveries are provenance only.** Keep them as delivered (for example in
   `docs/from_consultant/`). The app never reads them. Bulk upstream snapshots MAY be kept as gitignored local source copies with a manifest, when their size makes committing them impractical (PAT-ARCH-007).
3. **Normalize at ingest.** Convert each delivery into the repo schema in one reviewable
   commit. The schema has:
   - snake_case keys;
   - a stable `id` slug for each entry;
   - edition and publisher as separate fields;
   - an explicit first-party/third-party flag.

   The diff of the canonical file is exactly what the app serves.
4. **Load once.** Use one pydantic model per dataset. Load the file while the services are
   built (not at import time) and expose it through the services dict and a `deps`
   accessor.
   - Runtime fails soft: a missing or invalid file gives an empty catalog and one
     `get_logger` warning. A bad entry is dropped with one warning.
   - CI fails hard: a test asserts that the checked-in file loads with no entry dropped.
5. **Serve read-only.** Use GET routes only, each with a `response_model` and a
   `{"<plural>": [...]}` envelope (PAT-ARCH-005). Return the full list and let the client
   filter. A summary list plus GET by id is allowed for a dataset that is within budget but too heavy for one response.
6. **Backend consumers** (tools, prompt builders) read the in-memory catalog and never open
   the file.
7. **References from user data** store the `id` as TEXT, validated against the catalog on
   write. Published ids are permanent. Renames keep the id.
8. **Share code only when there is a second dataset.** Extract a shared loader once a
   second dataset exists (constraints.md 2).

## Consequences
- The runtime DB stays pure user data and disposable. Curated data is diffable and needs no
  migrations.
- Each delivery needs an ingest step. There is no SQL-level referential integrity.
- A fail-soft load can hide a broken file at runtime. The CI test is the safety net.

## Examples
- Precedent (not this pattern itself): `load_voice_configs()` in
  `app/intelligence/prompt_builders.py:39`, called once at
  `app/services/inference_service.py:58`.
- First intended use: species (ADR-0006). No implementation exists yet.
