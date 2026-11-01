---
id: SPEC-0013
requirement: REQ-0020
adr: ADR-0008
status: done
date: 2026-11-01
---

# SPEC-0013: The DM knows my hero (character on the session, fed into the DM prompt)

## 1. Requirement

Restated in [docs/requirements/LOG.md](../requirements/LOG.md) as REQ-0020. Decisions D1-D7 and the "Spec handoff" list in [ADR-0008](../adr/0008-character-on-session.md) are the contract. This spec carries them and does not re-decide them.

Normative summary:
- The client MUST send the player's character on session create (`POST /api/v1/sessions`).
- The backend MUST store it on the session as a nullable value that is immutable for the session's life. A session without a character MUST behave exactly as today. The system message for such a session MUST be byte-identical to today's.
- The inference worker MUST add a character section to the DM prompt, built by a pure builder (PAT-ARCH-003). The section goes into the one system message.
- When the character carries a catalog species `id`, the section MUST include that species' `character_creation_implications`, taken from the in-memory reference catalog. Species MUST be identified by catalog `id`. Legacy free-text-lineage characters MUST keep working (name only, no implications).
- The schema change MUST migrate existing databases in place (PAT-ARCH-002, PAT-ARCH-008). The human's real `dnd.db` already holds sessions.
- The frontend MUST send the active hero when it starts a session, and MUST never send the placeholder hero "Kaelen". Switching the active hero, saving a new hero as active, and deleting the active hero MUST ask "Start a new tale with <name>?" (ADR-0008 D3).
- Streaming, summaries, the attack tool, and campaign/quest/scene state MUST NOT change.

Decisions carried in from the human sign-off on 2026-11-01:
- ADR-0008 and PAT-ARCH-008 are `accepted`. PAT-ARCH-003 rules 3 and 5 were amended (the character section lives in the single system message; the worker also calls `get_character`). PAT-ARCH-002 rule 5 points at PAT-ARCH-008.
- Sessions from before this change stay hero-less until the user starts a New Tale. There is no set-once endpoint.
- Old characters with free-text lineage get the matching 5.5e species PRESELECTED when opened in the creator. It is saved only if the user saves.
- The placeholder hero "Kaelen" is NEVER sent to the backend.
- Editing the current hero shows a note that changes apply at the next New Tale (no automatic new tale). Switching the active hero, saving a new hero as active, or deleting the active hero asks "Start a new tale with <name>?". Yes starts a new tale. No keeps the current hero and tale.
- pydantic v2 idioms ONLY in new code (`ConfigDict`, `model_dump`). REQ-0023 cleans up the v1 leftovers separately. Do not touch the existing `class Config` blocks.

### Verified facts (checked against the tree on 2026-11-01)

Backend:
- `SqliteSessionStore.__init__` ([app/services/repos.py](../../app/services/repos.py) L47-L77) runs three base `CREATE ... IF NOT EXISTS` statements inside `with self._conn:` and then `PRAGMA user_version = 1` (L76) unconditionally. `_recover_interrupted()` runs last. `sessions` has only `id, created_at`.
- `create_session(self, session_id)` is at repos.py L111. `SessionStore.create_session` is at [app/type_defs.py](../../app/type_defs.py) L8. The Protocol already has `get_message` (L16).
- `tests/test_single_session_model.py::test_session_store_protocol_unchanged` pins the Protocol method set at 7 names, including `get_message`. `tests/test_sqlite_store.py::test_schema_created_on_open` asserts `version == 1` (L267). This assertion becomes wrong after WP-1 (see T-07).
- `POST /api/v1/sessions` is at [app/api/v1/session.py](../../app/api/v1/session.py) L25-L35. It takes no body and has no `require_local_token` dependency. It calls `store.create_session(session_id)`, logs `session.created`, and returns `SessionCreateResp`. The file still has a pydantic v1 `payload.dict()` call at L163. Leave it alone (REQ-0023).
- [app/schemas/v1.py](../../app/schemas/v1.py) starts with `from __future__ import annotations` and imports `BaseModel, ConfigDict, Field, constr` (L6). `SessionCreateResp` (L16-L26) uses a v1 `class Config`. Leave it alone.
- [app/intelligence/prompt_builders.py](../../app/intelligence/prompt_builders.py) already uses `get_logger`. It has `_truncate(s, n)` (L69, returns at most `n` chars, ending in `…` when cut), `build_system_prompt` (L170) and `build_chat_messages` (L187). These are pure and do no I/O.
- [app/services/inference_service.py](../../app/services/inference_service.py): `OllamaInferenceService.__init__(self, settings, tool_service=None)` is at L47. It builds `self._system_prompt` once (L59) and starts the worker thread inside `__init__` (L75). The chat branch of the worker calls `job.store.list_messages` (L213) and logs `prompt.built` (L223) with `history_count` and `message_count`. Slash jobs take a different branch and never call the chat builder.
- [app/services/build_services.py](../../app/services/build_services.py): the inference service is built at L31, before `reference` is built (L34). So today the worker cannot see the catalog. `load_species()` depends on neither the tool nor the inference service.
- `settings.app.max_turns` defaults to 6 and `settings.app.max_field_len` to 240 ([app/config.py](../../app/config.py) L39-L40).
- The catalog entry `elf` ([app/reference/species.json](../../app/reference/species.json) L36) is a `5.5e` entry. Its `character_creation_implications` is about 190 characters. The `Species` model is `extra="forbid"` with a slug `id` (`^[a-z0-9]+(-[a-z0-9]+)*$`).
- CORS allows all headers and methods for the Vite origins ([app/factory.py](../../app/factory.py) L22-L28). A JSON POST from the frontend passes preflight, so `app/factory.py` needs no change.
- Every existing worker test uses a real `SqliteSessionStore` or a subclass of it (`_SpyStore` in `tests/test_inference_reply.py`). No test fakes the `SessionStore` Protocol. So the worker calling `get_character` breaks no existing fake.
- `tests/session_helpers.py::make_stub_service(tool_service=None, **settings_kwargs)` (L14-L21) passes the extra kwargs straight into `Settings(...)`. A new `species` argument therefore needs an explicit parameter (WP-5).
- The full-suite baseline is 288 passed, 0 failed.

Frontend (no test runner; the gate is `npm run build` plus the manual F-checks):
- `Character` ([frontend/src/lib/character.ts](../../frontend/src/lib/character.ts)) has no species id. `normalizeCharacter` (L59-L76) clamps abilities to 3-20 and spreads `...c`, so an extra optional field survives it. It does not cap string lengths. Conditions are split from a 120-character input, so one condition can be longer than the backend's 40-character cap.
- `PLACEHOLDER_CHARACTER` has id `placeholder-hero` and name "Kaelen". `resolveActive` ([frontend/src/lib/roster.ts](../../frontend/src/lib/roster.ts) L65) returns the active hero, else `roster[0]`, else the placeholder.
- `createSession()` ([frontend/src/lib/api.ts](../../frontend/src/lib/api.ts) L27) takes no argument and sends no body. `parseJson` (L11) passes `body.detail` straight to `new Error(...)`. For a FastAPI 422 that is an array, so the message would read "[object Object]".
- [frontend/src/App.tsx](../../frontend/src/App.tsx) calls `createSession()` in two places: the bootstrap effect (L81) and `startNewSession` (L183-L187). `handleSaveCharacter` (L214), `handleSelectCharacter` (L222) and `handleDeleteCharacter` (L227) change the active hero with no confirmation. The creator is mounted with `activeId={activeCharacterId}` (L282), the raw pointer. That value can be null while the rail shows `roster[0]`.
- [frontend/src/components/CharacterCreator.tsx](../../frontend/src/components/CharacterCreator.tsx): the chip `onClick` and `pickSpecies` (L107) both set only `lineage` (to `s.name`). The "selected" state is `editing.lineage === s.name` (L282-L283). Species are fetched once each time the editor opens.

### Gates and open decisions

| ID | Gate | State |
|----|------|-------|
| G-1 | ADR-0008 accepted by the human | DONE (2026-11-01) |
| G-2 | PAT-ARCH-008 accepted; PAT-ARCH-003 rules 3 and 5 and PAT-ARCH-002 rule 5 amended | DONE (2026-11-01) |
| G-3 | Remaining human gates | None. The assumptions A-1 to A-10 in section 4 are spec-level defaults. The human MAY overrule them at review. |

Backend work packages (WP-1 to WP-6) have no frontend dependency. Frontend packages (WP-7, WP-8) depend on the WP-3 contract. Do not ship WP-7 without WP-8: after WP-7 alone, switching heroes would not start a new tale.

## 2. Test Spec (written first)

Backend tests run with `pytest -q` and need no network or Ollama. They use the `app` / `client` fixtures (real app, `:memory:` SQLite) and the `make_stub_service` / recording-`client.chat` style of `tests/test_prompt_pipeline.py`. The frontend has no test runner (adding one would be a new dependency). Frontend checks are the build gate plus the manual checks F-01 to F-14.

Gate for every backend WP:
```
./venv-dnd-server/bin/pytest -q
./venv-dnd-server/bin/python -m ruff check app tests scripts
./venv-dnd-server/bin/python -m black --check app tests scripts
```
Frontend WPs add `cd frontend && npm run build`. Baseline: 288 passed, 0 failed. Any new failure is the WP's fault.

Shared literal used by several tests (call it `ARIA`):
```python
ARIA = {
    "id": "hero-1", "name": "Aria", "lineage": "Wood Elf", "species_id": "elf",
    "char_class": "Ranger", "level": 3, "hp_current": 24, "hp_max": 28, "ac": 14,
    "abilities": {"STR": 12, "DEX": 16, "CON": 13, "INT": 11, "WIS": 15, "CHA": 10},
    "conditions": ["Blessed"],
}
```

### WP-1: migration ladder (`tests/test_store_migration.py`)

The old-version DB fixture is built with raw `sqlite3` in `tmp_path`. It uses the literal v1 DDL (the three base statements as they are today), one session `s-old`, one message `m-old` (all columns filled), and `PRAGMA user_version = 1`.

| ID | Test | Expected |
|----|------|----------|
| T-01 | Open the old v1 file DB with `SqliteSessionStore(path)` | `list_messages("s-old")` ids equal `["m-old"]`. Raw `PRAGMA table_info(sessions)` lists `character`. Raw `SELECT character FROM sessions WHERE id='s-old'` is NULL. Raw `PRAGMA user_version` is 2. Exactly one INFO record `store.migrated` has `from == 1` and `to == 2`. |
| T-02 | Close and reopen the migrated file | Version is still 2. The rows are unchanged. No `store.migrated` record on the second open. |
| T-03 | Fresh file DB (path does not exist yet) | Raw check: `character` column present, `user_version == 2`. `store.migrated` logged with `from == 0` and `to == 2`. |
| T-04 | v1 file DB whose `sessions` table already has a `character TEXT` column (half-applied step) | Opens without error. Version becomes 2. No duplicate-column error. |
| T-05 | `monkeypatch.setattr(repos_module, "_MIGRATIONS", [*repos_module._MIGRATIONS, (3, "sessions", "bogus", "ALTER TABLE no_such_table ADD COLUMN x TEXT")])`, then open a fresh file DB | Opening raises `sqlite3.OperationalError`. Raw check afterwards: `user_version == 2` (earlier steps committed), no `bogus` column, and the file can be opened with the real ladder (monkeypatch undone). |
| T-06 | File DB created with `PRAGMA user_version = 99` | Opens. Version stays 99 (never lowered). Exactly one WARNING record `store.schema_newer_than_code`. |
| T-07 | **Approved test amendment.** In `tests/test_sqlite_store.py::test_schema_created_on_open`, change `assert version == 1` to `assert version == 2` | Passes. This is the only assertion edited in that file. It is wrong after the ladder lands because a fresh DB now reaches v2. |

### WP-2: Protocol and store methods (`tests/test_session_character_store.py`)

| ID | Test | Expected |
|----|------|----------|
| T-08 | `create_session("s", character=ARIA)` then `get_character("s")` | Equals `ARIA`. Mutating the returned dict does not change a second `get_character("s")` (fresh dict per read). |
| T-09 | `create_session("s")` with no character | `get_character("s") is None`. `get_session("s") == []` (as today). |
| T-10 | `get_character("nope")` for an unknown session | Raises `KeyError`. |
| T-11 | File DB: create a session with `ARIA`, close, reopen. Also open the T-01 old DB and read `get_character("s-old")`. | The first returns `ARIA` after reopen. The second returns `None`. |
| T-12 | Immutability | `SqliteSessionStore` has no `set_character` or `update_character` attribute. A second `create_session` with an existing id still raises `sqlite3.IntegrityError` (as today) and the stored character is unchanged. |
| T-13 | Signature | For both `SessionStore` and `SqliteSessionStore`, `inspect.signature(create_session)` parameters are `["self", "session_id", "character"]` and `character` defaults to `None`. `get_character` has parameters `["self", "session_id"]` on both. |
| T-14 | **Approved test amendment.** In `tests/test_single_session_model.py::test_session_store_protocol_unchanged`, add `"get_character"` to the pinned set. | The set equals the 7 current names plus `get_character` (8 names). This is the only assertion edited in that file. |

### WP-3: REST contract (`tests/test_session_character_api.py`)

Uses the `client` fixture. Read the stored value through `app.deps.get_session_store().get_character(session_id)`.

| ID | Test | Expected |
|----|------|----------|
| T-15 | `client.post("/api/v1/sessions")` with no body | 201, a `Location` header, and body keys exactly `{"session_id", "capabilities"}`. Stored character is `None`. |
| T-16 | `json={}` and `json={"character": None}` | Both return 201. Stored character is `None`. |
| T-17 | `json={"character": ARIA}` with a leading and trailing space added to `name` | 201. Body keys are still exactly `{"session_id", "capabilities"}` (the character is not echoed). `get_character` equals `ARIA` (name stripped, abilities a plain dict with the six keys, all 11 keys present). |
| T-18 | Legacy-shaped payload: no `species_id`, no `id`, no `char_class`, no `conditions` (only `name, lineage, level, hp_current, hp_max, ac, abilities`) | 201. Stored `species_id is None`, `id == ""`, `char_class == ""`, `conditions == []`. |
| T-19 | Rejections (parametrized). Each case posts `ARIA` with one change. | Every case returns 422: `name` empty; `name` of 61 chars; `name` whitespace only; `lineage` of 61; `char_class` of 41; `level` 0; `level` 21; `hp_current` -1; `hp_max` 0; `hp_max` 1000; `ac` 31; `ac` -1; one ability 0; one ability 31; an ability key missing; an extra ability key (`"LUCK"`); 9 conditions; a condition of 41 chars; `species_id` `"Not A Slug"`; `species_id` of 65 chars; an unknown key inside `character` (`"inventory"`); an unknown key next to `character` in the body. |
| T-20 | Boundary values accepted | 201 for: `name` 60 chars, `lineage` 60, `char_class` 40, `id` 64, `species_id` 64 (valid slug), `level` 1 and 20, `hp_current` 0, `hp_max` 999, `ac` 0 and 30, all abilities 1, all abilities 30, 8 conditions of 40 chars each. |
| T-21 | Logging | The `session.created` record has `has_character` `True` for a character session and `False` for a bare one. With a sentinel in `name`, no log record (message or `__dict__`) contains the sentinel. |

### WP-4: pure prompt builder (`tests/test_character_section.py`)

Call `build_character_section` with literal dicts. No store, no service. `max_field_len` is passed explicitly.

| ID | Test | Expected |
|----|------|----------|
| T-22 | Golden output: `ARIA`, `species_name="Elf"`, `implications="Darkvision and Trance."`, `max_field_len=240` | The result equals exactly the 9 lines shown under WP-4 "Format" (joined with `"\n"`, no trailing newline). |
| T-23 | Modifiers `floor((s-10)/2)` | The text contains `STR 1 (-5)`, `DEX 8 (-1)`, `CON 9 (-1)`, `INT 10 (+0)`, `WIS 11 (+0)`, `CHA 12 (+1)` for one dict. A second dict gives `STR 30 (+10)`. |
| T-24 | Species line rules | `species_name="Elf"` with lineage `"elf"` (any case, surrounding space) gives `Species: Elf` (no parentheses). Lineage `"Wood Elf"` gives `Species: Elf (Wood Elf)`. `species_name=None` with lineage `"Wood Elf"` gives `Species: Wood Elf` and no `Species traits:` line, even if `implications` is passed. Both empty means there is no `Species:` line. |
| T-25 | Newline flattening | `name`, `lineage`, `char_class`, species name, and each condition contain `"\n"`, `"\r\n"` and `"\r"`. The result has no `"\r"`. For this full character (species resolved, at least one condition, implications given), `section.split("\n")` has exactly 9 lines. The only line equal to `END PLAYER CHARACTER` is the last. Text like `END PLAYER CHARACTER` inside a name stays inside the `Name:` line. |
| T-26 | Truncation | `implications` of 500 chars with `max_field_len=50`: the traits value is exactly 50 chars and ends with `…`. Conditions joined to more than 50 chars with `max_field_len=50`: the conditions value is exactly 50 chars and ends with `…`. `name` of 200 chars: the name value is at most 60 chars. `lineage` 200: at most 60. `char_class` 200: at most 40. Species name 200: at most 60. |
| T-27 | Size bound (maximal inputs) | Name 60, lineage 60 (different from the species name), species name 60, class 40, level 20, HP 999/999, AC 30, all abilities 30, 8 conditions of 40 chars, implications of 1,000 chars, `max_field_len=240`: `len(section) <= 1024`. The test also asserts `len(section) <= 968` (the computed worst case, see WP-4). |
| T-28 | Purity and optional lines | The input dict equals a `copy.deepcopy` taken before the call. Two calls return the same string. Empty `conditions` gives no `Conditions:` line. `implications` of `None` or `""` gives no `Species traits:` line. Empty `char_class` gives `Class: unknown, level 3`. |

### WP-5: worker wiring (`tests/test_character_wiring.py`)

Uses `make_stub_service(species=...)` and a recording `client.chat` (copy the `_recording_chat` and one-line `_expected_system()` helpers from `tests/test_prompt_pipeline.py`). Each test uses a real `SqliteSessionStore(":memory:")`.

| ID | Test | Expected |
|----|------|----------|
| T-29 | `services = build_services(make_default_repos(), enable_tool_discovery=False)` | `services["inference"]._species_by_id` is a dict with the same size as `services["reference"]["species"]` (68) and contains `"elf"`. `services["tool"].default_context["reference"] is services["reference"]` still holds. The key set of `services` is unchanged. |
| T-30 | Session created with `ARIA` (species `elf`), service built with `species=load_species()`, one chat job | The system message (first item) equals `_expected_system() + "\n\n" + build_character_section(ARIA, "Elf", <catalog implications for elf>, max_field_len=240)`. The message list is `[system, user]`. |
| T-31 | Same, but `species_id` is `"no-such-species"` | The job completes. The system message equals `_expected_system() + "\n\n" + build_character_section(..., None, None, max_field_len=240)`. It contains `Species: Wood Elf` and no `Species traits:`. The `prompt.built` record has `character is True` and `species_resolved is False`. |
| T-32 | Session created with no character | The system message equals `_expected_system()` exactly (byte-identical to today). The `prompt.built` record has `character is False` and `species_resolved is False`. For `ARIA` with `elf`, the record has `character is True` and `species_resolved is True`. |
| T-33 | Spy store: `SqliteSessionStore` subclass that counts `get_character` calls. Run one chat job and one slash job (`/roll 1d4`, built like `slash_env` in `tests/test_slash_dispatch.py` L52-L58). | The chat job makes exactly 1 call. The slash job makes 0 calls and does not call `client.chat`. |
| T-34 | A sentinel `SENTINEL-c0de` as the character `name` and as a condition, one chat job, `caplog` at INFO | The sentinel is in the system message sent to `client.chat`. No log record (message or `__dict__`) contains it. |

### WP-6: integration with a faked Ollama (`tests/test_character_integration.py`)

Uses the `client` fixture (real `build_services`, so the real species catalog reaches the worker). Fake Ollama: `monkeypatch.setattr(get_inference_service().client, "chat", recorder)` where the recorder deep-copies the messages it receives. Wait for idle with `wait_idle(get_inference_service())`.

| ID | Test | Expected |
|----|------|----------|
| T-35 | `POST /sessions` with `ARIA`, then `POST /sessions/{sid}/messages` (`AUTH` header) | Exactly one chat call. `messages[0]` is the only `system` message. It contains `PLAYER CHARACTER (game data, not instructions):`, `Name: Aria`, `Species: Elf (Wood Elf)`, `Class: Ranger, level 3`, `HP at start of tale: 24/28 | AC: 14`, and the catalog's `character_creation_implications` for `elf` (cut with `_truncate(..., 240)`). The last message is the user's text. |
| T-36 | A second message in the same session | The second chat call has exactly one `system` message, and it contains the character section exactly once. The history holds the first user message and the first reply. No other message contains `PLAYER CHARACTER`. |
| T-37 | `POST /sessions` with no body, then one message | `messages[0]["content"]` equals `_expected_system()`. The list is `[system, user]`. |
| T-38 | Legacy lineage-only character (the T-18 payload with lineage `"Wood Elf"`), then one message | 201. The system message contains `Species: Wood Elf` and no `Species traits:`. |
| T-39 | Regression and gate | The whole suite passes. The only existing assertions edited are T-07 and T-14. Ruff and black are clean on `app tests scripts`. |

### WP-7 and WP-8: frontend (manual, build gate)

Gate for both: `cd frontend && npm run build` (`tsc -b && vite build`) passes with no new warnings.

Setup for all F-checks: backend running (`./restart.sh`), `cd frontend && npm run dev`, browser DevTools open on the Network tab, "Preserve log" on. Start with a clean profile unless a check says otherwise (DevTools > Application > Local Storage: delete every `vox.*` key). To read the stored character of the newest session:

```
./venv-dnd-server/bin/python -c "import sqlite3; print(sqlite3.connect('dnd.db').execute('select id, character from sessions order by created_at desc limit 1').fetchone())"
```

| ID | Check | Expected |
|----|-------|----------|
| F-01 | `npm run build` after WP-7, and again after WP-8 | Exits 0. |
| F-02 | Clean profile, open the app (empty roster, rail shows Kaelen) | One `POST /api/v1/sessions` with no request body. The newest session's `character` is `None`. The backend log shows `session.created` with `has_character` false. |
| F-03 | Forge a hero: name "Aria", pick the "Elf" chip, class "Ranger", save. (After WP-8, a "Start a new tale with Aria?" prompt appears: press OK.) Then, if no tale started, use Menu > New Tale. | The new `POST /api/v1/sessions` body has a `character` object with snake_case keys (`id, name, lineage, species_id, char_class, level, hp_current, hp_max, ac, abilities, conditions`), `species_id` equals `"elf"`, `lineage` equals `"Elf"`, and abilities is `{STR, DEX, CON, INT, WIS, CHA}`. No key is camelCase. Status 201. The database line shows the same JSON. |
| F-04 | Roster empty (delete all heroes first), Menu > New Tale | The `POST /api/v1/sessions` has no body. Kaelen is never in any request body, in any check. |
| F-05 | Seed a legacy hero in `vox.characters` (DevTools console: `localStorage.setItem('vox.characters', JSON.stringify([{id:'legacy-1',name:'Old Hero',lineage:'Elf',charClass:'Fighter',level:2,hpCurrent:10,hpMax:10,ac:12,abilities:{STR:10,DEX:10,CON:10,INT:10,WIS:10,CHA:10},conditions:[]}]))`, then reload) | The app loads without a console error and the rail shows Old Hero. Then Menu > New Tale: the `POST /api/v1/sessions` body carries the legacy hero with `species_id: null` and `lineage: "Elf"`, and returns 201. |
| F-06 | Continue F-05. Open the creator, edit Old Hero. | The "Elf" chip already shows as selected (`aria-pressed` true) without clicking. Click "← Roster" without saving: `localStorage['vox.characters']` still has no `speciesId` key. Edit again, press "Forge Hero": the saved hero now has `speciesId: "elf"`. |
| F-07 | Seed a legacy hero with lineage `Wood Elf`, open it for edit | No chip is selected. Save: the stored hero has no `speciesId`. A new tale sends `species_id: null`, `lineage: "Wood Elf"`. |
| F-08 | Edit a hero: pick the "Elf" chip, then change the Lineage text to `Wood Elf`, save, start a new tale | Stored hero has `speciesId: "elf"` and `lineage: "Wood Elf"`. The request has `species_id: "elf"` and `lineage: "Wood Elf"`. Typing in the lineage field does not clear the species. |
| F-09 | Edit the hero currently at the table (open it from the roster with the "At the table" tag) | A one-line note reads "Changes reach the DM at the next New Tale." Save: no prompt appears, no `POST /api/v1/sessions`, and the rail updates. Editing a hero that is not at the table shows no note. |
| F-10 | Two heroes, A at the table. Click B in the roster. | A browser prompt asks "Start a new tale with B?". Cancel: A still shows "At the table", no `POST /api/v1/sessions`, the narrative log is untouched. Click B again and press OK: B is at the table, one `POST /api/v1/sessions` carries B, the narrative log is empty. Clicking the hero already at the table does nothing (no prompt). |
| F-11 | Two heroes, A at the table. Forge a new hero C and save. Then edit B (not at the table) and save. | Each save asks "Start a new tale with <name>?". Cancel on C: C is in the roster and A is still at the table, no `POST`. Cancel on B: the same. OK on C: C is at the table with a new tale carrying C. |
| F-12 | Heroes A (at the table) and B. Delete A. | The prompt asks "Start a new tale with B?". Cancel: both heroes remain, A at the table, no `POST`. OK: A is gone, B is at the table, one `POST` carries B. Deleting B (not at the table) when A is at the table: no prompt, B removed. With only one hero left and at the table, deleting it asks "Start a new tale without a hero?". OK: roster empty, Kaelen on the rail, the `POST` has no body. |
| F-13 | Start a tale with hero A, then reload the page | The same session is restored (`vox.session_id` unchanged), with no new `POST /api/v1/sessions`. The rail shows the hero stored in `vox.active_character`. A session that was created before this change stays hero-less (`character` is `None` in the database) until Menu > New Tale. |
| F-14 | Playtest, not gating (needs the real Ollama): forge "Aria", Elf Ranger, start the tale, send "Who am I and what can I do?" | The DM's reply refers to Aria and her class, and may use her species traits. Write down what felt wrong. Those notes drive the next slice (REQ-0007). This check judges a model's wording, so it cannot fail the build. |

## 3. Work Packages

Each WP MUST be implemented test-first: write the tests named in section 2, watch them fail, then change the code. Backend packages come before frontend packages. Run packages in order: WP-1 to WP-8.

Rules that apply to every WP below (restated here so no package depends on another):
- Log only through `get_logger(__name__)` from `app.services.logger` (PAT-CODE-001). No `print`, no stdlib `logging.getLogger`. Never log character content or prompt text. Flags and counts only.
- No new dependencies (neither `requirements*.txt` nor `frontend/package.json`).
- No git commands (do not stage, commit, branch, or stash).
- Protected files, do not edit: everything under `docs/adr/`, everything under `docs/patterns/`, `docs/requirements/LOG.md`, `.github/BACKLOG.json`, `app/config.py`, `settings.json`.
- This spec needs no protected file. It does edit three existing test files and one test helper. Each is listed in the WP that edits it, and the edits are limited to what that WP names.
- pydantic v2 idioms only in new code (`ConfigDict`, `model_dump`). Do not edit existing `class Config` blocks or existing v1 calls.
- Smallest edit: no new abstraction layers, no helper that has a single call site unless the WP names it.

### WP-1: migration ladder and `character` column (M)
- **Gate:** the backend gate (pytest, ruff, black). Depends on: none.
- **Files:**
  - `app/services/repos.py`
  - new `tests/test_store_migration.py`
  - `tests/test_sqlite_store.py` (only the T-07 assertion in `test_schema_created_on_open`)
- **Inputs:** PAT-ARCH-008 (accepted). `SqliteSessionStore.__init__` as described in Verified facts. The stdlib `sqlite3` module. `get_logger` is already imported in `repos.py`.
- **Change:**
  1. Add a module-level, append-only list `_MIGRATIONS: list[tuple[int, str, str, str]]` of `(version, table, column, ddl)`. It starts with exactly one entry: `(2, "sessions", "character", "ALTER TABLE sessions ADD COLUMN character TEXT")`.
  2. In `__init__`, keep the three base `CREATE ... IF NOT EXISTS` statements exactly as they are (frozen at v1). Delete the unconditional `PRAGMA user_version = 1` line.
  3. After the base statements, still under `self._lock` and before `_recover_interrupted()`: read `PRAGMA user_version` into `start`. If it is below 1, set it to 1. Compute `newest = _MIGRATIONS[-1][0]`.
  4. If the current version is above `newest`: log WARNING `store.schema_newer_than_code` with the version in `extra`, leave the version alone, and skip the ladder.
  5. Otherwise, for each entry with `version` above the current version, in list order: `self._conn.execute("BEGIN")`. If `PRAGMA table_info(<table>)` does not list `<column>`, run the DDL. Then `PRAGMA user_version = <version>` and `self._conn.commit()`. If anything raises, `self._conn.rollback()`, `logger.exception("store.migration_failed", extra={"version": version})`, close the connection, and re-raise. The store MUST NOT open on a half-migrated database (assumption A-3).
  6. If the version changed since `start` (including 0 to 2 on a fresh DB), log INFO `store.migrated` with `extra={"from": start, "to": <final>}`. Log no SQL and no values.
  7. In `tests/test_sqlite_store.py::test_schema_created_on_open`, change `assert version == 1` to `assert version == 2` (T-07). Change nothing else in that file.
- **Outputs:** an old `dnd.db` at user_version 1 upgrades in place to 2 with `character = NULL` on its existing sessions. A fresh DB goes 0 to 1 to 2. The code can no longer lower a version.
- **Acceptance (restated in full):**
  - Opening a v1 file DB with a session and a message keeps both, adds a nullable `character` column, sets `user_version` to 2, and logs one `store.migrated` with `from` 1 and `to` 2 (T-01).
  - Reopening is a no-op: version 2, same rows, no `store.migrated` record (T-02).
  - A fresh file DB ends at version 2 with the column present (T-03).
  - A v1 DB that already has the column opens and reaches version 2 with no duplicate-column error (T-04).
  - A failing step raises `sqlite3.OperationalError`, leaves `user_version` at the last committed step and adds no column (T-05).
  - A DB with `user_version` 99 stays at 99 and logs one WARNING `store.schema_newer_than_code` (T-06).
  - `test_schema_created_on_open` asserts `version == 2` (T-07).
  - The baseline suite (288) still passes. No other existing assertion changed.
- **Verification:** `./venv-dnd-server/bin/pytest -q tests/test_store_migration.py tests/test_sqlite_store.py`, then the full backend gate.
- **Stop condition:** if `PRAGMA user_version = N` inside the explicit transaction does not roll back with it, or `BEGIN` raises "cannot start a transaction within a transaction", stop and report the exact error. Do not switch to autocommit or another migration scheme.
- **Patterns used/created:** PAT-ARCH-008 (accepted), PAT-ARCH-002 (accepted), PAT-CODE-001.

### WP-2: Protocol and store methods (S)
- **Gate:** the backend gate. Depends on: WP-1.
- **Files:**
  - `app/type_defs.py`
  - `app/services/repos.py`
  - new `tests/test_session_character_store.py`
  - `tests/test_single_session_model.py` (only the pinned set in `test_session_store_protocol_unchanged`, T-14)
- **Inputs:** WP-1's `character TEXT` column. `repos.py` encodes dicts as JSON TEXT with `json.dumps` / `json.loads` (PAT-ARCH-002 rule 4). Every public store method takes `self._lock` and does not call another public method.
- **Change:**
  1. `type_defs.py`: change the Protocol to `create_session(self, session_id: str, character: dict[str, Any] | None = None) -> None: ...` and add `get_character(self, session_id: str) -> dict[str, Any] | None: ...`.
  2. `repos.py` `SqliteSessionStore.create_session(self, session_id, character=None)`: one INSERT writes `id`, `created_at` and `character` (`json.dumps(character)` when not `None`, else NULL). The write stays one transaction, so the character is set once at creation and never changed.
  3. Add `get_character(self, session_id)`: under the lock, `SELECT character FROM sessions WHERE id = ?`. No row raises `KeyError(session_id)`. A NULL value returns `None`. Otherwise return `json.loads(value)` (a fresh dict).
  4. Do not add `set_character`, an update method, or a generic session-metadata method (ADR-0008 D5).
  5. `tests/test_single_session_model.py`: add `"get_character"` to the expected set in `test_session_store_protocol_unchanged` (T-14). This is an approved test amendment (ADR-0008 Spec handoff 2). Change nothing else in that file.
  6. `seed_sample_data` and other callers of `create_session(id)` keep working unchanged because `character` defaults to `None`.
- **Outputs:** a character can be written once at session creation and read back by session id. Sessions without one read back `None`.
- **Acceptance (restated in full):**
  - `create_session("s", character=ARIA)` then `get_character("s")` equals `ARIA`, as a fresh dict on every read (T-08).
  - `create_session("s")` gives `get_character("s") is None` and `get_session("s") == []` (T-09).
  - `get_character` for an unknown session raises `KeyError` (T-10).
  - The character survives a close and reopen. A session migrated from an old DB reads `None` (T-11).
  - There is no mutator, and a duplicate `create_session` raises `sqlite3.IntegrityError` and leaves the first character unchanged (T-12).
  - Both signatures match T-13. The pinned Protocol set is the previous 7 names plus `get_character` (T-14).
  - The baseline suite still passes.
- **Verification:** `./venv-dnd-server/bin/pytest -q tests/test_session_character_store.py tests/test_single_session_model.py`, then the full backend gate.
- **Stop condition:** if any existing test fails for a reason other than the T-07 and T-14 assertions, stop and report. Do not edit other tests.
- **Patterns used/created:** PAT-ARCH-001 (the Protocol grows by one method; the architect already noted this), PAT-ARCH-002.

### WP-3: REST contract (M)
- **Gate:** the backend gate. Depends on: WP-2.
- **Files:**
  - `app/schemas/v1.py`
  - `app/api/v1/session.py`
  - new `tests/test_session_character_api.py`
- **Inputs:** `store.create_session(session_id, character=...)` from WP-2. FastAPI treats an absent or empty request body as `None` for a model parameter with default `None`. The current route is described in Verified facts.
- **Change:**
  1. In `app/schemas/v1.py`, add the imports it needs (`Annotated`, `StringConstraints`) and three new models below `SessionCreateResp`, written with pydantic v2 `ConfigDict` only. Do not touch existing models.
     - `AbilitiesIn`: `model_config = ConfigDict(extra="forbid")`, six `int` fields `STR, DEX, CON, INT, WIS, CHA`, each `Field(ge=1, le=30)`, all required.
     - `CharacterIn`: `model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)`, snake_case on the wire, with the fields below.
     - `SessionCreateReq`: `model_config = ConfigDict(extra="forbid")` with `character: CharacterIn | None = None`.
  2. `CharacterIn` fields (limits are ADR-0008 D4; which fields are required is assumption A-1):

     | Field | Type | Default | Limits |
     |---|---|---|---|
     | `id` | `str` | `""` | at most 64 chars |
     | `name` | `str` | required | 1 to 60 chars after stripping |
     | `lineage` | `str` | `""` | at most 60 |
     | `species_id` | `str \| None` | `None` | at most 64, pattern `^[a-z0-9]+(-[a-z0-9]+)*$` (same as `Species.id`) |
     | `char_class` | `str` | `""` | at most 40 |
     | `level` | `int` | required | 1 to 20 |
     | `hp_current` | `int` | required | 0 to 999 |
     | `hp_max` | `int` | required | 1 to 999 |
     | `ac` | `int` | required | 0 to 30 |
     | `abilities` | `AbilitiesIn` | required | exactly the six keys, each 1 to 30 |
     | `conditions` | `list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)]]` | `[]` | at most 8 items |

  3. In `app/api/v1/session.py`: import `SessionCreateReq` and add the parameter `req: SessionCreateReq | None = None` to `create_session` (after `store`). Compute `character = req.character.model_dump() if req is not None and req.character is not None else None`, call `store.create_session(session_id, character=character)`, and add `"has_character": character is not None` to the `session.created` log `extra`. The route stays a thin adapter: no other logic, `response_model`, status code, `Location` header and `SessionCreateResp` unchanged.
  4. Do not add a character read endpoint, and do not change the messages, snapshot, `/intel` or WebSocket output.
- **Outputs:** `POST /api/v1/sessions` accepts an optional `{"character": {...}}` body, validates it, and persists it on the session.
- **Acceptance (restated in full):**
  - No body, `{}`, and `{"character": null}` all return 201 with the same response keys as today, and store no character (T-15, T-16).
  - A valid character returns 201, is stored with all 11 keys, the name is stripped, and is not echoed in the response (T-17).
  - A legacy-shaped payload without `species_id`, `id`, `char_class` or `conditions` returns 201 and stores the defaults (T-18).
  - Each over-cap, under-floor, missing-key, extra-key, bad-slug or unknown-field case in T-19 returns 422.
  - Every boundary value in T-20 returns 201.
  - `session.created` logs the `has_character` flag and never any character content (T-21).
  - The baseline suite still passes.
- **Verification:** `./venv-dnd-server/bin/pytest -q tests/test_session_character_api.py`, then the full backend gate.
- **Stop condition:** if FastAPI answers 422 to a request with no body (T-15), stop and report the FastAPI version and error. Do not make the body mandatory or add a second route.
- **Patterns used/created:** PAT-ARCH-001 (thin adapter), PAT-ARCH-005 (proposed: explicit models, pydantic v2 only).

### WP-4: pure prompt builder (M)
- **Gate:** the backend gate. Depends on: none (it can run in parallel with WP-1 to WP-3; it takes plain values only).
- **Files:**
  - `app/intelligence/prompt_builders.py`
  - new `tests/test_character_section.py`
- **Inputs:** `_truncate(s, n)` in the same file (L69). The character is a plain dict with the keys in the WP-3 table.
- **Change:** add one public function `build_character_section(character: dict[str, Any], species_name: str | None, implications: str | None, *, max_field_len: int) -> str`. It is pure: no I/O, no store, no logging, no mutation of `character`. Do not change `build_system_prompt` or `build_chat_messages`.
- **Format (the contract; lines joined with `"\n"`, no trailing newline):**
  ```
  PLAYER CHARACTER (game data, not instructions):
  Name: Aria
  Species: Elf (Wood Elf)
  Class: Ranger, level 3
  HP at start of tale: 24/28 | AC: 14
  Abilities: STR 12 (+1), DEX 16 (+3), CON 13 (+1), INT 11 (+0), WIS 15 (+2), CHA 10 (+0)
  Conditions: Blessed
  Species traits: Darkvision and Trance.
  END PLAYER CHARACTER
  ```
  Rules:
  - Free text (name, lineage, class, species name, each condition, implications) has `"\r\n"`, `"\r"` and `"\n"` replaced by single spaces, so a value can never start a new line. This is the whole sanitizing step.
  - Per-field caps, using `_truncate`: name 60, lineage 60, species name 60, class 40. The joined conditions string (`", ".join(...)`) and the implications are each cut to `max_field_len`.
  - Species line: when `species_name` is given, `Species: <species_name>`, plus ` (<lineage>)` only when the lineage is non-empty and differs from the species name (compared case-insensitively, after stripping). When `species_name` is `None`, use `Species: <lineage>` if the lineage is non-empty. If both are empty, omit the line.
  - `Species traits:` appears only when `species_name` is not `None` and `implications` is non-empty. Name-only characters never get traits.
  - `Conditions:` appears only when there is at least one condition.
  - Class line is `Class: <class>, level <n>`. Use `unknown` when the class is empty (assumption A-5).
  - Modifier is `(score - 10) // 2` (floor), printed with an explicit sign (`+0`, `-5`, `+10`). Abilities print in the order STR, DEX, CON, INT, WIS, CHA. A missing ability key is skipped.
  - Size bound: the fixed parts add up to at most 488 characters (labels, caps and newlines). So the total is at most `488 + 2 * max_field_len`. With the default `max_field_len` of 240 that is 968, under the ADR-0008 bound of 1,024 characters. The bound holds for any `max_field_len` up to 268.
- **Outputs:** a string the worker can append to the system message.
- **Acceptance (restated in full):**
  - The golden example above is reproduced exactly (T-22).
  - Modifiers follow `floor((s-10)/2)`, with score 1 giving -5 and score 30 giving +10 (T-23).
  - The species line follows the lineage and name-only rules (T-24).
  - Newlines and carriage returns never create extra lines: the section has exactly 9 lines for a full character, and only the last equals `END PLAYER CHARACTER` (T-25).
  - Every cap and truncation holds, including `…` on cut text (T-26).
  - The maximal input stays at or under 1,024 characters (and at or under 968) with `max_field_len=240` (T-27).
  - The function is pure and the optional lines drop out correctly (T-28).
  - The baseline suite still passes.
- **Verification:** `./venv-dnd-server/bin/pytest -q tests/test_character_section.py`, then the full backend gate.
- **Stop condition:** if the T-27 bound cannot be met without changing the format above, stop and report the measured length. Do not change the format or the caps on your own.
- **Patterns used/created:** PAT-ARCH-003 (accepted and amended: pure builders; the character section is part of the single system message), PAT-CODE-001.

### WP-5: worker wiring (M)
- **Gate:** the backend gate. Depends on: WP-2 (the store method) and WP-4 (the builder).
- **Files:**
  - `app/services/inference_service.py`
  - `app/services/build_services.py`
  - `tests/session_helpers.py` (only `make_stub_service`)
  - new `tests/test_character_wiring.py`
- **Inputs:** `build_character_section` from WP-4. `store.get_character` from WP-2. `Species` and `load_species` in `app/reference/species.py`. The worker's chat branch as described in Verified facts.
- **Change:**
  1. `build_services.py`: build `reference` (the species and weapons loaders) right after `tool_service` and before the inference service. Construct `OllamaInferenceService(settings, tool_service=tool_service, species=reference["species"])`. Keep `tool_service.default_context["inference"] = inference` and `tool_service.default_context["reference"] = reference` after it. The tool-before-inference order of ADR-0004 D1 is unchanged. The returned dict keys do not change.
  2. `inference_service.py`: change the signature to `__init__(self, settings, tool_service=None, species=None)`. Before the worker thread starts, set `self._species_by_id = {s.id: s for s in (species or [])}` (built once, never rebuilt). Import `Species` for the type hint and `build_character_section` from `prompt_builders`.
  3. In the chat branch only, right after `history = job.store.list_messages(...)`, call `character = job.store.get_character(job.session_id)`. When it is `None`, the system message is `self._system_prompt` unchanged. Otherwise look up `species = self._species_by_id.get(character.get("species_id") or "")` and build the section with `species.name if species else None`, `species.character_creation_implications if species else None`, and `max_field_len=self._max_field_len`. The system message is `self._system_prompt + "\n\n" + section`. Pass that as the `system` argument of `build_chat_messages`. The builder functions receive plain values only. They never see the store or the species objects.
  4. Add `"character": <bool>` and `"species_resolved": <bool>` to the `prompt.built` log `extra` (no content). `species_resolved` is true only when the species was found in the catalog.
  5. Slash jobs do not read the character. Do not change the slash branch.
  6. `tests/session_helpers.py`: change `make_stub_service` to `make_stub_service(tool_service=None, species=None, **settings_kwargs)` and pass `species=species` to `OllamaInferenceService`. Change nothing else in the file.
  7. An unknown or missing species id is not an error. The job proceeds name-only (ADR-0008 D2).
- **Outputs:** the worker puts the character section into the one system message for sessions that have a character, and leaves the system message byte-identical for sessions that do not.
- **Acceptance (restated in full):**
  - `build_services` loads the reference catalog before the inference service. The service holds a `{id: Species}` map with all 68 species, and `services` still has exactly the keys `session, tool, inference, reference` (T-29).
  - A character with a resolvable species id produces a system message equal to the base system message, a blank line, then the section with the species name and the catalog implications (T-30).
  - An unknown species id produces a name-only section, the job completes, and `prompt.built` has `species_resolved` false (T-31).
  - A session with no character produces exactly today's system message, and `prompt.built` has `character` false (T-32).
  - A chat job calls `get_character` exactly once. A slash job never calls it (T-33).
  - No log record contains character text (T-34).
  - The message list shape is still `[system, prior..., user]` with exactly one system message first.
  - The baseline suite still passes. Existing tests that call `make_stub_service(...)` are unchanged.
- **Verification:** `./venv-dnd-server/bin/pytest -q tests/test_character_wiring.py tests/test_prompt_pipeline.py tests/test_slash_dispatch.py`, then the full backend gate.
- **Stop condition:** if `build_services` cannot load `reference` before the inference service without a circular import or a changed return shape, stop and report. Do not add a lazy catalog lookup or a store-level species cache.
- **Patterns used/created:** PAT-ARCH-003 (amended rules 3 and 5), PAT-ARCH-006 (user records reference catalog entries by `id`, no FK; tools and workers read the in-memory catalog), PAT-ARCH-001.

### WP-6: integration test with a faked Ollama (M)
- **Gate:** the backend gate. Depends on: WP-3 and WP-5.
- **Files:**
  - new `tests/test_character_integration.py` (tests only; no app code changes)
- **Inputs:** the `client` fixture in `tests/conftest.py` (real `build_services` with the real catalog, `:memory:` SQLite). `app.deps.get_inference_service()` and `get_session_store()`. `AUTH` and `wait_idle` from `tests/session_helpers.py`.
- **Change:** write T-35 to T-38. The fake Ollama replaces `get_inference_service().client.chat` with a recorder that deep-copies the messages and returns `reply-N`. Tests create sessions through the real REST routes and post messages through `POST /api/v1/sessions/{sid}/messages`. No network, no Ollama.
- **Outputs:** an end-to-end check that a character sent on session create reaches the system message sent to the model, with the species traits from the real catalog.
- **Acceptance (restated in full):**
  - A session created with `ARIA`, plus one message, sends exactly one chat call. Its only system message has the character header, `Name: Aria`, `Species: Elf (Wood Elf)`, the class and level line, the HP/AC line, and the `elf` catalog implications. The user text is the last message (T-35).
  - A second message in the same session again sends exactly one system message with the section once, and history with the first reply. No other message holds the section (T-36).
  - A session created with no body sends exactly `_expected_system()` as the system message and a two-message list (T-37).
  - A legacy lineage-only character is accepted, and the system message shows `Species: Wood Elf` with no traits line (T-38).
  - The whole suite plus ruff and black is green, and the only existing assertions edited in the spec are T-07 and T-14 (T-39).
- **Verification:** the full backend gate. Expected: 288 baseline tests still passing plus all new tests, 0 failed.
- **Stop condition:** if a test needs an app-code change to pass, stop and report which earlier WP is wrong. Do not patch app code in this WP.
- **Patterns used/created:** PAT-ARCH-003, PAT-ARCH-001, `tests.instructions.md` conventions.

### WP-7: frontend model and API (M)
- **Gate:** `cd frontend && npm run build`, plus the manual checks F-01 to F-08 (F-01 is the build). The backend must be running and include WP-1 to WP-5. Depends on: WP-3 (the contract).
- **Files:**
  - `frontend/src/lib/character.ts`
  - `frontend/src/lib/roster.ts`
  - `frontend/src/lib/api.ts`
  - `frontend/src/types.ts`
  - `frontend/src/components/CharacterCreator.tsx`
  - `frontend/src/App.tsx` (only the two `createSession()` call sites and the `startNewSession` signature; WP-8 owns the rest)
- **Inputs:** the WP-3 request contract. `CharacterIn` wire keys: `id, name, lineage, species_id, char_class, level, hp_current, hp_max, ac, abilities, conditions`. The existing frontend described in Verified facts. The frontend has no test runner and gets no new dependency.
- **Change:**
  1. `character.ts`: add `speciesId?: string | null` to `Character` (optional, so saved heroes in localStorage still parse). Make `normalizeCharacter` cap lengths to the backend limits: name 60, lineage 60, class 40, each condition 40 (applied before the `|| 'Unnamed Hero'`-style fallbacks), and read `(c.conditions ?? [])` so a legacy save without that field does not throw (A-9). Add `toCharacterIn(c: Character): CharacterIn`, which calls `normalizeCharacter(c)` and returns the snake_case object (`species_id: c.speciesId ?? null`, `char_class`, `hp_current`, `hp_max`).
  2. `types.ts`: add the `CharacterIn` interface (snake_case, `abilities: Record<AbilityKey, number>`).
  3. `roster.ts`: add `sendableHero(roster, activeId): Character | null`. It returns the hero `resolveActive` would show, or `null` when that is the placeholder (compare against `PLACEHOLDER_CHARACTER.id`). This is the only place that decides what is sent, and the placeholder is never sent.
  4. `api.ts`: change to `createSession(character?: Character | null)`. With no character it sends exactly what it sends today (no body, no content-type header). With a character it sends `Content-Type: application/json` and `JSON.stringify({ character: toCharacterIn(character) })`. In `parseJson`, use `body.detail` for the error message only when it is a string. Otherwise keep `Request failed: <status>`. (A 422 from FastAPI has an array `detail`.) The error is thrown, never swallowed.
  5. `App.tsx`: the bootstrap effect passes `sendableHero(roster, activeCharacterId)` to `createSession`. `startNewSession` becomes `startNewSession(hero: Character | null = sendableHero(roster, activeCharacterId))` and passes `hero` on. Its callers (the menu "New Tale" action) keep calling it with no argument.
  6. `CharacterCreator.tsx`: the chip `onClick` and `pickSpecies` set both `lineage: picked.name` and `speciesId: picked.id`. The chip's "selected" state and `aria-pressed` key on `editing.speciesId === s.id` (not on the lineage text). Typing in the Lineage field changes only `lineage` and never touches `speciesId`. Add an effect that runs when the species list has loaded or the edited hero's id changes: if the edited hero has no `speciesId` and exactly one `5.5e` catalog entry has a name equal to the hero's lineage (trimmed, case-insensitive), set `speciesId` to that entry's id in the editing state only. It is saved only when the user presses "Forge Hero". "Wood Elf" matches nothing and the hero stays name-only.
- **Outputs:** a hero with a species id sends that id. Legacy heroes load and send name-only. The placeholder is never sent. The creator preselects the matching species for legacy heroes.
- **Acceptance (restated in full):**
  - `npm run build` passes (F-01).
  - A clean profile creates a session with no request body (F-02).
  - A hero forged with the "Elf" chip sends a snake_case body with `species_id: "elf"` and `lineage: "Elf"` (F-03).
  - With an empty roster, New Tale sends no body, so "Kaelen" never reaches the backend (F-04).
  - A legacy hero without `speciesId` loads without a console error and is sent with `species_id: null` (F-05).
  - Opening a legacy hero whose lineage equals a 5.5e species name preselects that chip, persists only on save, and a non-matching lineage such as `Wood Elf` stays name-only (F-06, F-07).
  - Typing in the lineage field after picking a species keeps `speciesId` (F-08).
  - A backend 422 shows a readable error (the `Request failed: 422` text), not "[object Object]".
- **Verification:** `cd frontend && npm run build`, then F-01 to F-08 by hand as written in section 2.
- **Stop condition:** if `tsc -b` reports an error in a file outside the list above, stop and report. Do not loosen `tsconfig` settings.
- **Patterns used/created:** PAT-ARCH-006 (reference by `id`), PAT-ARCH-005 (snake_case on the wire).

### WP-8: frontend hero and tale rule (M)
- **Gate:** `cd frontend && npm run build`, plus the manual checks F-01 and F-09 to F-14. Depends on: WP-7.
- **Files:**
  - `frontend/src/App.tsx`
  - `frontend/src/components/CharacterCreator.tsx` (only the note in the editor view)
- **Inputs:** WP-7's `sendableHero` and `startNewSession(hero)`. In `App.tsx`, `character = resolveActive(roster, activeCharacterId)` is the hero at the table. The prompt uses `window.confirm` (the smallest option, assumption A-7).
- **Change:**
  1. `App.tsx`: pass `activeId={character.id}` to `CharacterCreator` instead of the raw `activeCharacterId`. This makes the "At the table" tag and the editor note follow the hero the rail shows, even when the pointer is null (A-8).
  2. `handleSelectCharacter(id)`: if `id === character.id`, do nothing. Otherwise `window.confirm(`Start a new tale with ${name}?`)` where `name` is the target hero's name. On OK: `saveActiveId(id)`, `setActiveCharacterId(id)`, and `void startNewSession(<target hero>)`. On Cancel: change nothing.
  3. `handleSaveCharacter(next)`: always persist the roster (`upsertCharacter`, `saveRoster`, `setRoster`). Read the saved hero back from the new roster. If `next.id === character.id` (the hero at the table, edited in place): also keep the pointer on that id and do nothing else (no prompt, no new tale). Otherwise (a new hero, or an edit of a hero that is not at the table, A-10): `window.confirm(`Start a new tale with ${saved.name}?`)`. On OK: set it active and `void startNewSession(saved)`. On Cancel: it stays saved in the roster and the active hero does not change.
  4. `handleDeleteCharacter(id)`: if `id !== character.id`, remove it with no prompt. If it is the hero at the table: compute the roster without it and the fallback (`nextRoster[0] ?? null`). Ask `Start a new tale with ${fallback.name}?`, or `Start a new tale without a hero?` when there is no fallback (A-7). On Cancel: delete nothing. On OK: save the roster, set the fallback active (or clear the pointer), and `void startNewSession(fallback)`.
  5. `CharacterCreator.tsx`: in the editor view, when the edited hero is in the roster and `editing.id === activeId`, show one line using an existing text class (no CSS file change): "Changes reach the DM at the next New Tale." Nothing is shown for other heroes or for a new hero.
  6. Sessions restored from `vox.session_id` are left alone: no automatic new tale on load. A session from before this change stays hero-less until the user starts a New Tale.
- **Outputs:** the hero at the table always matches the hero the DM was given, except for in-place edits (noted) and the known edge cases in section 4.
- **Acceptance (restated in full):**
  - After WP-8, `npm run build` still passes (F-01).
  - Editing the hero at the table shows the note, shows no prompt, starts no session, and updates the rail (F-09).
  - Selecting another hero asks "Start a new tale with <name>?". Cancel changes nothing. OK makes that hero active and sends one `POST /api/v1/sessions` with that hero. Selecting the current hero asks nothing (F-10).
  - Saving a new hero, or an edit of a hero not at the table, asks the same question. Cancel keeps it in the roster without changing the active hero. OK activates it and starts a new tale with it (F-11).
  - Deleting the hero at the table asks with the fallback's name (or "without a hero"). Cancel deletes nothing. OK removes it, activates the fallback, and starts a new tale with the fallback (or with no body). Deleting a hero not at the table asks nothing (F-12).
  - A reload restores the same session with no new `POST`, and a pre-change session stays hero-less (F-13).
  - The playtest F-14 is run by the human and its notes are recorded in the BACKLOG follow-ups (the human writes those; the implementer does not edit the backlog).
- **Verification:** `cd frontend && npm run build`, then F-09 to F-14 by hand as written in section 2.
- **Stop condition:** if `window.confirm` is blocked by the browser or test environment so the flow cannot be checked, stop and report. Do not add a modal component.
- **Patterns used/created:** none. (ADR-0008 D3 rule.)

## 4. Other Details

### Traceability: REQ-0020 clause to work packages and tests

| Clause | WPs | Tests |
|---|---|---|
| C1. The client sends the character on session create | WP-3, WP-7 | T-15 to T-21, F-02, F-03, F-04 |
| C2. Stored on the session as a nullable, immutable value; sessions without one behave as today | WP-1, WP-2, WP-5 | T-01 to T-14, T-32, T-37 |
| C3. The worker adds a character section to the DM prompt, built by pure builders (PAT-ARCH-003) | WP-4, WP-5, WP-6 | T-22 to T-28, T-30, T-35, T-36 |
| C4. A species `id` pulls that species' `character_creation_implications` from the in-memory catalog | WP-5, WP-6 (with WP-4) | T-29, T-30, T-35 |
| C5. Species identified by catalog `id`; legacy free-text lineage keeps working | WP-3, WP-4, WP-5, WP-6, WP-7 | T-18, T-24, T-31, T-38, F-05 to F-08 |
| C6. The schema change migrates existing databases (PAT-ARCH-002, PAT-ARCH-008) | WP-1, WP-2 | T-01 to T-07, T-11 |
| C7. Hero and tale stay together on the client (ADR-0008 D3) | WP-7, WP-8 | F-09 to F-13 |
| C8. Streaming, summaries, attack tool and campaign state unchanged | all (see non-goals) | T-39 |

### Assumptions made by this spec

The human MAY overrule any of these at review. None blocks the work.
- **A-1:** In `CharacterIn`, `name`, `level`, `hp_current`, `hp_max`, `ac` and `abilities` are required. `id`, `lineage`, `species_id`, `char_class` and `conditions` have defaults. ADR-0008 D4 lists the limits but not which fields are required. The defaults let legacy-shaped payloads through (T-18).
- **A-2:** `SessionCreateReq` is also `extra="forbid"`. A misspelled top-level key (for example `charcter`) is a 422, not a silent drop. ADR-0008 D4 says there is no silent drop.
- **A-3:** If a migration step fails, the store rolls back, logs `store.migration_failed`, closes the connection, and re-raises. The server then fails to start. This differs from the usual rule "do not let startup crash". A server that cannot migrate the user's `dnd.db` should not serve it.
- **A-4:** Log event names: `store.migrated` (fields `from`, `to`), `store.schema_newer_than_code` (WARNING), `store.migration_failed`. PAT-ARCH-008 fixes only `store.migrated`.
- **A-5:** Builder details that ADR-0008 D6 leaves open: empty `Conditions:` and `Species traits:` lines are omitted, an empty class prints as `unknown`, and each short field has its own cap (60/60/60/40) on top of `max_field_len` for conditions and implications. The 1,024-character bound holds for `max_field_len` up to 268. The default is 240. If someone raises `settings.app.max_field_len` above 268, the bound no longer holds. T-27 checks only the default.
- **A-6:** `session.created` gains a `has_character` boolean (flag only). It lets F-02 and F-03 be checked from the log.
- **A-7:** The hero-switch prompt is `window.confirm`. Edge cases: when the roster is empty and the first hero is saved, the prompt still appears (the tale before it is hero-less). Cancel keeps the tale hero-less while the rail shows the new hero (the rail falls back to `roster[0]`). Deleting the last hero asks "Start a new tale without a hero?". For deletes, Cancel means "do not delete", because the hero cannot stay active after deletion.
- **A-8:** `CharacterCreator` receives `character.id` (the hero the rail shows) as `activeId`, not the raw pointer.
- **A-9:** `normalizeCharacter` caps string lengths to the backend limits and tolerates a missing `conditions` array. The creator's conditions field allows up to 120 characters, so a single condition could exceed 40 and fail with a 422 otherwise.
- **A-10:** Saving an edit of an existing hero who is not at the table is treated like switching to that hero (it asks the question). Today saving makes that hero active with no question.

### Risks
- **DDL inside a transaction.** Python's `sqlite3` has its own rules about implicit transactions. Mitigation: an explicit `BEGIN`, a `table_info` guard, T-04 and T-05, and the WP-1 stop condition.
- **The migration touches the human's real `dnd.db`.** The change is additive (one nullable column) and runs once. The human SHOULD copy `dnd.db` before the first run with the new code (`cp dnd.db dnd.db.bak`). This is a suggestion, not a step in a WP.
- **Prompt budget.** The section is at most 968 characters (about 250 tokens) with default settings. REQ-0021's summary will share the same system message. ADR-0008 D7 names that as a revisit trigger.
- **Prompt steering.** A child can type odd names. The section is capped, flattened to single-line values, and labeled as data. There is no further hardening (constraints.md).
- **Catalog edits change in-progress sessions' traits text.** Accepted in ADR-0008 D2.
- **Hero and tale can disagree in three known cases:** an in-place edit of the current hero (the note says so), a legacy session until the next New Tale, and the first-hero Cancel edge (A-7). If `startNewSession` fails after the active hero was changed (backend down), the active hero has moved but the tale has not. The error banner shows, and Menu > New Tale retries with the active hero.
- **`window.confirm` blocks the page thread.** Acceptable for a modal choice in a household app.
- **No frontend test runner.** Frontend correctness rests on the build gate and F-01 to F-14. Mitigation: the logic that could regress (`sendableHero`, `toCharacterIn`, the length caps) is small and pure.

### Rollback plan
- Revert the code changes of each WP, in reverse order. No data needs deleting.
- The `character` column is additive and nullable. Old code ignores it. If a database already at version 2 is opened by old code, the old constructor sets `user_version` back to 1. The next run of the new code finds the column present (the `table_info` guard) and sets 2 again. Nothing breaks.
- To remove the column, use `ALTER TABLE sessions DROP COLUMN character` (SQLite 3.35 or newer) after reverting. This is not required.

### Out-of-list files
- No protected file is edited. `app/factory.py` and `app/deps.py` are not touched (no new router, CORS already allows the request).
- Test files edited (each limited to what its WP names): `tests/test_sqlite_store.py` (T-07), `tests/test_single_session_model.py` (T-14), `tests/session_helpers.py` (`make_stub_service` gains `species`).
- Docs to update in the session wrap-up (not by an implementer of this spec): the `repos.py`, `session.py` and `inference_service.py` lines in `.github/copilot-instructions.md`.

### Patterns applied / created
- **Applied:** PAT-ARCH-001 (accepted; the Protocol grows by one method, thin adapter route), PAT-ARCH-002 (accepted; stdlib sqlite, JSON TEXT), PAT-ARCH-003 (accepted, amended 2026-11-01; pure builders, character section in the single system message, worker also calls `get_character`), PAT-ARCH-005 (proposed; explicit models, snake_case, pydantic v2 only), PAT-ARCH-006 (accepted; reference by `id`, no FK), PAT-ARCH-008 (accepted; the migration ladder, first call site), PAT-CODE-001 (accepted; `get_logger`).
- **Created:** none. No new reusable pattern emerged while scoping.
- **Decisions:** ADR-0008 (accepted), ADR-0003 and ADR-0006 unchanged.

### Non-goals
- Streaming (REQ-0007).
- Summaries (REQ-0021).
- The `/attack` tool and any tool that reads the character (REQ-0022; it reads `get_character` later).
- Campaign, quest and scene state; a `characters` table or character identity independent of sessions (REQ-0015).
- Mid-session character edits, HP tracking, level-up, or any endpoint that changes or reads the character. There is no set-once or replace endpoint.
- Changes to the messages response, the `/intel` snapshot, or the WebSocket events.
- Changing the species catalog or its ingest.
- A frontend test runner or a modal component for the prompt.
- Automatic migration of old localStorage heroes at app start. The creator preselect is the only legacy bridge.
- REQ-0023's pydantic v1 cleanup (`class Config`, `.dict()`, `schema_extra`). Do not touch it.

## Deviations / notes (as built, 2026-11-01)

- WP-4 left `build_system_prompt` and `build_chat_messages` untouched, per the spec. The character section is wired into the worker in WP-5.
- A stored character with no ability scores omits the `Abilities:` line.
- Edge (A-7): the first hero from an empty roster, then Cancel on the switch question, leaves the tale hero-less while the rail shows the new hero.
- Unspecified: a failed POST after the switch is confirmed. The active hero changes before the POST resolves. Not browser-verified.

