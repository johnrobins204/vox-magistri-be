---
id: PAT-ARCH-007
category: architecture
status: proposed
supersedes: null
superseded_by: null
---

# Bulk upstream reference sources: sync to gitignored scratch, allowlist and project at ingest into PAT-ARCH-006 files

## Problem
Some reference data comes from a large upstream source, such as the open5e API (about 37 MB
over 12 endpoints), rather than a small curated delivery. Calling the source at runtime
breaks offline play and lets content drift. Committing the raw dumps bloats git history
forever and produces diffs nobody can review. Loading everything wastes memory on content
the app never uses.

## Context
This pattern applies to read-only reference data fetched from a bulk upstream source and fed
into PAT-ARCH-006. It does not apply to:
- small hand-curated deliveries, which use PAT-ARCH-006 directly;
- user or homebrew data, which uses PAT-ARCH-002;
- a dataset that cannot fit the budget even after allowlisting and projection. That dataset
  uses the ADR-0007 fallback: a derived, read-only, gitignored SQLite file.

Decided by ADR-0007.

## Solution
1. **Sync offline, on demand.** A Python script (`scripts/sync_<source>.py`) pages through the
   upstream API.
   - It writes raw snapshots and a `_manifest.json` (endpoint, `fetched_at`, count) to a
     **gitignored** scratch directory (`dnd_data/`).
   - It also fetches the upstream document and license metadata.
   - The app never calls the upstream at runtime.
2. **Ingest only what a consumer needs.** A dataset is ingested only when a named consumer
   (a route, tool or prompt builder) needs it. Every other dataset stays in scratch.
3. **Allowlist, then project, then normalize.**
   - Keep an explicit list of upstream document keys per dataset (the default is SRD only).
   - Keep only the fields the consumer uses, and drop duplicated or derivable fields.
   - Then apply the PAT-ARCH-006 normalization: snake_case keys, an `id` slug, separate
     edition and publisher fields, and a `third_party` flag.
   - Keep the upstream key as `source_key`.
4. **Repo-owned ids, curated overlay wins.** Upstream keys are never ids. Ids that are
   already published win. Where curated (consultant) and bulk entries share an id, the
   curated fields win. All merging happens at ingest, into one file per dataset.
5. **Budget.** A canonical file stays under 2 MB and 2,000 entries, and a CI test asserts it.
   A dataset over budget moves to the ADR-0007 fallback tier, under the same
   `reference["<dataset>"]` key.
6. **Attribution.** Ingest generates `app/reference/ATTRIBUTION.md` (title, publisher,
   license and permalink for each allowlisted document). It adds the full license text, for
   example `LICENSE-OGL.txt`, when a license requires it.

## Consequences
- Play is offline and data is pinned per commit. Git growth is bounded and diffs stay
  reviewable.
- The curator must choose documents and fields. A dropped field means re-running ingest from
  scratch, or re-syncing.
- A fresh clone has the committed canonical files but not the raw snapshots. Re-ingesting
  needs a sync, which needs the network.

## Examples
- No implementation exists yet. The shape precedent is `scripts/ingest_species.py`
  (PAT-ARCH-006). The wiring precedent is `app/services/build_services.py` lines 33-34.
