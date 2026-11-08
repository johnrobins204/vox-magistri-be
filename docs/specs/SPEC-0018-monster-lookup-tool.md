---
id: SPEC-0018
requirement: REQ-0031
adr: ADR-0012
status: accepted
date: 2026-11-07
---

# `/monster` stat-block lookup tool

## 1. Requirement
REQ-0031; restatement in `docs/requirements/LOG.md` (row `| REQ-0031`). ADR: ADR-0012 (accepted, option B). Pattern: PAT-ARCH-011. Decisions the packages depend on:
- A hit is rendered by code from `context["reference"]["creatures"]`; no LLM. Only a true miss makes one flagged training-mode `generate`. No chars-budget setting.
- Dataset: both SRDs; if the measured `app/reference/creatures.json` exceeds 2,000,000 B, ship `srd-2024` only (WP-1 measures, WP-3 applies).
- Pure helpers live in `app/intelligence/monster_blocks.py` since `test_pat_arch_004` wants `NAME` and `run` in every `tools/*.py`. Contract: `.github/instructions/tools.instructions.md`.

## 2. Test Spec
Pytest, offline, literal fixtures. WP-1 tests load `scripts/ingest_open5e.py` with the `isolated_paths` fixture as `tests/test_ingest_rules.py` does. Later tests use `make_creature(name, edition="5.5e", **overrides)` (WP-2, `tests/creature_fixtures.py`) and a `FakeInference` whose `generate(prompt)` records it and returns `"MODEL REPLY"`.

### WP-1: projection and measurement (`tests/test_ingest_creatures.py`)
Fixture `_raw_creature(name, document_key, **over)`: an upstream-shaped dict (raw keys in WP-1 Inputs plus droppable `speed_all`, `proficiency_bonus`).
| ID | Test | Expected |
|---|---|---|
| T-1 | `build_records("creatures", ...)` | record keys equal `set(PROJECTION["creatures"])`; `attacks`, `crossreferences`, `modifiers`, `speed_all`, `document` appear nowhere in `json.dumps(records)`. |
| T-2 | scalar mapping | `size`/`type` are names; `edition` `"5.5e"` (srd-2024) or `"5e"`; `languages == as_string`; `cr` float; immunity strings equal the `*_display` values; `senses` only non-null ranges; `saving_throws`/`skill_bonuses` drop nulls; `speed` only positive ints among walk/burrow/climb/fly/swim. |
| T-3 | action split | the four `action_type`s fill the four lists, sorted by `order_in_statblock` (nulls last); items `{name, desc}` plus `usage` only when `usage_limits` is set (`PER_DAY` 3 -> `"3/Day"`, `RECHARGE_ON_ROLL` 5 -> `"Recharge 5-6"` (param 6 -> `"Recharge 6"`), other -> title-cased type plus param) and `cost` only on a legendary item with a cost; unknown `action_type` raises `ValueError` naming it. |
| T-4 | allowlist, ids | `DOCUMENT_ALLOWLIST["creatures"]` is a subset of both SRDs containing `"srd-2024"`; `CONSUMERS["creatures"]` contains `"/monster"`; an `a5e-mm` entry is dropped; 2024 and 2014 `Goblin` get ids `goblin`, `goblin-5e`. |
| T-5 | `measure_projection("creatures", entries)` | `{"both", "srd-2014", "srd-2024": {entries, bytes}, "fits_both", "allowlist"}`; `bytes == len(render(records).encode())`; `MAX_BYTES` patched above the both-size: `fits_both` true, both SRDs; between 2024-only and both: false, `["srd-2024"]`. `ingest("creatures", snap, out)` in `tmp_path` is byte-identical on a second run. |

### WP-2: `Creature` model (`tests/test_creature_model.py`; helper `tests/creature_fixtures.py`)
| ID | Test | Expected |
|---|---|---|
| T-7 | valid entry, defaults | a full literal entry validates (`ability_scores` is `AbilityScores`, lists hold `StatEntry`); only the required keys validates too; `make_creature("Goblin","5e").id == "goblin-5e"`, `make_creature("Goblin").id == "goblin"`. |
| T-8 | strictness, path | an unknown key, id `"Bad Id"`, edition `"3e"` or a missing `cr` each raise `ValidationError`; `CREATURES_PATH` is `app/reference/creatures.json`. |

### WP-3: committed dataset and budget (`tests/test_reference_budget.py` edited; new `tests/test_creatures_dataset.py`)
| ID | Test | Expected |
|---|---|---|
| T-9 | `test_reference_budget.py` | `creatures.json` in `REFERENCE_FILES`, `<= 2_000_000` bytes, `1..2_000` entries; `OPEN5E_MODELS` gains `"creatures": ("app.reference.creatures", "Creature")` (no-dropped-entries test). |
| T-10 | dataset shape | record keys equal the `Creature` fields; `(len, editions)` is `(656, {"5e","5.5e"})` or `(331, {"5.5e"})`; `third_party` all false; ids unique; `source_key`s unique, prefixed `srd_`/`srd-2024_`; `Aboleth` has `legendary_actions`; no `"attacks"`/`"crossreferences"` in the file. |

### WP-4: startup load (`tests/test_creatures_wiring.py`; build as `tests/test_rules_wiring.py` does, shut down in `finally`)
| ID | Test | Expected |
|---|---|---|
| T-11 | loaded once | `reference["creatures"]` is a list of `Creature`, as long as the raw array; `default_context["reference"] is services["reference"]`; other datasets non-empty. |
| T-12 | fail-soft | `app.services.build_services.CREATURES_PATH` patched to a missing file: no raise, `creatures == []`, one WARNING `reference.unavailable` (`dataset == "creatures"`, `reason == "missing"`). |

### WP-5: stat-block renderer (`tests/test_monster_render.py`)
| ID | Test | Expected |
|---|---|---|
| T-13 | golden, 2014 monster | a Goblin-like `make_creature(..., "5e", ...)` renders to the exact string written in the test (WP-5 layout). |
| T-14 | golden, legendary 2024 monster | traits, actions (one `usage="3/Day"`), a bonus action, a reaction and legendary actions (one `cost=2`): exact string, five headings in order. |
| T-15 | numbers | modifiers of scores 1, 10, 11, 20, 30 are `-5,+0,+0,+5,+10`; CR `0, 0.125, 0.25, 0.5, 11` renders `0, 1/8, 1/4, 1/2, 11`; XP `155000` renders `155,000`; XP `None` omits it. |
| T-16 | omission, fidelity | empty sections/lines and zero senses are absent; `Languages —` when empty; a 5,000-char `desc` appears verbatim; input not mutated. |

### WP-6: name matching (`tests/test_monster_lookup.py`)
| ID | Test | Expected |
|---|---|---|
| T-17 | exact, then substring | catalog Goblin, Goblin Boss: `"goblin"` gives Goblin; `"  GOBLIN-boss! "` and `"boss"` give Goblin Boss. |
| T-18 | ambiguity | `"dragon"` over 7 distinct `... Dragon` names raises `ToolError` (`matches several monsters`), listing 5 sorted names. |
| T-19 | editions | same name in both: 5.5e wins; `"goblin 2014"` gives the 5e entry, `"goblin 2024"` the 5.5e one; `"goblin 2014"` over a 5.5e-only catalog gives `None`. |
| T-20 | near-typo, true miss | `"gobln"` raises `ToolError` starting `No SRD monster named "gobln". Did you mean: Goblin` (at most 3 names); `"Zorbax the Unknowable"` and an empty catalog return `None`. |

### WP-7: the tool (`tests/test_monster_tool.py`; imports `run`, `NAME`, `HELP`, `TRAINING_DISCLAIMER`, `build_monster_prompt`)
| ID | Test | Expected |
|---|---|---|
| T-21 | contract, empty, help | `NAME == "monster"`; `""`, `"  "`, `"\n\t"` raise `ToolError("Usage: /monster <monster name> [2014|2024]")`; `run("help", ctx)` is `{"text": HELP, "meta": {"tool": "monster", "help": True}}`; no `generate`. |
| T-22 | hit | `run("  goblin ", ctx)` equals `{"text": render_stat_block(goblin), "meta": {"tool": "monster", "source": "creatures", "creature_ids": ["goblin"]}}`; ambiguity and typo `ToolError`s propagate; no `generate`. |
| T-23 | true miss | text `"MODEL REPLY\n\n" + TRAINING_DISCLAIMER` (`"Not checked against the SRD monster text."`); meta `{"tool": "monster", "source": "training", "creature_ids": []}`; `prompts == [build_monster_prompt("Zorbax the Unknowable")]`; same with no `reference`, `{}`, `{"creatures": None}`, `[]`. |
| T-24 | builder, no voice | `build_monster_prompt("  Beholder ") == "MONSTER: Beholder\n\n" + MONSTER_DIRECTIVES_TRAINING`; no `DM_ROLE_PROMPT`, `"VOICE:"`, `"SYS:"`; `IntelligenceError` from `generate` propagates. |
| T-25 | store, logs | a `store` raising on any attribute is never touched; `caplog`: a hit logs one `monster.lookup` (`source=="creatures"`, `creature_count==1`, `rendered_chars==len(text)`), a miss one with `"training"`, `0`, `0`; no record holds the query (`"Zorbax ZZMARKER"`), a name, stat text or prompt. |
| T-26 | source hygiene | `tools/monster.py` and `monster_blocks.py` contain none of `dnd_data`, `open5e`, `httpx`, `open(`, `.read_text(`, `build_narrator_prompt`, nor import `scripts`. |

### WP-8: discovery and dispatch (`tests/test_tool_calling.py`, `tests/test_slash_dispatch.py`)
| ID | Test | Expected |
|---|---|---|
| T-27 | discovery | `list_tools()["monster"] == "app.intelligence.tools.monster"`; `get_registry(refresh=True)` names equal the service list and include `roll`, `narrate`, `rules`, `monster`. |
| T-28 | invoke | server catalog holds Goblin; `invoke("monster", "goblin", client_context={"reference": {"creatures": []}})` gives `creature_ids == ["goblin"]`. |
| T-29 | worker hit | `/monster goblin` (catalog in `slash_env.ts.default_context["reference"]`): `[user, assistant]`, user `completed`, `content == render_stat_block(goblin)`, meta `{"tool","source":"creatures","creature_ids":["goblin"],"reply_to": user id}`, no chat call. |
| T-30 | worker miss, typo | `/monster Zorbax`: `"stub reply\n\n" + TRAINING_DISCLAIMER`, `source == "training"`, one chat call equal to `build_monster_prompt("Zorbax")`; `/monster gobln` (Goblin in catalog): user `status == "error"`, no chat call. |

## 3. Work Packages

### WP-1: creatures projection, measurement, size rule (script only)
- **Files:** edit `scripts/ingest_open5e.py`; new `tests/test_ingest_creatures.py`. No `dnd_data/` or network.
- **Inputs:** the script's `build_records`, `_flatten`, `_DATASET_FIELDS` hook (as `weapons` uses it), `render`, `MAX_BYTES`, `main`. Upstream creature keys: `size`/`type` `{name,key}`; `languages.as_string`; `resistances_and_immunities.{damage_vulnerabilities,damage_resistances,damage_immunities,condition_immunities}_display`; senses `blindsight_range`, `darkvision_range`, `tremorsense_range`, `truesight_range`; `actions[]` with `action_type`, `order_in_statblock`, `legendary_action_cost`, `usage_limits {type, param}`; `document` is already a dict.
- **Outputs:** `DOCUMENT_ALLOWLIST["creatures"] = DEFAULT_DOCUMENTS`; `CONSUMERS["creatures"] = "/monster tool (REQ-0031)"`; `PROJECTION["creatures"] = (id, name, edition, source, publisher, third_party, source_key, size, type, alignment, armor_class, armor_detail, hit_points, hit_dice, speed, ability_scores, saving_throws, skill_bonuses, damage_vulnerabilities, damage_resistances, damage_immunities, condition_immunities, passive_perception, senses, languages, cr, experience_points, traits, actions, bonus_actions, reactions, legendary_actions)`; `_creature_fields(raw)` in `_DATASET_FIELDS`; `measure_projection(dataset, entries) -> dict` (T-5; uses `build_records(..., allowlist=...)`, `render`, the module `MAX_BYTES`; `allowlist` is both SRDs when the both-SRD bytes are `<= MAX_BYTES`, else `["srd-2024"]`); `main` accepts `--measure <dataset>`: prints that result as JSON from `dnd_data/<dataset>.json`, writes nothing. Tests T-1 to T-5.
- **Acceptance criteria:** projection per T-1 to T-3; string fields default to `""`; `traits` is `[{name, desc}]` in raw order; `speed` has no `unit`/`hover`; `usage`/`cost` omitted when null; empty lists emitted. T-1 to T-5 pass; gate green.
- **Patterns used/created:** PAT-ARCH-007, 006.

### WP-2: `Creature` model and test helper
- **Files:** new `app/reference/creatures.py`; new `tests/creature_fixtures.py`; new `tests/test_creature_model.py`.
- **Inputs:** the WP-1 projection key list; precedent `app/reference/rules.py` (`RULES_PATH`, `Rule`).
- **Outputs:** `CREATURES_PATH` (`Path(__file__).resolve().parent / "creatures.json"`); all models `ConfigDict(extra="forbid")`; `StatEntry(name, desc, usage: str | None = None, cost: int | None = None)`; `AbilityScores` (six ints `strength` .. `charisma`); `Creature`, one field per WP-1 projection key. Required: `id` (pattern `^[a-z0-9]+(-[a-z0-9]+)*$`), `name`, `edition` (`Literal["5e","5.5e"] | None`), `source`, `publisher: str | None`, `third_party: bool`, `source_key`, `cr: float`. All others default (`None` for nullable scalars, `""` for strings, `{}` for the `dict[str, int]` fields, all-10 `ability_scores`, `[]` for the five `list[StatEntry]` lists). `make_creature` builds a valid `Creature` (id is the name slug, plus `-5e` for `"5e"`; fixed `source`, `publisher`, `source_key`, `cr=0.25`; then `**overrides`). Tests T-7, T-8.
- **Acceptance criteria:** as T-7, T-8; field names equal the WP-1 projection keys.
- **Patterns used/created:** PAT-ARCH-006.

### WP-3: generate and commit `app/reference/creatures.json`; apply the 2 MB rule
- **Files:** new `app/reference/creatures.json` (generated, never hand-edited); `app/reference/ATTRIBUTION.md`, `LICENSE-OGL.txt` (expected unchanged); edit `tests/test_reference_budget.py`; new `tests/test_creatures_dataset.py`; edit `scripts/ingest_open5e.py` only for the fallback.
- **Inputs:** WP-1, WP-2; local gitignored `dnd_data/creatures.json` and `_documents.json`; if missing, stop and report (never hand-write the data or run the sync script).
- **Outputs:** first run `python -m scripts.ingest_open5e --measure creatures`. **Rule:** if `fits_both`, keep both SRDs; else set `DOCUMENT_ALLOWLIST["creatures"] = [SRD_2024]` (human decision; no field trimming). Then run `python -m scripts.ingest_open5e creatures` twice. Tests T-9, T-10. Commit note: measured both-SRD bytes and the allowlist chosen.
- **Acceptance criteria:** second run changes nothing; at most 2,000,000 B and 2,000 entries; 656 (both) or 331 (2024 only) entries, else stop and report; `load_entries(CREATURES_PATH, Creature, "creatures")` loads every entry with no warning; ATTRIBUTION `git diff` empty. If ingest raises (for example an unknown `action_type`), stop and report. T-9, T-10 pass.
- **Patterns used/created:** PAT-ARCH-006, PAT-ARCH-007.

### WP-4: load the catalog at startup (fail-soft)
- **Files:** edit `app/services/build_services.py`; new `tests/test_creatures_wiring.py`.
- **Inputs:** WP-2 (`Creature`, `CREATURES_PATH`), WP-3 (the committed file).
- **Outputs:** import `CREATURES_PATH, Creature`; add `"creatures": load_entries(CREATURES_PATH, Creature, "creatures")` to `reference`. Tests T-11, T-12.
- **Acceptance criteria:** as T-11, T-12; `services` keys stay `session, tool, inference, reference, world`; no GET route; existing wiring tests pass.
- **Patterns used/created:** PAT-ARCH-006.

### WP-5: pure stat-block renderer
- **Files:** new `app/intelligence/monster_blocks.py`; new `tests/test_monster_render.py`.
- **Inputs:** WP-2 (`Creature`, `make_creature`). Imports only stdlib and `app.reference.creatures`; no I/O, no logging, no store.
- **Outputs:** `render_stat_block(creature: Creature) -> str`; tests T-13 to T-16.
- **Acceptance criteria:** lines joined by `"\n"`, no trailing newline, in this order, each omitted when empty: `{name} (2014)` (`(2024)` for `5.5e`, no suffix for `None`); `{size} {type}, {alignment}`; `AC {n}` plus ` ({armor_detail})`; `HP {n} ({hit_dice})`; `Speed walk 30 ft., fly 60 ft.` (walk, burrow, climb, fly, swim); `STR 20 (+5) DEX 12 (+1) CON 18 (+4) INT 20 (+5) WIS 20 (+5) CHA 18 (+4)` (modifier `(score - 10) // 2`); `Saving Throws Dex +5, Con +8`; `Skills Animal Handling +5, Stealth +5` (sorted by key); `Damage Vulnerabilities {s}`, `Damage Resistances {s}`, `Damage Immunities {s}`, `Condition Immunities {s}`; `Senses darkvision 120 ft., passive Perception 15` (alphabetical, values `> 0`); `Languages {s}` (`—` when empty, always shown); `CR {cr} (XP {xp:,})` (`1/8`, `1/4`, `1/2`; whole numbers without `.0`). Then per non-empty list, in order traits, actions, bonus actions, reactions, legendary actions: an empty line, a heading (`Traits`, `Actions`, `Bonus Actions`, `Reactions`, `Legendary Actions`), one line per entry `{name}{suffix}. {desc}`, suffix ` ({usage})` when set and ` (Costs {cost} Actions)` when `cost > 1`. Text is never truncated or reworded. T-13 to T-16 pass.
- **Patterns used/created:** PAT-ARCH-011.

### WP-6: name matching
- **Files:** edit `app/intelligence/monster_blocks.py`; new `tests/test_monster_lookup.py`.
- **Inputs:** WP-5 module; `ToolError` from `app.intelligence.tools`; precedent `_norm` and `_lookup` in `tools/attack.py`; stdlib `difflib` only.
- **Outputs:** `find_creature(query: str, creatures: list[Creature]) -> Creature | None`; tests T-17 to T-20.
- **Acceptance criteria:** normalize with `re.sub(r"[\W_]+", " ", text.casefold()).strip()`. A final token `2014`/`2024` (name left non-empty) is stripped and restricts editions to `5e`/`5.5e`. Exact normalized name first, then substring (query inside name). Several distinct names: `ToolError` (`matches several monsters`) listing the first 5 sorted names. One distinct name: 5.5e preferred, then non-third-party, then lowest `id`. No match: if `difflib.get_close_matches(normalized, normalized names, n=3, cutoff=0.8)` is non-empty raise `ToolError(f'No SRD monster named "{query}". Did you mean: {original names, comma-joined}?')`, else return `None` (also for an empty catalog or query). Pure. T-17 to T-20 pass.
- **Patterns used/created:** PAT-ARCH-011.

### WP-7: the `/monster` tool and training prompt builder
- **Files:** new `app/intelligence/tools/monster.py`; edit `app/intelligence/prompt_builders.py` (add only `MONSTER_DIRECTIVES_TRAINING`, `build_monster_prompt`); new `tests/test_monster_tool.py`.
- **Inputs:** WP-5, WP-6; precedent `tools/rules.py` and `build_rules_prompt` (one-shot, no voice).
- **Outputs:** `build_monster_prompt(name) -> f"MONSTER: {name.strip()}\n\n" + MONSTER_DIRECTIVES_TRAINING` (constant: asks for a plain-text 5e stat block from general knowledge, to say plainly if the monster is unknown, no narrator voice). In `monster.py`: `NAME`, `_USAGE` (the T-21 text), `HELP`, `TRAINING_DISCLAIMER = "Not checked against the SRD monster text."`, `logger = get_logger(__name__)`, `run`. Tests T-21 to T-26.
- **Acceptance criteria:** `text = (args or "").strip()`; empty raises `ToolError(_USAGE)` first; `"help"` gives the T-21 result. Catalog is `(context.get("reference") or {}).get("creatures") or []`; `find_creature(text, catalog)` errors propagate. Hit: result per T-22, no `generate`. `None`: one `context["inference"].generate(build_monster_prompt(text))`, result per T-23 (text is `reply.rstrip() + "\n\n" + TRAINING_DISCLAIMER`; `generate` errors propagate). One `logger.info("monster.lookup", extra={"source", "creature_count", "rendered_chars"})` per call (`rendered_chars` is `len(text)` on a hit, else 0); never log the query, names, text or prompts. No store, file, `dnd_data`, open5e or narrator-voice use. T-21 to T-26 pass.
- **Patterns used/created:** PAT-ARCH-011, 009 (rules 1, 5-7), 004, 003, PAT-CODE-001.

### WP-8: discovery and dispatch tests, tool contract doc
- **Files:** edit `tests/test_tool_calling.py` (add T-27, T-28); edit `tests/test_slash_dispatch.py` (add T-29, T-30); edit `.github/instructions/tools.instructions.md`. Keep existing tests unchanged.
- **Inputs:** WP-1 to WP-7; `FakeInference` (`tests/test_tool_calling.py`); `slash_env`, `_post`, `wait_idle` and the `/rules` tests (`tests/test_slash_dispatch.py`).
- **Outputs:** T-27 to T-30; in the doc: add `"creatures"` to the `context["reference"]` key list, a sentence that PAT-ARCH-011 tools (`/attack`, `/monster`) render a catalog entry with code, and `tests/test_monster_tool.py` in the last bullet.
- **Acceptance criteria:** as T-27 to T-30; doc edits additive; no pattern or ADR edits.
- **Patterns used/created:** PAT-ARCH-004, 011.

## 4. Other Details
- **Risks:** size unmeasured until WP-1/3 (the rule handles it); upstream `action_type`/`usage_limits.type` values not all seen (WP-3 stops on an unknown action type); `hover` not kept; the 0.8 typo cutoff may catch homebrew names.
- **Rollback:** additive; delete the new modules, `creatures.json`, the `build_services` line and script entries.
- **Patterns:** PAT-ARCH-011, 009, 004, 006, 007, 003, PAT-CODE-001 applied; none created.
- **Non-goals:** encounter building, a monster picker UI, roll cards for `/monster`, a chars-budget setting, a GET route, non-SRD monsters, aliases, `hover`.
