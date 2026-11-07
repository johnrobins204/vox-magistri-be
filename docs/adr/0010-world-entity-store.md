---
id: ADR-0010
status: accepted
date: 2026-11-07
requirement: REQ-0026
supersedes: null
superseded_by: null
---

# World entity store: a `world_entities` table in the session SQLite file via a new ladder step kind, nullable session scope, and a local selector feeding the narrator system prompt

## Context
REQ-0026 (`docs/requirements/LOG.md`) adds the first persisted world memory. Today
`app/intelligence/world_guide.py` and `quest_guide.py` are stubs, `WorldSettings` holds only
guidance flags, the ladder in `app/services/repos.py` has one step (v2), and no campaign model
exists (REQ-0015 open). Patterns consulted: PAT-ARCH-001/002/003/008/009 (accepted),
PAT-ARCH-005 (accepted 2026-11-07).

| Trigger (`docs/adr/README.md`) | Fired | Fact |
|---|---|---|
| Deviates from accepted pattern | yes | a new table is not an `ADD COLUMN` step, which `test_pat_arch_008_*` rejects; PAT-ARCH-003 rule 3 does not list a world section |
| Cross-cutting convention | yes | ladder step shape; `world` settings schema |
| Hard to reverse | partly | the human's `dnd.db` gains a table and a `user_version` bump |
| Two or more viable approaches | yes | scope, storage and selector reuse each have real alternatives |
| New dependency | no | stdlib `sqlite3` only; no vector DB |

## Decision Drivers
Scores 1-5; weights High 3, Medium 2, Low 1 (`docs/constraints.md`). Max total 90.

| Dimension | W | Why it matters here |
|---|---|---|
| Simplicity / smallest edit | 3 | solo, part-time |
| Reversibility | 3 | the real `dnd.db` must keep working |
| Maintainability | 3 | hand-written SQL, one maintainer |
| Reuse of patterns/deps | 2 | PAT-ARCH-002/008 already exist |
| Fun / learning | 2 | constraint 5 |
| Performance | 1 | household scale, dozens of entities |
| Security | 1 | dev token only, no new surface |
| Continuity (added) | 3 | owner's top pain is the DM forgetting earlier events; facts must outlive one session's `max_turns` window |

## Considered Options and Rubric Scoring
Columns: Simp / Rev / Maint / Reuse / Fun / Perf / Sec / Cont / Total.

**D1 Scope**

| Option | Simp | Rev | Maint | Reuse | Fun | Perf | Sec | Cont | Total |
|---|---|---|---|---|---|---|---|---|---|
| S1 session-only (`session_id NOT NULL`) | 5 one FK like `messages` | 2 SQLite cannot drop NOT NULL without a table rebuild | 5 no NULL rule | 4 mirrors `messages` FK | 2 nothing new | 3 equal | 3 equal | 2 world lost on each new session | 60 |
| **S2 nullable `session_id`: NULL = campaign-wide, set = session-local** | 4 one `IS NULL OR =` filter | 5 REQ-0015 can add `campaign_id` additively and claim NULL rows | 4 one documented rule | 4 same FK style | 3 scope modelling | 3 equal | 3 equal | 5 persists across sessions | **74** |
| S3 free-text `campaign_id`, no campaign table | 3 extra column and filter | 3 unvalidated ids need a rewrite when REQ-0015 lands | 2 a typo silently splits the world | 2 no FK target | 3 | 3 equal | 3 equal | 4 cross-session but fragile | 52 |

**D2 Storage and migration**

| Option | Simp | Rev | Maint | Reuse | Fun | Perf | Sec | Cont | Total |
|---|---|---|---|---|---|---|---|---|---|
| **A same file and `SqliteSessionStore` instance; new ladder step kind `CREATE TABLE IF NOT EXISTS`** | 4 one table, ~5 methods, ~6 lines in `_migrate`, one test branch | 5 additive; no row rewritten | 4 one connection, lock and ladder; class grows | 5 PAT-ARCH-002/008 reused | 4 ladder design | 3 shares the store lock; trivial at this scale | 3 equal | 5 FK to `sessions(id)`; in-place upgrade | **78** |
| B add the table to the frozen v1 base `CREATE`s, no ladder step | 5 one statement | 4 additive, but `user_version` stops describing the schema | 2 breaks PAT-ARCH-008 rule 1 and the REQ's "only via ladder extension" MUST | 3 sidesteps the ladder | 2 | 3 | 3 | 5 | 64 |
| C separate `SqliteWorldStore` on its own file (`database.world_url`) | 2 second connection, lock, schema, setting, wiring | 4 delete a file | 2 two ladders; duplicate boilerplate or a base class PAT-ARCH-002 forbids until needed | 3 | 3 | 4 own lock | 3 | 3 no FK across files; two `:memory:` DBs in tests | 52 |
| D do nothing until REQ-0015 | 5 no edit | 5 | 5 | 3 n/a | 1 | 3 | 3 | 1 top pain unaddressed | 62 |

`PRAGMA user_version` is one integer per file, so a second store sharing `dnd.db` could not keep
its own ladder; that rules out a "same file, separate class" variant.

**D3 Selector reuse** (PAT-ARCH-009 `select_rules` has one call site today)

| Option | Simp | Rev | Maint | Reuse | Fun | Perf | Sec | Cont | Total |
|---|---|---|---|---|---|---|---|---|---|
| **L1 local pure selector in `prompt_builders.py`; `rules.py` untouched** | 4 ~40 new lines | 5 one function | 4 ~10 lines of tokenizer overlap | 3 reuses PAT-ARCH-009 rules 2-3 as discipline, not code | 4 | 3 | 3 | 4 alias weights and recency fill fit entities | **71** |
| L2 extract a shared `selection.py` for rules and world | 2 edits `rules.py` and its tests; generic knobs | 3 | 3 edition tie-break and dedup do not apply to entities | 5 | 4 | 3 | 3 | 4 | 60 |
| L3 import private `_tokens` from `rules.py` | 5 one import | 4 | 2 rules stopwords (`rule`, `work`) leak; rules edits change world selection | 4 | 2 | 3 | 3 | 3 | 60 |

## Decision Outcome
Chosen: **S2 + A + L1** (74 / 78 / 71). They win because they keep one SQLite file, one
connection and one ladder; the world outlives a session; and they add no code to accepted
modules beyond one ladder step kind. Single-approach decisions, not scored:

| Topic | Decision |
|---|---|
| Table | `world_entities`: `id` TEXT PK (uuid), `session_id` TEXT NULL FK `sessions(id)`, `kind`, `name`, `aliases` (JSON TEXT, default `[]`), `notes`, `status` TEXT NOT NULL DEFAULT `canon`, `created_at`, `updated_at`. No CHECK constraints (SQLite cannot alter one in place); no index (dozens of rows). One step at the next contiguous version. |
| Store API | New `WorldStore` Protocol in `app/type_defs.py` (create/get/list/update/delete), implemented by `SqliteSessionStore`; `make_default_repos` exposes the same object as `"world"`; `deps.get_world_store()`. `SessionStore` Protocol unchanged. Unknown entity or session raises `KeyError`. |
| Vocabulary | `EntityKind` (npc, place, faction, quest, item, other) and `EntityStatus` (canon, pending, rejected) `StrEnum`s in `app/type_defs.py`, enforced at the edge; default `canon`. The approval slice needs no migration. |
| API | PAT-ARCH-005: `app/api/v1/world.py`, `/api/v1/world/entities` list/create and `/{id}` get/patch/delete; `{"entities": [...]}`; `HTTPException` 404; `UtcDatetime`; length limits as module constants; same auth dependency as session routes; OpenAPI snapshot regenerated. **No frontend panel** (Swagger `/docs` is the operator UI). |
| Injection | The worker gets the world store from `build_services` and, per chat job, lists the entities for the campaign and the session. Pure `select_world_entities` and `build_world_section` keep only `canon` entities. They score name/alias token hits x3 and notes hits x1 over the current text plus the kept prior turns, rank by (score desc, `updated_at` desc, id), and pack whole entities within the budget, skipping any that do not fit and never truncating. The section goes after the character section as game data. Counts-only logging; slash tools unaffected. |
| Settings | `world.entity_budget_chars` (int, `ge=0`, default 1500; 0 disables injection) in `WorldSettings` and `settings.json`. `enable_world_guidance` untouched. |
| Out of scope | Mention detection, approval queue, LLM extraction, recap, regenerate/edit, frontend UI. |

Traded away: one shared selector (small tokenizer duplication), file-level isolation, and a
dedicated store class (`SqliteSessionStore` now serves two Protocols).

## Consequences
- Positive: `dnd.db` upgrades in place; tests stay `:memory:`, with no network and no Ollama;
  status forward-compatible.
- Negative: the class name understates its role; lexical selection misses paraphrase; recency
  fill can spend budget on loosely related entities; the ladder linter gets two branches.
- Follow-up and risks: REQ-0015 maps NULL-scope rows to a campaign. Revisit a shared selector
  when a third selector appears. The ladder step cannot land until the PAT-ARCH-008 amendment
  is accepted, because `test_pat_arch_008_*` would fail.

## Pattern Impact
**Human sign-off given 2026-11-07 (ADR-0010, PAT-ARCH-003, PAT-ARCH-005, PAT-ARCH-008);
amendments below applied to the pattern files, the linter test change lands in WP-2:**
- **PAT-ARCH-008** (accepted), amendment applied:
  1. Tuple becomes `(version, table, column or None, ddl)`. `None` marks a table step whose
     DDL starts with `CREATE TABLE IF NOT EXISTS <table> (`. It only creates a new table: no
     copy, rename or drop.
  2. Table-step guard: skip the DDL if `sqlite_master` already lists the table; the
     `user_version` bump stays in the same transaction.
  3. Rule 6 tests include v1 and v2 file DBs: the table exists and is empty, rows survive,
     the version is the newest, and reopening is a no-op.
  4. `test_pat_arch_008_*`: contiguity unchanged; each step is either the ALTER form with a
     column or the CREATE form with `column is None`. INDEX "Mechanically enforced" row text
     updated to match.
  5. Context/Consequences: "additive" means a new nullable column or a new table.
- **PAT-ARCH-003** (accepted), amendment applied: rule 3 adds a world section from
  `build_world_section` over `WorldStore.list_entities` (ADR-0010); rule 5 notes the worker also
  calls `WorldStore.list_entities`. The REQ-0015 campaign-section sentence stays.

Used unchanged: PAT-ARCH-001, 002, 009, CODE-001; PAT-ARCH-005 (accepted) applied. No new
pattern: each new mechanism has one call site (constraints.md 2).
