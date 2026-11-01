---
id: SPEC-0012
requirement: REQ-0019
adr: ADR-0007
status: done
date: 2026-11-01
---

# SPEC-0012: Bulk open5e reference ingest (sync, allowlist, projection, budget)

## Deviations (as built, 2026-11-01)

- Pilot dataset is `weapons`, not `conditions`. Fresh v2 conditions data has top-level keys `core` and `a5e-ag`, with SRD keys only inside per-edition descriptions. `conditions` stays in the allowlist and projection but is removed from `CONSUMERS`. WP-4 is implemented as `GET /api/v1/reference/weapons` (75 entries, 33,678 bytes).
- T-33 asserts the measured size and verdict instead of "fits". The real creatures data does not fit the budget with both SRDs combined (656 entries, 2,692,306 bytes). This is a parked human decision; see REQ-0019 follow-ups.

## 1. Requirement

Restated in [docs/requirements/LOG.md](../requirements/LOG.md) as REQ-0019.

Normative summary:
- Bulk reference data from open5e MUST be ingested per ADR-0007 option D.
- `scripts/sync_open5e.py` MUST sync on demand into the gitignored `dnd_data/` directory and MUST write `dnd_data/_manifest.json`.
- The app MUST NOT call open5e at runtime. No module under `app/` may contain the open5e host or import the sync or ingest scripts.
- Ingest MUST run per dataset, and only when a named consumer exists.
- Ingest MUST keep only allowlisted source documents and only the projected fields that a consumer uses.
- The SRD 5.1 (`srd-2014`) and SRD 5.2 (`srd-2024`) documents are canonical. Approved third-party documents MAY be allowlisted.
- Each committed `app/reference/*.json` file MUST stay within 2,000,000 bytes and 2,000 entries. A CI test enforces this.
- A dataset that cannot fit the budget MAY fall back to a gitignored, regenerable, read-only `reference.db` under the same `reference["<dataset>"]` key. The fallback is not built by this spec.
- Ingest MUST generate `app/reference/ATTRIBUTION.md`, and `app/reference/LICENSE-OGL.txt` when an OGL document is allowlisted.
- Ids MUST be app-owned slugs. Consultant entries win over open5e entries on id collision at ingest.
- ADR-0006 and PAT-ARCH-006 MUST remain intact: load once at startup, read-only `GET /api/v1/reference/<dataset>`, and `dnd.db` holds only user data.
- Tests MUST run without network. Frontend work is out of scope.

Decisions carried in from the human sign-off on 2026-11-01:
- ADR-0007 and PAT-ARCH-007 are `accepted`. The three clarifications to PAT-ARCH-006 are applied.
- Both SRDs are canonical: 2014 (SRD 5.1) and 2024 (SRD 5.2). The creatures budget MUST be measured with both.
- Third-party open5e documents are allowed. Attribution requirements still apply.

Pilot choice: `conditions` (see WP-4). It is the smallest dataset that carries both SRD documents, and it has a named consumer, the route in WP-4. The pilot is confirmed by the human before WP-4 starts (BACKLOG follow-up).

Verified facts used by this spec (from the tree on 2026-11-01):
- `.gitignore` already lists `dnd_data/` (lines 23-25). Whether the directory is already tracked is not verified here. The human checks this at commit time.
- `dnd_data/conditions.json` entries carry `key`, `document{name,key,display_name,publisher{name,key},gamesystem{name,key},permalink}`, `descriptions[{desc,document,gamesystem}]`, `icon` and `name`.
- `httpx` is a runtime dependency (`requirements.txt`). No new dependency is added.
- `scripts/ingest_species.py` and `app/reference/species.py` are the precedent for the normalize-then-load shape.

## 2. Test Spec (written first)

All tests run with `pytest -q` and need no network. The sync tests inject an `httpx.MockTransport`. The ingest tests build their input inline in `tmp_path`. No new fixture files are created.

The gate for every WP is `pytest -q`, `ruff check app tests scripts`, and `black --check app tests scripts`.

### WP-1: sync script and manifest (`tests/test_sync_open5e.py`)

| ID | Test | Expected |
|----|------|----------|
| T-01 | `ENDPOINTS` | The set equals the 12 dataset names: armor, backgrounds, classes, conditions, creatures, feats, magicitems, rules, sections, species, spells, weapons. |
| T-02 | paging | A mock transport serving two pages through an absolute `next` URL yields every result in order. `dnd_data/<name>.json` is a JSON array with the total count. |
| T-03 | manifest | After syncing two datasets, `_manifest.json` has `version: "1.0"` and one record per file with `dataset`, `endpoint`, `file`, `count`, and `fetched_at` (ISO 8601, UTC). Counts equal the array lengths. |
| T-04 | documents metadata | `/v2/documents/` is fetched into `_documents.json`. Each record keeps `key`, `name`, `publisher`, `gamesystem`, `permalink`, and the upstream license field verbatim. |
| T-05 | retry | HTTP 429 followed by 200 succeeds. Three consecutive 5xx responses raise `SyncError`. Attempts are bounded at 3 per request. |
| T-06 | atomic write | When a page fails mid-sync, the previous `dnd_data/<name>.json` is byte-identical afterwards. Writes go to a temporary file and then `os.replace`. |
| T-07 | scratch only | With `output_dir=tmp_path`, every written path is under `tmp_path`. Nothing is written under `app/`. |
| T-08 | injectable transport | `sync(output_dir, transport=...)` makes no real connection. A test with the default transport is not written. |

### WP-2: ingest core (`tests/test_ingest_open5e.py`)

Input is inline JSON in `tmp_path`, shaped like the snapshot.

| ID | Test | Expected |
|----|------|----------|
| T-09 | allowlist | Entries whose `document.key` is not in the dataset allowlist are dropped. The count of dropped entries is returned. |
| T-10 | projection | Each output record has exactly the keys in `PROJECTION["conditions"]`. `document`, the full `descriptions` list, and `icon` are absent. |
| T-11 | edition and third-party mapping | `srd-2014` gives `edition "5e"`, `third_party false`. `srd-2024` gives `edition "5.5e"`, `third_party false`. A third-party document gives `edition null`, `third_party true`. |
| T-12 | publisher and source | `publisher` is `document.publisher.name`. `source` is `document.display_name`. Neither is invented. |
| T-13 | source_key | `source_key` is the open5e `key` verbatim (for example `srd-2024_blinded`). |
| T-14 | id rule (E1, E2) | With "Blinded" in both SRDs and no reserved ids, the 5.5e entry gets `blinded` and the 5e entry gets `blinded-5e`. |
| T-15 | reserved ids | If the previously committed file maps a `source_key` to an id, that id is kept, even if the rule would assign another. |
| T-16 | overlay | `scripts/overlays/<dataset>.json` records that match a bulk id replace only the fields they provide. Bulk-only fields are kept. Overlay records with no bulk match are appended unchanged. |
| T-17 | id format and uniqueness | Every id matches `^[a-z0-9]+(-[a-z0-9]+)*$`. A duplicate id after the rules raises `ValueError`. |
| T-18 | deterministic render | Rendering is `json.dumps(records, indent=2, ensure_ascii=False) + "\n"`. Two ingests of the same input give identical bytes. |
| T-19 | budget check | `check_budget` raises `ValueError` when entries exceed 2,000 or rendered bytes exceed 2,000,000. Exactly 2,000 entries and exactly 2,000,000 bytes pass. Nothing is written on failure. |
| T-20 | consumer rule | `ingest("<dataset>")` raises `ValueError` when the dataset has no entry in `CONSUMERS`. |

### WP-3: attribution and budget CI (`tests/test_open5e_attribution.py`, `tests/test_reference_budget.py`)

| ID | Test | Expected |
|----|------|----------|
| T-21 | attribution content | `write_attribution` writes one section per allowlisted document that a committed dataset uses. Each section has the title, publisher, license, and permalink, and marks third-party documents. |
| T-22 | OGL gate | If an allowlisted document's license names OGL 1.0a and `scripts/licenses/OGL-1.0a.txt` is missing, ingest raises before writing. When the file exists it is copied to `app/reference/LICENSE-OGL.txt`. |
| T-23 | license missing | An allowlisted document with no license in `_documents.json` makes ingest raise `ValueError` that names the document key. |
| T-24 | CI budget | For every `app/reference/*.json`, the size is at most 2,000,000 bytes and the entry count is at most 2,000. The glob is non-empty and includes `species.json`. |
| T-25 | CI no entry dropped | For each open5e-ingested file, `load_entries` returns `len(raw JSON list)` entries with zero WARNING records. |
| T-26 | no runtime upstream | No file under `app/` contains `api.open5e.com`. No module under `app/` imports `scripts` or `sync_open5e`. |

### WP-4: pilot dataset and consumer route (`tests/test_reference_conditions_route.py`)

| ID | Test | Expected |
|----|------|----------|
| T-27 | checked-in file | `load_entries(CONDITIONS_PATH, Condition, "conditions")` returns `len(raw)` items with zero WARNING records. |
| T-28 | wiring | `build_services(...)["reference"]["conditions"]` has the same count. `tool.default_context["reference"]` is the same object. |
| T-29 | route | `GET /api/v1/reference/conditions` returns 200 with body keys exactly `{"conditions"}`. The items equal `[c.model_dump() for c in load_entries(...)]`. |
| T-30 | read-only | `POST` and `PUT` to that path return 405. |
| T-31 | missing key | Services without a `conditions` key return 503 with a JSON `detail`. |
| T-32 | regression | The species tests (T-09 to T-18 in SPEC-0011) and the whole suite pass without assertion changes. |

### WP-5: creatures budget measurement (`tests/test_creatures_budget_measurement.py`)

This test needs the local `dnd_data/creatures.json` snapshot. It is skipped with a reason when the file is absent. That is always the case in CI, because `dnd_data/` is gitignored.

| ID | Test | Expected |
|----|------|----------|
| T-33 | both SRDs | With the allowlist `{srd-2014, srd-2024}` and `CANDIDATE_CREATURE_FIELDS`, the rendered output is at most 2,000,000 bytes and at most 2,000 entries. The result is written to `dnd_data/_budget_creatures.json`. |
| T-34 | single SRD | The same measurement is recorded for `{srd-2014}` alone and for `{srd-2024}` alone. These results are written to the same output file. |
| T-35 | field check | Each name in `CANDIDATE_CREATURE_FIELDS` is either present in the snapshot or listed in the output as absent. No excluded field appears in the projection: `speed_all`, `saving_throws_all`, `skill_bonuses_all`, `modifiers`, `crossreferences`, `document`. |

The decision rule for T-33 and T-34 is in section 4.

## 3. Work Packages

Each WP MUST be implemented test-first. Each WP uses only `httpx`, the stdlib, and existing app modules.

### WP-1: sync script and manifest
- **Files:**
  - new `scripts/sync_open5e.py`
  - new `tests/test_sync_open5e.py`
- **Inputs:** `httpx` (runtime dependency). `dnd_data/` is gitignored.
- **Outputs:** a function `sync(output_dir: Path, transport: httpx.BaseTransport | None = None) -> dict` and a `main()` that calls it with `ROOT / "dnd_data"`. The module defines `ENDPOINTS`, `SyncError`, and the constant `BASE_URL = "https://api.open5e.com"`.
- **Acceptance criteria:**
  - Calls `GET {BASE_URL}/v2/<name>/`. Follows the absolute `next` URL until it is null. Assumption to check at the one manual live run: open5e v2 pagination returns `next` as an absolute URL. The live run is a manual step, not a test.
  - Retries 429 and 5xx responses up to 3 attempts in total, then raises `SyncError`.
  - Writes each dataset to `<name>.json` atomically (temporary file in the same directory, then `os.replace`).
  - Writes `_documents.json` from `GET /v2/documents/` and records the license field as the API returns it.
  - Writes `_manifest.json` with `version`, `synced_at`, and one record per file with `dataset`, `endpoint`, `file`, `count`, `fetched_at`.
  - Logs through `get_logger(__name__)` (PAT-CODE-001). Prints one summary line from `main()` only.
  - T-01 to T-08 pass.
- **Patterns used/created:** PAT-ARCH-007 (accepted).

### WP-2: ingest core
- **Files:**
  - new `scripts/ingest_open5e.py`
  - new `tests/test_ingest_open5e.py`
- **Inputs:** WP-1 output shape. A snapshot is a JSON array of open5e entries.
- **Outputs:** the constants and functions below.
  - `DOCUMENT_ALLOWLIST: dict[str, list[str]]`: for each dataset, the allowed document keys. The default is `["srd-2014", "srd-2024"]`.
  - `EDITION_BY_DOCUMENT = {"srd-2014": "5e", "srd-2024": "5.5e"}`. Any other document gets `edition null`.
  - `PROJECTION: dict[str, tuple[str, ...]]`. For the pilot: `("id", "name", "edition", "source", "publisher", "third_party", "source_key", "description")`.
  - `CONSUMERS: dict[str, str]`. For the pilot: `{"conditions": "GET /api/v1/reference/conditions"}`.
  - `ingest(dataset: str, snapshot_dir, out_path, overlay_path=None) -> int`, `project(...)`, `check_budget(records) -> str` (returns the rendered text).
  - `MAX_BYTES = 2_000_000` and `MAX_ENTRIES = 2_000`.
- **Acceptance criteria:**
  - Allowlist, projection, edition mapping, and publisher/source rules as tests T-09 to T-13.
  - **Id rule (E1, E2).** Ids are the slug of `name` (lowercase, non-alphanumeric runs become `-`). Claims are resolved in this priority order:
    1. Reserved: a `source_key` already mapped to an id in the previously committed file keeps that id.
    2. Overlay: a curated overlay record with the same id as the bulk slug.
    3. SRD 5.5e (`srd-2024`) entries take the bare slug.
    4. SRD 5e (`srd-2014`) entries take `<slug>-5e` when the bare slug is claimed.
    5. Third-party entries take `<slug>-<document key>` when the bare slug is claimed.
    A suffix collision raises `ValueError`.
  - **Overlay.** `scripts/overlays/<dataset>.json` is optional and committed. Matching records replace only the fields they provide. Unmatched records are appended unchanged. Consultant entries win on collision.
  - Deterministic render as T-18. `check_budget` as T-19. No file is written when the budget fails.
  - `ingest` raises for a dataset with no `CONSUMERS` entry (T-20).
  - T-09 to T-20 pass. The ingest imports from `app.reference` only as needed, and never imports `httpx`.
- **Patterns used/created:** PAT-ARCH-006 (accepted), PAT-ARCH-007 (accepted).

### WP-3: attribution generation and budget CI test
- **Files:**
  - `scripts/ingest_open5e.py` (add `write_attribution` and the OGL gate)
  - new `tests/test_open5e_attribution.py`
  - new `tests/test_reference_budget.py`
  - new `scripts/licenses/` directory. The OGL text file is **not** created by the implementer. It is supplied by the human.
- **Inputs:** WP-2 functions. `dnd_data/_documents.json` from WP-1.
- **Outputs:** `app/reference/ATTRIBUTION.md` (generated), and `app/reference/LICENSE-OGL.txt` (copied, only when required).
- **Acceptance criteria:**
  - `write_attribution` renders one section per allowlisted document used by a committed dataset: title (`display_name`), publisher, license, permalink, and a third-party marker. The file header says it is generated by `scripts/ingest_open5e.py`. Do not edit it by hand (T-21).
  - If a document's license names OGL 1.0a, ingest requires `scripts/licenses/OGL-1.0a.txt`. It raises before writing when that file is missing. The file is copied to `app/reference/LICENSE-OGL.txt` (T-22).
  - An allowlisted document with no license field raises `ValueError` that names the key (T-23).
  - `tests/test_reference_budget.py` contains the CI budget test T-24, the no-dropped-entries test T-25 for each open5e-ingested file, and the no-runtime-upstream test T-26.
  - This WP does not commit any dataset file. The budget CI test passes against the species file alone.
- **Patterns used/created:** PAT-ARCH-007 (accepted), PAT-ARCH-006 (accepted).

### WP-4: pilot dataset (`conditions`) and consumer route
- **Files:**
  - new `app/reference/conditions.json` (generated by `ingest_open5e.py`, not hand-edited)
  - new `app/reference/loader.py`: the shared loader extracted from `app/reference/species.py`
  - `app/reference/species.py`: delegates to `loader.py`. Its log event names and behaviour do not change.
  - new `app/reference/conditions.py`: the `Condition` pydantic model (`extra="forbid"`, same id slug pattern as `Species`) and `CONDITIONS_PATH`
  - `app/reference/ATTRIBUTION.md` (regenerated)
  - `app/services/build_services.py`: adds `reference["conditions"] = load_entries(...)`
  - `app/api/v1/reference.py`: new `GET /conditions` route
  - `app/schemas/v1.py`: new `ConditionListResp` with the `{"conditions": [...]}` envelope
  - new `tests/test_reference_conditions_route.py`
- **Inputs:** WP-2 and WP-3. The human has confirmed the pilot choice.
- **Outputs:** one committed dataset, one route, one shared loader.
- **Acceptance criteria:**
  - If `conditions` does not contain both `srd-2014` and `srd-2024`, the implementer stops and reports it. Do not fall back silently.
  - The shared loader is extracted because this is the second dataset (PAT-ARCH-006 rule 8). The loader logs `reference.unavailable` and `reference.entry_dropped` as before, with an added `dataset` field.
  - `ingest_open5e.py conditions` regenerates `app/reference/conditions.json` and `ATTRIBUTION.md`. The committed bytes match that output (test in T-27 may compare the bytes).
  - The route follows PAT-ARCH-005 (`response_model`, `{"conditions": [...]}`), is read-only, and returns 503 when the key is absent.
  - T-27 to T-32 pass.
- **Patterns used/created:** PAT-ARCH-006 (accepted, amended by the three clarifications), PAT-ARCH-005 (proposed, envelope only), PAT-ARCH-007 (accepted).

### WP-5: creatures budget measurement
- **Files:**
  - new `tests/test_creatures_budget_measurement.py`
  - `scripts/ingest_open5e.py`: adds the constant `CANDIDATE_CREATURE_FIELDS` and a `measure(dataset, snapshot_dir, documents) -> dict` function. It does not write to `app/reference/`.
- **Inputs:** `dnd_data/creatures.json`, `dnd_data/_documents.json` (local only).
- **Outputs:** `dnd_data/_budget_creatures.json`. This file is local and gitignored. It records, for each of `{srd-2014,srd-2024}`, `{srd-2014}`, and `{srd-2024}`: the entry count, the rendered bytes, the fields present, and the fields absent.
- **Acceptance criteria:**
  - `CANDIDATE_CREATURE_FIELDS` is a candidate list: `name`, `size`, `type`, `alignment`, `armor_class`, `hit_points`, `hit_dice`, `speed`, `ability_scores`, `saving_throws`, `skill_bonuses`, `damage_vulnerabilities`, `damage_resistances`, `damage_immunities`, `condition_immunities`, `senses`, `languages`, `challenge_rating_text`, `cr`, `actions`, `reactions`, `legendary_actions`, `traits`. Every name is verified against the snapshot. Names that are absent are recorded, not invented.
  - Excluded: `speed_all`, `saving_throws_all`, `skill_bonuses_all`, `modifiers` (derivable from `ability_scores`), `crossreferences`, and the `document` object (ADR-0007 F5). Source fields come from `document` as flat `source`, `publisher`, `edition`, `third_party`, and `source_key`.
  - T-33 to T-35 pass locally. They skip in CI with a clear reason.
  - This WP commits nothing. It reports the result to the human.
- **Patterns used/created:** PAT-ARCH-007 (accepted).

## 4. Other Details

**Measurement decision rule (applies to WP-5 and to any future dataset):**
- If `{srd-2014, srd-2024}` fits both limits, creatures MAY be committed to `app/reference/creatures.json` in a follow-up spec. That spec needs a named consumer.
- If it does not fit but one SRD does, the human chooses one ruleset for that dataset, or the fallback.
- If neither fits, creatures uses the ADR-0007 point 8 fallback, a gitignored read-only `reference.db`. That fallback is a new spec with its own pattern write-up.

**Edition and id naming for `dnd_data` documents:** the mapping above is the decision of this spec. The human confirms it before WP-2 is committed (BACKLOG follow-up).

**Risks:**
- The live API shape can differ from the fixtures (pagination, `license` field name). Mitigation: one manual live run of `sync_open5e.py` after WP-1. The test fixtures are written from the observed snapshot shape.
- A field dropped by projection needs a re-ingest from the snapshots, or a re-sync.
- The SRD and OGL text is copied into `conditions` `description`. Licensing: SRD 5.1 and 5.2 and OGL texts all allow it, provided attribution is kept. Attribution is generated and tested.
- The budget is tight for creatures. WP-5 decides with measurement, not estimate.

**Rollback plan:** revert the WP commit. Delete `scripts/sync_open5e.py`, `scripts/ingest_open5e.py`, `scripts/overlays/`, `scripts/licenses/`, `app/reference/conditions.json`, `app/reference/conditions.py`, `app/reference/loader.py`, and `app/reference/ATTRIBUTION.md`. Restore `app/reference/species.py` and `build_services.py`, and remove the route. `dnd_data/` stays gitignored and needs no change.

**Patterns applied/created:**
- PAT-ARCH-007 (accepted): bulk upstream sync and allowlist ingest. Created as `proposed` by the architect, accepted 2026-11-01.
- PAT-ARCH-006 (accepted): reference data. Three clarifications applied 2026-11-01 with human sign-off: (a) bulk snapshots may be gitignored local source copies; (b) the explicit 2 MB and 2,000-entry budget replaces "roughly thousands"; (c) a summary list plus GET by id is allowed for a dataset within budget but too heavy for one response.
- PAT-ARCH-005 (proposed): response envelope only.
- PAT-CODE-001 (accepted): `get_logger`.
- ADR-0007 (accepted), ADR-0006 (accepted, unchanged).

**Non-goals:**
- Any frontend change.
- Any runtime call to open5e.
- Creatures consumer, route, or tool. Creatures is measured only.
- Building the `reference.db` fallback.
- Ingesting open5e `species`. Species stays consultant-sourced under SPEC-0011.
- Ingesting classes, backgrounds, feats, armor, weapons, rules, sections, spells, or magic items.
- Allowlisting any third-party document in the pilot. The mechanism is in place and is tested, but no third-party document is enabled until a consumer needs one.
- A UI for attribution. Attribution becomes a MUST only if the app is distributed beyond the household (ADR-0007 revisit trigger).
- A git history rewrite for `dnd_data/`.
- Changing ADR-0006 or any accepted pattern beyond the three approved PAT-ARCH-006 clarifications.

**Open items for the human (recorded in BACKLOG follow-ups):**
1. Confirm the pilot `conditions` and its route.
2. Confirm the edition-disambiguation rule (section 3, WP-2).
3. Supply the full OGL 1.0a text at `scripts/licenses/OGL-1.0a.txt` before any OGL document is allowlisted.
4. Confirm whether `dnd_data/` is tracked in git at commit time.
