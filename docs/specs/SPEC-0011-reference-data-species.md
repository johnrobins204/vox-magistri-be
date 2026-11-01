---
id: SPEC-0011
requirement: REQ-0018
adr: ADR-0006
status: done
date: 2026-10-18
---

# SPEC-0011: Curated reference data, species catalog

## 1. Requirement

Restated in [docs/requirements/LOG.md](../requirements/LOG.md) as REQ-0018.

Normative summary:
- Each curated dataset MUST be one normalized JSON file under `app/reference/`, with snake_case keys, a unique slug `id`, separate `edition` and `publisher` fields, and an explicit `third_party` flag.
- The consultant delivery `docs/from_consultant/dnd_all_species_full_list.json` MUST stay unmodified and MUST NOT be read by the app. It is provenance only.
- Normalization MUST run once at ingest (`scripts/ingest_species.py`), in a reviewable commit.
- The app MUST load each dataset once at startup. A missing or invalid file MUST log one warning and yield an empty list. Entries that fail validation MUST be dropped with one warning each.
- The read-only route `GET /api/v1/reference/species` MUST return `{"species": [...]}`.
- Reference data MUST NOT be stored in SQLite tables.
- The character creator MUST offer a two-tier species picker: the 10 base `5.5e` species first, then a browse-all view with descriptions and character-creation implications.
- Entries MUST be short summaries, not verbatim rules text.

Decisions carried in from the human sign-off on 2026-10-18:
- ADR-0006 and PAT-ARCH-006 are `accepted`.
- Edition labels `5e` and `5.5e` are kept. The delivered `3rd Party` label is not an edition. Those entries get `edition: null` and `third_party: true`.
- Hollow One is corrected at ingest to `third_party: false`, `edition: "5e"`, `publisher: "Wizards of the Coast"`, and `source: "Explorer's Guide to Wildemount"`. The delivered source was `Explorer's Guide to Wildemount (Darrington Press / WotC)`.
- The LLM-assisted character-creator features and the classes and backgrounds datasets are out of scope.

Delivered data: 68 entries, which is 10 `5.5e` (lines 3-75), 48 `5e` (lines 83-459), and 10 `3rd Party` (lines 467 onward). After the Hollow One correction, the target counts are 10 `5.5e`, 49 `5e`, and 9 with `edition: null`.

## 2. Test Spec (written first)

Backend tests run with `pytest -q`. The frontend has no test runner (see [frontend/package.json](../../frontend/package.json)). Frontend checks are the build gate plus the manual checks F-01 to F-07. Adding a frontend test runner is out of scope because it would be a new dependency.

### WP-1: normalized file and ingest script (`tests/test_reference_species_ingest.py`)

| ID | Test | Expected |
|----|------|----------|
| T-01 | `normalize()` on the consultant file | 68 entries. Each entry has exactly the keys `id, name, edition, source, publisher, third_party, creature_type, description, character_creation_implications`. |
| T-02 | ids and names | All ids are unique and match `^[a-z0-9]+(-[a-z0-9]+)*$`. `Deep Gnome (Svirfneblin)` gives id `deep-gnome-svirfneblin`. `Half-Elf (Legacy 2014)` gives name `Half-Elf` and id `half-elf`. `Half-Orc (Legacy 2014)` gives name `Half-Orc` and id `half-orc`. |
| T-03 | Hollow One correction | `edition == "5e"`, `third_party is False`, `publisher == "Wizards of the Coast"`, `source == "Explorer's Guide to Wildemount"`. |
| T-04 | edition and third-party counts | `"5.5e"` count is 10. `"5e"` count is 49. `None` count is 9. `edition is None` if and only if `third_party is True`. No entry has the value `"3rd Party"`. |
| T-05 | publisher is never invented | For every entry except Hollow One, `publisher` is `None` or appears verbatim in the delivered Source text. Hollow One is covered by T-03. |
| T-06 | text is not rewritten | `description`, `character_creation_implications`, and `creature_type` equal the delivered text for every entry. |
| T-07 | duplicate ids fail the ingest | `normalize()` raises `ValueError` when two delivered entries produce the same id. |
| T-08 | checked-in file is reproducible | The bytes of `app/reference/species.json` equal the script output for the consultant file. |

### WP-2: model and fail-soft loader (`tests/test_reference_species_loader.py`)

Mirror the `load_voice_configs` tests in `tests/test_prompt_builders.py` (T-18 to T-22). Log capture uses `caplog` on the `get_logger` logger name.

| ID | Test | Expected |
|----|------|----------|
| T-09 | checked-in file | `load_species()` returns 68 `Species` objects and emits no WARNING. |
| T-10 | missing file | Returns `[]`. Exactly one WARNING with message `reference.unavailable`. |
| T-11 | invalid JSON | Returns `[]`. One WARNING `reference.unavailable`. |
| T-12 | top-level JSON is not a list | Returns `[]`. One WARNING `reference.unavailable`. |
| T-13 | one bad entry among two good ones | Returns the 2 good entries. One WARNING `reference.entry_dropped` for the bad one. The file text is not in any log record. |
| T-14 | extra key in an entry | Entry is dropped (`extra="forbid"`), with one WARNING. |
| T-15 | `edition: "3rd Party"` | Entry is dropped, with one WARNING. |
| T-16 | duplicate id in the file | The second entry is dropped with one WARNING. The first is kept. |
| T-17 | id not a slug (for example `"Aasimar"`) | Entry is dropped, with one WARNING. |
| T-18 | CI hard-fail guard | For the checked-in file, the loaded count equals `len(raw JSON list)` and there are zero WARNINGs. This makes a bad checked-in file fail CI even though runtime is fail-soft. |

### WP-3: wiring (`tests/test_reference_wiring.py`)

| ID | Test | Expected |
|----|------|----------|
| T-19 | `build_services(...)` | `services["reference"]["species"]` has 68 entries. |
| T-20 | tool context | `services["tool"].default_context["reference"] is services["reference"]` (same object). |
| T-21 | regression | The full existing suite (`pytest -q`) passes with no assertion changes. |

### WP-4: route (`tests/test_reference_route.py`)

| ID | Test | Expected |
|----|------|----------|
| T-22 | `GET /api/v1/reference/species` via the `client` fixture | 200. Body keys are exactly `{"species"}`. 68 items, each with the 9 keys from T-01. |
| T-23 | round trip | `resp.json()["species"] == [s.model_dump() for s in load_species()]`. |
| T-24 | read-only | `POST` and `PUT` to the same path return 405. |
| T-25 | no detail or other datasets yet | `GET /api/v1/reference/classes` returns 404. `GET /api/v1/reference/species/aasimar` returns 404. |
| T-26 | services without the `reference` key | 503 with a JSON `detail` field. Built with `create_app(services={...})` and no `reference` key. |
| T-27 | empty catalog | Services with `{"reference": {"species": []}}` return 200 and `{"species": []}`. |
| T-28 | SQLite holds no reference tables | After `make_default_repos(f"sqlite:///{tmp_path}/t.db")` and an app build, `sqlite_master` table names contain neither `species` nor `reference`. |

### WP-5 and WP-6: frontend (manual, build gate)

Gate for both: `cd frontend && npm run build` (`tsc -b && vite build`) passes.

| ID | Check | Expected |
|----|-------|----------|
| F-01 | backend running, open the character creator, Forge New Hero | The 10 base species from the 5.5e entries appear as chips, in file order. |
| F-02 | backend stopped | The creator shows "Species list unavailable". The free-text lineage input still works. No uncaught error in the console. |
| F-03 | click a species chip | The lineage input is set to the species `name`. The saved hero shows it in the roster subline. |
| F-04 | existing hero with lineage `Wood Elf` | Loads and edits unchanged. Lineage stays as typed. |
| F-05 | "Browse all species" | Lists 68 entries. The search box filters by name, case-insensitive. The edition filter (All, 5.5e, 5e, Third-party) works. |
| F-06 | third-party entries | Show a "Third-party" badge. Show the publisher only when it is non-null. Hollow One shows no badge. |
| F-07 | Escape | Closes the browser only. The creator stays open. "Use this species" sets lineage to the species name and closes the browser. |

## 3. Work Packages

Each package MUST be implemented test-first. Gate per package: `pytest -q`, `ruff check app tests`, `black --check app tests`. WP-5 and WP-6 also need `npm run build`. Run ruff and black on `scripts/` locally.

### WP-1: normalized species file and ingest script
- Depends on: none.
- Files:
  - new `scripts/ingest_species.py`. It is stdlib-only, exposes `normalize(entries) -> list[dict]`, and has a `main()` that writes the file.
  - new `app/reference/species.json`.
  - new `tests/test_reference_species_ingest.py`.
- Behavior:
  - `id` is the slug of the normalized `name`. Duplicates raise `ValueError`.
  - Name qualifiers `(Legacy 2014)` are stripped from `name`. The `source` field is kept as delivered.
  - `edition` is `5e` or `5.5e` as delivered. `3rd Party` maps to `None` with `third_party: true`.
  - `publisher` is taken from a publisher parenthetical in the delivered Source only, or from the explicit OVERRIDES table (Hollow One). Otherwise it is `None`.
  - Text fields are copied as delivered.
  - Hollow One is handled through the OVERRIDES table, keyed by the delivered name.
- Acceptance:
  - T-01 to T-08 pass.
  - The commit message notes the Hollow One correction and that entries are summaries.
  - The author confirms the delivered text is summary-level, not verbatim rules text.

### WP-2: model and fail-soft loader
- Depends on: WP-1.
- Files:
  - new `app/reference/__init__.py` (empty).
  - new `app/reference/species.py`. It defines the `Species` Pydantic model (`ConfigDict(extra="forbid")`, `id` slug pattern, `edition: Literal["5e", "5.5e"] | None`, `publisher: str | None`, `third_party: bool`, and the text fields). It also defines the `SPECIES_PATH` constant and `load_species(path=SPECIES_PATH) -> list[Species]`.
  - new `tests/test_reference_species_loader.py`.
- Behavior:
  - Mirrors `load_voice_configs`. The failure events are `reference.unavailable` (with a `reason` of `missing`, `invalid_json`, or `not_list`) and `reference.entry_dropped` (with `index` and `reason`, never file content).
  - Uses `get_logger(__name__)`.
- Acceptance: T-09 to T-18 pass.

### WP-3: wiring into services and tool context
- Depends on: WP-2.
- Files:
  - `app/services/build_services.py`. Add `reference = {"species": load_species()}` to the services dict. Set `tool_service.default_context["reference"] = reference`.
  - `app/deps.py`. Add `get_reference()`, which returns `get_services().get("reference")`.
- Behavior: the catalog is loaded once, when services are built at startup. No tool reads it in this package. It is only placed in context.
- Acceptance: T-19 to T-21 pass.

### WP-4: read-only route and response model
- Depends on: WP-3.
- Files:
  - new `app/api/v1/reference.py`. It defines `router = APIRouter(prefix="/api/v1/reference", tags=["reference"])` and `GET /species` with `response_model=SpeciesListResp`.
  - `app/schemas/v1.py`. Add `SpeciesListResp(BaseModel)` with `species: list[Species]`, written with pydantic v2 `ConfigDict`. Leave existing models unchanged.
  - `app/factory.py`. Include the reference router.
- Behavior:
  - When `get_reference()` is None, return 503 with `detail`.
  - Otherwise return `{"species": catalog["species"]}`, which can be empty.
  - The route MUST NOT touch the session store.
- Acceptance: T-22 to T-28 pass.

### WP-5: frontend types, API call, tier-1 picker
- Depends on: WP-4. Can start in parallel against the contract below.
- Contract (`frontend/src/types.ts`):
  ```ts
  export interface Species {
    id: string
    name: string
    edition: '5e' | '5.5e' | null
    source: string
    publisher: string | null
    third_party: boolean
    creature_type: string
    description: string
    character_creation_implications: string
  }
  ```
- Files:
  - `frontend/src/types.ts`. Add `Species`, plus `SpeciesListResp { species: Species[] }`.
  - `frontend/src/lib/api.ts`. Add `getSpecies(): Promise<Species[]>`. Use the same request helper as `getIntelStatus`, and send `authHeaders` only if `getIntelStatus` does.
  - `frontend/src/components/CharacterCreator.tsx`. Replace the hardcoded `LINEAGE_SUGGESTIONS` datalist with a chip list of the 10 `edition === '5.5e'` species. Fetch once each time the editor opens. Clicking a chip sets `lineage` to the species `name`. Keep the free-text lineage input. Add a "Browse all species" button that calls an `onBrowseAll` callback, which WP-6 wires up.
- Behavior:
  - Fetch failure shows "Species list unavailable" and nothing else breaks.
  - The `Character` shape in `lib/character.ts` is unchanged. Heroes saved in localStorage keep working.
- Acceptance: `npm run build` passes. F-01 to F-04 pass.

### WP-6: browse-all species view
- Depends on: WP-5.
- Files:
  - new `frontend/src/components/SpeciesBrowser.tsx`. Props: `species: Species[]`, `onPick(species)`, `onClose()`.
  - `frontend/src/components/CharacterCreator.tsx`. Mount the browser when the button is clicked. The creator ignores Escape while the browser is open.
- Behavior:
  - Shows name, edition badge, source, publisher (if non-null), creature type, description, and character-creation implications.
  - Search and edition filter are client-side.
  - "Use this species" calls `onPick`, which sets lineage and closes the browser.
- Acceptance: `npm run build` passes. F-05 to F-07 pass.

## 4. Other Details

### Route contract
- `GET /api/v1/reference/species` returns `200 {"species": [Species, ...]}`.
- 503 with `detail` if the reference service is not wired.
- No auth change in this package. REQ-0009 owns auth. This is a public read-only catalog, like `/intel` status.
- PAT-ARCH-005 is still `proposed`, and this route follows it. If REQ-0010 changes the envelope, the route follows. This spec does not modify PAT-ARCH-005.

### Logging
- `reference.unavailable` and `reference.entry_dropped` are WARNING events through `get_logger`.
- No file text or entry content is logged. Only counts, indexes, and reasons.

### Settings and config
- No new `settings.json` key. `SPECIES_PATH` is a code constant, like `VOICE_CONFIGS_PATH`, because the file is a packaged dataset and not a deployment setting.

### Persistence
- No SQLite tables. The `Species` model and the file are the storage (ADR-0006). User records will reference entries by `id` TEXT with no FK (PAT-ARCH-006), and that happens in REQ-0015.

### Non-goals
- LLM-assisted character-creator features.
- Classes and backgrounds datasets.
- A `GET /species/{id}` detail route.
- A shared generic loader. The loader is extracted only once a second dataset exists (ADR-0006).
- Auth on the reference route.
- A frontend test runner.
- Updating `docs/api/openapi.json` (REQ-0010).

### Patterns applied
- ADR-0006 (accepted): file-canonical reference data.
- PAT-ARCH-006 (accepted): normalize at ingest, load once, fail-soft at runtime, fail-hard in CI, read-only routes.
- PAT-ARCH-003 (accepted): fail-soft loader precedent (`load_voice_configs`). Config loaded once with fallback and a `get_logger` warning.
- PAT-ARCH-005 (proposed): explicit response model and envelope.
- PAT-CODE-001 (accepted): logging through `get_logger`.

### Patterns created
- None in this spec. No new pattern is needed; PAT-ARCH-006 covers the strategy.

### Risks
- Silent data loss at runtime. Mitigated by T-18 (CI fails on a bad file) and the WARNING logs.
- Consultant text is not verbatim-checked. Mitigated by the summary-only rule and the WP-1 commit checklist.
- `docs/from_consultant/` becomes public if the repo does. The author must confirm the delivered text is summary-level.
- Route envelope may change under REQ-0010. Mitigated by following PAT-ARCH-005 now and noting the dependency.

### Rollback
- Revert the commits for each package. Nothing is persisted, so no migration is needed. Removing `app/reference/` and the route restores the prior state.

### Open questions for the human
- Hollow One: confirm `edition: "5e"` (derived from the book, not in the delivery) and the publisher "Wizards of the Coast".
- Edition is `null` for the 9 third-party entries. The consultant gave no edition. Confirm, or a curator should fill them in.
- Publisher is `null` for every entry except Hollow One unless the source names one. Confirm that "no invented publisher" is the rule.
- The character creator has no species list yet beyond the lineage datalist. The picker mounts in `CharacterCreator.tsx`. Confirm this is the intended mount point.
- ADR-0006 `requirement:` still reads `pending`. Set it to REQ-0018 if desired. It was left unchanged on purpose.
