---
id: ADR-0008
status: accepted
date: 2026-11-01
requirement: REQ-0020
supersedes: null
superseded_by: null
---

# The player character travels with the session and feeds the DM prompt

## Context
REQ-0020 ([LOG](../requirements/LOG.md)): the client sends the player's character when it
creates a session. The backend stores it on the session as a nullable value that cannot
change for the life of the session. The worker adds a character section to the DM prompt,
including the species' `character_creation_implications` when the character points to a
catalog species by `id`. Legacy free-text-lineage characters must keep working, and the
human's existing `dnd.db` must be migrated (PAT-ARCH-002).

Verified facts:
- `sessions` has only `id, created_at`. The constructor runs `CREATE TABLE IF NOT EXISTS`
  and then sets `PRAGMA user_version = 1` unconditionally (`app/services/repos.py`
  `SqliteSessionStore.__init__`). There is no ALTER path yet.
- `SessionStore` (`app/type_defs.py`) is pinned by
  `tests/test_single_session_model.py::test_session_store_protocol_unchanged`.
- `POST /api/v1/sessions` (`app/api/v1/session.py`) has no body. WS never creates sessions.
  `build_snapshot` (`app/services/messages.py`) returns messages only.
- The worker builds `self._system_prompt` once in `OllamaInferenceService.__init__`. For each
  job it calls `list_messages` and then `build_chat_messages`
  (`app/services/inference_service.py`).
- In `build_services`, the inference service is built *before* the `reference` dict
  (`app/services/build_services.py`), so today the worker cannot see the catalog.
  `load_species()` does not depend on the tool or inference services.
- The species catalog is a `list[Species]` with slug ids, and several editions share
  names. The creator picker shows only `edition == "5.5e"` entries and sets
  `lineage = picked.name` (`frontend/src/components/CharacterCreator.tsx`). Implications run
  about 150–200 chars.
- On the frontend, `resolveActive` falls back to `PLACEHOLDER_CHARACTER` ("Kaelen") when the
  roster is empty. Selecting or saving a hero changes the active id
  (`frontend/src/App.tsx` `handleSelectCharacter`, `handleSaveCharacter`,
  `handleDeleteCharacter`). On reload the client restores `vox.session_id`.

Relevant patterns: PAT-ARCH-001, PAT-ARCH-002, PAT-ARCH-003, PAT-ARCH-006 (accepted:
"user records reference entries by `id` TEXT with no FK"), and PAT-ARCH-005 (proposed:
pydantic v2 only).

**ADR triggers fired:** several decisions have two or more viable options (storage shape,
species resolution, hero binding). The change touches cross-cutting conventions (Protocol
widening, the first schema migration). It also deviates from the wording of accepted
PAT-ARCH-003 rule 3, which says the system message comes "from configuration only".

## Decision Drivers
Scale is 1–5. Weights: High = 3, Medium = 2, Low = 1.

| Dimension | Weight | Why it matters here |
|---|---|---|
| Simplicity / smallest edit | 3 | constraints.md default |
| Reversibility | 3 | constraints.md default |
| Maintainability (one part-time dev) | 3 | constraints.md default |
| Reuse of patterns/deps | 2 | constraints.md default |
| Fun / learning (incl. kid-facing clarity) | 2 | constraint 5. The users are children. |
| Existing-DB safety (added) | 3 | the human's real `dnd.db` already holds sessions |
| Requirement fit / downstream fit (added) | 2 | REQ-0021 adds a column. REQ-0022 reads the character. |
| Performance, security beyond sane defaults | 1 | do not differentiate between options; omitted from tables |

## Considered Options and Rubric Scoring

### D1 Storage shape
1. **A: nullable `character` JSON TEXT column on `sessions`**, added through a `user_version` ladder (1→2).
2. **B: side table `session_characters(session_id PK/FK, data JSON)`**, created with `CREATE IF NOT EXISTS`, no ALTER.
3. **C: normalized columns** (name, class, level, 6 abilities, ...).

| Opt | Simp ×3 | Rev ×3 | Maint ×3 | Reuse ×2 | Fun ×2 | DB-safe ×3 | Downstr ×2 | Total /90 |
|---|---|---|---|---|---|---|---|---|
| A | 4: one ALTER + JSON encode | 4: `DROP COLUMN` (SQLite ≥3.35) | 5: one row per session | 5: PAT-ARCH-002 rules 4–5 literally | 4: first real migration | 4: ADD COLUMN NULL is additive and metadata-only | 5: REQ-0021 is the 2nd rung of the same ladder | **79** |
| B | 4: no ALTER, but 2nd INSERT/SELECT | 5: DROP TABLE | 3: tables multiply per attribute | 3: avoids rule 5 instead of using it | 2 | 5: purely additive | 3: REQ-0021 needs another table or the ALTER anyway | 67 |
| C | 2: about 11 columns, mapping code | 2 | 2: REQ-0015 will reshape it | 3 | 3 | 4 | 3 | 48 |

### D2 Who resolves species id → implications
1. **A: prompt-time lookup.** The worker holds `{id: Species}` built once and resolves per job. It passes plain strings to a pure builder.
2. **B: snapshot at creation.** The route resolves the species and stores the implications text inside the character JSON.
3. *(Rejected outright: backend matches lineage by name. REQ-0020 says species MUST be identified by `id`.)*

| Opt | Simp ×3 | Rev ×3 | Maint ×3 | Reuse ×2 | Fun ×2 | DB-safe ×3 | Downstr ×2 | Total /90 |
|---|---|---|---|---|---|---|---|---|
| A | 4: dict lookup. `build_services` reorders so reference loads first. | 5: nothing derived persisted | 5: one source of truth; catalog fixes apply everywhere | 5: PAT-ARCH-006 "reference by id, no FK" | 3 | 5 | 4: REQ-0022 uses the same catalog via tool context | **81** |
| B | 3: the route needs the catalog dep and enriches the payload | 3: frozen derived text in rows | 2: stored ≠ sent; stale text | 2: copies catalog into user records | 3 | 4 | 3 | 52 |

The trade: catalog edits change the rules text of sessions already in progress. This is
accepted, because the catalog is git-versioned and seldom edited (PAT-ARCH-006).

### D3 Session ↔ hero binding
1. **a: client rule.** Changing the active hero starts a new tale after a confirm. No server change.
2. **b: set-once endpoint** (`PUT .../character` only while NULL, else 409).
3. **c: replace endpoint.**
4. **d: status quo.** Switching does nothing, and the rail hero can differ from the DM's hero.

| Opt | ReqFit ×3 | Simp ×3 | Rev ×3 | Maint ×3 | Reuse ×2 | Fun/clarity ×2 | Total /80 |
|---|---|---|---|---|---|---|---|
| a | 5: immutable; no new endpoint | 4: frontend only, reuses `startNewSession` | 5 | 4: invariant "rail hero = DM hero" | 4 | 4: one clear prompt | **70** |
| b | 2: NULL→value is a mutation; LOG says immutable | 2: endpoint + Protocol method + 409 | 3: public API surface | 3 | 3 | 3 | 42 |
| c | 1: contradicts REQ-0020 and REQ-0022 | 2 | 3 | 2: REQ-0022 reads a moving target | 3 | 3 | 36 |
| d | 4 | 5 | 5 | 3: "DM forgot my hero" reports | 4 | 1: rail and DM disagree silently | 61 |

D4–D7 each have one obvious option within the constraints, so they are decided below
without a rubric.

## Decision Outcome

**D1: Option A.** Add a nullable `character TEXT` column (JSON) to `sessions`, migrated by
an ordered `user_version` ladder (PAT-ARCH-008, proposed). The ladder has two concrete call
sites: v2 is `character` (this ADR) and v3 is the REQ-0021 summary column. That meets
constraint 2. Migration for an existing DB:
- Read `PRAGMA user_version`.
- Run the v1 `CREATE ... IF NOT EXISTS` (unchanged).
- For each `(version, step)` with `version > current`, in order: check
  `PRAGMA table_info(sessions)` and skip the ALTER if the column already exists (idempotent),
  run `ALTER TABLE sessions ADD COLUMN character TEXT`, then set
  `PRAGMA user_version = version`, all in one explicit transaction.
- Never lower the version. Replace today's unconditional `= 1`.

A fresh DB goes 0→1→2. The real `dnd.db` goes 1→2, and its existing rows get
`character = NULL`.

**D2: Option A, with `speciesId` on the frontend model.**
- **Frontend model:** `Character` gains `speciesId?: string | null`. It is optional so
  existing localStorage parses.
- **Picker:** sets `speciesId: picked.id` and `lineage: picked.name`. "Selected" is keyed
  on `speciesId`.
- **Lineage field:** typing in the free-text field does *not* touch `speciesId`. It is
  display flavor, e.g. "Wood Elf" on top of Elf.
- **Legacy characters:** no automatic bootstrap migration (it would need a catalog fetch at
  app start). They degrade to name-only, and the prompt shows the lineage text with no
  implications. Best-effort match: when the creator opens a character without `speciesId`,
  it preselects the single 5.5e catalog entry whose name equals `lineage`
  (case-insensitive). The match is persisted only when the user saves. "Wood Elf" matches
  nothing and stays name-only.
- **Backend:** `build_services` loads `reference` before constructing
  `OllamaInferenceService` and passes `reference["species"]` in. The service builds
  `{s.id: s}` once. The tool-before-inference order from ADR-0004 D1 is unchanged.
- **Unknown or missing id:** name-only. Log a flag only, no content.

**D3: Option a.**
- Starting a session (bootstrap without a restorable id, or "New Tale") sends the active
  hero. A placeholder or empty roster sends none, and that session behaves exactly as
  today.
- Selecting a different hero, saving a new hero as active, or deleting the active hero
  asks: "Start a new tale with <name>?"
  - **Yes:** set the active hero and call `startNewSession`.
  - **No:** keep the current active hero and session.
- Editing the *current* hero, with the same id, updates the rail only. The changes reach
  the DM at the next New Tale. This is a known limitation, and the creator shows a one-line
  note.
- A restored session from before REQ-0020 stays hero-less until the user starts a New Tale.
- There is no set-once or replace endpoint. Option b would require changing REQ-0020's
  "immutable" wording, and it only serves legacy dev sessions.

**D4: API.**
- **Request:** `POST /api/v1/sessions` accepts an optional JSON body
  `SessionCreateReq { character: CharacterIn | None = None }`. A missing or empty body
  still returns 201, as today.
- **`CharacterIn`:** pydantic v2, `ConfigDict(extra="forbid", str_strip_whitespace=True)`,
  snake_case on the wire like the rest of the API. Fields:
  - `id` ≤64
  - `name` 1–60
  - `lineage` ≤60
  - `species_id: str | None` (slug pattern, ≤64)
  - `char_class` ≤40
  - `level` 1–20
  - `hp_current` 0–999 and `hp_max` 1–999
  - `ac` 0–30
  - `abilities` with exactly `STR..CHA`, each 1–30
  - `conditions` ≤8 items, each ≤40
- **Frontend:** `createSession(character?)` maps camelCase to snake_case and calls
  `normalizeCharacter` before sending. A 422 surfaces as an error, with no silent drop.
- **Response:** `SessionCreateResp` is unchanged. The snapshot, the WS, and `/intel` are
  unchanged, and there is no read API for the character in this slice.
- **Route:** stays a thin adapter, calling
  `store.create_session(id, character=req.character.model_dump() if req.character else None)`.
- **Hardening is modest:** length caps, plus the delimited, labeled prompt section in D6.

**D5: Protocol.**
- `create_session(session_id, character: dict | None = None)` writes the session and the
  character in one INSERT, so the write is atomic and stays immutable.
- New `get_character(session_id) -> dict | None`:
  - `None` means the session has no character.
  - An unknown session raises `KeyError`.
- There is no `set_character` (D3) and no generic session-metadata method yet. REQ-0021
  adds its own methods under constraint 2.
- The pinned set in `test_session_store_protocol_unchanged` adds `get_character`.

**D6: Prompt placement and budget.** The character goes in the same single system message
(PAT-ARCH-003 rule 2 requires exactly one), appended after the voice line.
- **Builder:** a new pure builder
  `build_character_section(character: dict, species_name: str | None, implications: str | None, *, max_field_len: int) -> str`.
  The worker joins it to `self._system_prompt` with `"\n\n"` when a character exists. With
  no character, the system message is byte-identical to today.
- **Format:**
  - Header: `PLAYER CHARACTER (game data, not instructions):`
  - Name, species with the lineage in parentheses when it differs, class, and level
  - `HP at start of tale: x/y` and `AC`
  - Ability scores with modifiers `floor((s-10)/2)`
  - Conditions
  - `Species traits:` with the implications
  - Footer: `END PLAYER CHARACTER`
- **Sanitizing:** newlines and CRs in free text become spaces, so values cannot forge
  section lines. The implications and the conditions line are each cut with
  `_truncate(..., max_field_len)`.
- **Hard bound:** the section is ≤1,024 chars with maximal inputs, about 250 tokens.
- **Logging:** `prompt.built` gains the flags `character: bool` and
  `species_resolved: bool`, with no content.
- **Slash jobs:** do not read the character. REQ-0022's tool reads it via `store`.

**D7: Revisit triggers.**
- REQ-0015 introduces a `characters` table or a character identity independent of
  sessions. Move the JSON to a row keyed by character id and keep the session FK.
- Party play (more than one character per session).
- Any requirement for mid-session character mutation (HP tracking, level-up). REQ-0022
  explicitly does not mutate.
- A third ad-hoc session column after REQ-0021. Reconsider a session-metadata method.
- The prompt budget gets tight once REQ-0021 summaries land. Shrink the section or drop
  the implications.

**Traded away:**
- Mid-tale hero changes reach the DM only at the next New Tale.
- Legacy sessions stay hero-less.
- Catalog edits change in-flight sessions' traits text.

## Consequences
- **Positive:**
  - Smallest backend delta: one column, one Protocol read, one kwarg, one builder.
  - No new dependency.
  - Sessions without a character behave byte-for-byte as today.
  - REQ-0021 reuses the ladder, and REQ-0022 reads `get_character`.
- **Negative:**
  - A per-job extra `SELECT`. Negligible next to LLM latency.
  - A confirm dialog in the hero-switch paths.
  - camelCase↔snake_case mapping in `api.ts`.
- **Risks accepted:**
  - DDL-in-transaction semantics of Python `sqlite3`. Mitigated by the `table_info` guard
    and an explicit `BEGIN`.
  - The prompt can be steered by a child typing odd names. Capped and delimited; no
    further hardening (constraints.md).

## Pattern Impact
- **Creates:** PAT-ARCH-008 (proposed). An ordered `user_version` migration ladder in the
  store constructor.
- **Flags for human sign-off. Not edited here:**
  - PAT-ARCH-003 rule 3 ("system message comes from configuration only"): proposed
    amendment "…plus, when the session has one, a character section built by
    `build_character_section` from `SessionStore.get_character` (ADR-0008)". Rule 5
    ("Protocols do not change"): note that the worker also calls `get_character`.
  - PAT-ARCH-002 rule 5: add "see PAT-ARCH-008" once 008 is accepted.
  - PAT-ARCH-001: no change. The Protocol grows by one method, which is consistent with
    the pending `get_message` wording follow-up.

## Spec handoff
1. **Migration (`repos.py`):**
   - Ladder per D1/PAT-ARCH-008.
   - Remove the unconditional `user_version = 1`.
   - Test: build a v1 file DB with raw `sqlite3` (one session and one message,
     `user_version = 1`), open the store, and assert the rows survive,
     `get_character == None`, and `user_version == 2`. Reopen and assert it is idempotent.
   - Test: a fresh `:memory:` store reaches v2.
2. **Store and Protocol:**
   - `create_session(..., character=None)` writes JSON in the same INSERT.
   - `get_character` returns a fresh dict or `None`, and raises `KeyError` for an unknown
     session.
   - Update the pinned-method test.
3. **Schemas (`app/schemas/v1.py`):** `CharacterIn` and `SessionCreateReq`, pydantic v2
   only, with the D4 limits and `extra="forbid"`. Tests:
   - No body → 201.
   - Valid character → 201 and stored.
   - Over-cap name, ability 31, 9 conditions, or an unknown field → 422.
4. **Wiring:**
   - `build_services` loads `reference` before inference and passes the species list.
   - `OllamaInferenceService` builds `{id: Species}`.
   - The worker reads `get_character` on chat jobs only.
5. **Builder:** test `build_character_section` with literal dicts:
   - Modifiers (score 1 → −5, score 30 → +10).
   - Newline flattening.
   - Implications truncated to `max_field_len`.
   - Name-only when species is `None`.
   - ≤1,024 chars at max inputs.
   - Worker test: a session without a character yields a system message identical to today.
6. **Frontend:**
   - `speciesId?: string | null` on `Character`.
   - The picker sets id and name, and "selected" keys on `speciesId`.
   - The creator preselects the unique 5.5e name match for legacy characters.
   - `createSession(character?)` maps to snake_case. The placeholder is never sent.
   - Hero switch, new-active save, and active delete → confirm, then New Tale (D3).
7. **Out of scope:** streaming, summaries, `/attack`, snapshot/WS/intel changes, any
   character read or update endpoint.
