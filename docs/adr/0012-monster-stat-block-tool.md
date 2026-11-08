---
id: ADR-0012
status: accepted
date: 2026-11-07
requirement: REQ-0031
supersedes: null
superseded_by: null
---

# `/monster`: SRD creatures projected into `app/reference/creatures.json`, exact name lookup with a deterministic stat-block render, LLM training fallback only on a true miss

## Context
REQ-0031 (`docs/requirements/LOG.md`). Triggers: a new committed dataset (PAT-ARCH-006/007), two viable designs, and the scope of accepted PAT-ARCH-009. Later encounter building must stay possible.

| # | Finding | Evidence |
|---|---|---|
| F1 | Both SRDs: 656 creatures, 2,692,306 B at the WP-5 candidate projection, over the 2 MB cap. srd-2014 alone 1,412,798 B (325); srd-2024 alone 1,278,662 B (331) | `dnd_data/_budget_creatures.json` |
| F2 | `actions` is 1,127,482 B (42%); each raw action carries `attacks[]` (about 400 B per attack, a structured copy of `desc`) plus bookkeeping keys | `field_bytes`; first entry of `dnd_data/creatures.json` |
| F3 | Reactions and legendary actions are `actions` items with `action_type`; senses are `passive_perception` and `*_range` ints; `languages` is `{as_string, data}`; `size`/`type` are `{name, key}` | first entry of `dnd_data/creatures.json` |
| F4 | srd-2014 (CC-BY-4.0, OGL 1.0a) and srd-2024 (CC-BY-4.0) are already allowlisted and covered by `ATTRIBUTION.md` and `LICENSE-OGL.txt` | `app/reference/`, `scripts/ingest_open5e.py` `DOCUMENT_ALLOWLIST` |
| F5 | The `/rules` selector scores keywords over body text, packs within 6,000 chars, then one `generate` answers a question | `app/intelligence/tools/rules.py`, `settings.json` |
| F6 | `/attack` already does exact-then-substring name lookup, 5.5e preferred, ambiguity as `ToolError`, no LLM; PAT-ARCH-009 Context excludes such lookups | `app/intelligence/tools/attack.py` `_lookup` |
| F7 | Ollama runs at the server default context (2k-4k tokens); all calls share `_ollama_lock` | ADR-0009 F9/F10 |
| F8 | The aboleth's action and trait text alone is about 2,700 chars; legendary dragons are longer (estimate) | first entry of `dnd_data/creatures.json` |
| F9 | `load_entries`, `context["reference"]` and the `OPEN5E_MODELS` budget test exist | `app/reference/loader.py`, `app/services/build_services.py` 34-47, `tests/test_reference_budget.py` |

## Decision Drivers
Scores 1-5; weights High 3, Medium 2, Low 1 (`docs/constraints.md`). Max 120.

| Dimension | W | Why it matters here |
|---|---|---|
| Simplicity / smallest edit | 3 | solo, part-time |
| Reversibility | 3 | the dataset stays in git history whatever we pick |
| Maintainability | 3 | one maintainer |
| Reuse of patterns/deps | 2 | ingest, loader, `/attack` lookup exist |
| Fun / learning | 2 | constraint 5 |
| Performance | 1 | household scale |
| Security | 1 | dev token only |
| Faithfulness (added) | 3 | the DM reads AC, HP and to-hit numbers aloud at the table |
| Latency (added) | 2 | one shared Ollama lock (F7) also serves `/narrate` |
| Coverage beyond SRD (added) | 3 | owner asked for stat blocks; SRD lacks many iconic monsters; REQ MUST |
| Fit to REQ-0031 wording (added) | 1 | the wording may be amended with sign-off |

## Considered Options
- **A. PAT-ARCH-009 verbatim**: rules-style scorer over creatures, whole blocks packed within a new `prompts.monster_budget_chars`, one `generate` answers.
- **B. Hybrid**: `/attack`-style name lookup; a hit is rendered by code (no LLM); ambiguity or a near-typo is a `ToolError`; only a true miss makes one flagged training-mode `generate`.
- **C. Deterministic only**: as B, but a miss is a `ToolError`; no LLM anywhere.
- **D. A plus extracting a shared selector** from `rules.py` now.
- Status quo rejected: fails every MUST.

## Rubric Scoring
| Dim (W) | A | B | C | D |
|---|---|---|---|---|
| Simplicity (3) | 3: scorer, builder, setting; body-text scoring ranks other blocks that mention "goblin" | 4: ~15-line lookup (F6 shape), a render function, a small training builder | 5: lookup and render only | 2: A plus a refactor of shipped `rules.py` and its tests |
| Reversibility (3) | 4: additive; dataset in history | 4: same | 4: same | 3: also changes `/rules` |
| Maintainability (3) | 3: scorer and prompt tuning; numbers in LLM output untestable | 4: render tested by exact string; one small prompt | 5: no prompt | 3: shared code with two divergent needs |
| Reuse (2) | 5: `/rules` template 1:1 | 4: `/attack` lookup, loader, PAT-ARCH-009 rules 1 and 4-7 | 4: `/attack` lookup, loader | 5 |
| Fun (2) | 3 | 4: ETL plus stat-block formatting | 3 | 4: refactor exercise |
| Performance (1) | 3: ~1k-token generation per lookup | 5: hit is a dict scan | 5 | 3 |
| Security (1) | 3: no new surface | 3 | 3 | 3 |
| Faithfulness (3) | 2: 8B model restates ~30 numbers labelled `source=creatures`; blocks over budget (F8) fall to training | 5: catalog text verbatim; misses flagged | 5: never invents | 2: as A |
| Latency (2) | 2: every lookup holds the lock for a long generation | 4: hits instant; misses one call | 5 | 2 |
| Coverage (3) | 4: flagged training answer | 4: same, only for true misses | 1: homebrew or non-SRD gets nothing | 4 |
| Fit (1) | 5 | 3: keeps catalog, determinism, flagged fallback; drops the chars budget | 1: drops the fallback | 5 |
| **Weighted total** | **79** | **98** | **93** | **75** |

Sensitivity: B beats C while Coverage is weighted Medium or higher (94 vs 92 at 2); at Low, C wins (90 vs 91).

## Decision Outcome
**Chosen: B (98).** Structured, exact data needs no model on a hit, so this is faster and 100% faithful. The flagged fallback still serves monsters that are not in the SRD. Trade-off: REQ-0031's "chars budget" wording and the `/rules` code shape are given up.

1. **Projection (`creatures`, consumer "/monster tool (REQ-0031)", srd-2014 + srd-2024).** Keep `id, name, edition, source, publisher, third_party, source_key`, `size` and `type` (name strings), `alignment, armor_class, armor_detail, hit_points, hit_dice, speed`, `ability_scores`, `saving_throws` and `skill_bonuses` (non-null only), damage and condition immunity/resistance/vulnerability display strings, `passive_perception` and non-null sense ranges, `languages` (`as_string`), `cr` (float), `experience_points`, `traits[{name, desc}]`, and `actions`, `bonus_actions`, `reactions`, `legendary_actions` split by `action_type`, ordered by `order_in_statblock`, each `{name, desc, usage?, cost?}`. Drop `attacks[]`, `crossreferences`, `modifiers`, `*_all`, `document`, `languages.data`, `limited_to_form`, `proficiency_bonus` and unused upstream keys. **Size estimate 0.9-1.3 MB (not measured).** Spec WP-1 measures the final projection (extend `measure()`) before committing; `check_budget` and `test_reference_budget.py` stop anything over 2 MB. Measured fallback: srd-2024 only (F1), a human choice, not the SQLite tier.
2. **Model and wiring.** `app/reference/creatures.py` (`Creature` plus an action submodel, `extra="forbid"`), loaded fail-soft by `load_entries` into `reference["creatures"]`, added to `OPEN5E_MODELS`. No GET route (PAT-ARCH-006 rule 5). Memory: a few MB (estimate).
3. **Lookup** in `app/intelligence/tools/monster.py`, normalized as in `/attack`, optional trailing `2014`/`2024` filter: exact name, then substring; several distinct names give a `ToolError` listing up to 5; one name in both editions resolves to 5.5e unless filtered.
4. **Hit.** A pure `render_stat_block(creature) -> str` renders the whole block in stat-block order, computes modifiers and never truncates. `meta = {tool: "monster", source: "creatures", creature_ids: [id]}`.
5. **Miss.** If stdlib `difflib` finds close names (cutoff 0.8), raise a `ToolError` "Did you mean ..." so a typo never invents a block. Otherwise use training mode: a pure `build_monster_prompt(name)` (no voice), one `generate`, and the fixed "Not checked against the SRD monster text." appended. `source: "training"`, `creature_ids: []`.
6. **No budget setting**: no excerpt is ever placed in a prompt, so it would have no reader. If the wording is kept, it goes in `prompts.monster_budget_chars` (rules precedent; `world` is ADR-0010's).
7. **Logs** record counts only: source, entry count, rendered chars. Never the query.
8. **No shared code.** `/monster` does not use the rules scorer (F5), so it is not a second selector call site. Its lookup overlaps `/attack._lookup`, but its miss behaviour differs. Extract it at a third name-lookup tool (PAT-ARCH-011).
9. **Encounter-ready.** `cr`, `experience_points`, `type`, `size`, `hit_points` and `armor_class` stay typed fields.

## Consequences
- Positive: instant, exact blocks; offline tests (literal entries, stubbed `generate`); attribution already in place (F4).
- Negative: two reply paths; about 1 MB more in git; hand-written formatting.
- Risks: size was unmeasured when decided; WP-1 measured both SRDs at 1,452,161 B (656 entries), under the 2 MB cap, so both ship. A loose typo cutoff sends homebrew names to "Did you mean"; the 5.5e default may surprise a 2014 table (filter token).

## Pattern Impact
- Uses PAT-ARCH-004, 006, 007 unchanged, and PAT-ARCH-003's one-shot builder carve-out.
- **Creates PAT-ARCH-011** (accepted 2026-11-07): structured reference lookup tools.
- **PAT-ARCH-009 (accepted), amendment signed off 2026-11-07 and applied:** (a) Context: a tool that renders a matched entry deterministically (PAT-ARCH-011) applies only rules 1 and 4-7, to its training fallback; (b) "no shared code until a second grounded tool" became "until a second tool uses the keyword selector".
- **REQ-0031 wording, signed off 2026-11-07 and applied in the LOG:** "selected deterministically within a settings-held chars budget" became "looked up deterministically by name and rendered without an LLM, with a flagged training fallback only when no SRD name matches".
