---
id: ADR-0017
status: accepted
date: 2026-11-08
requirement: REQ-0037
supersedes: null
superseded_by: null
---

# Plain chat is an admin side-chat; `/narrate` takes over the conversational narrator pipeline; one tool guide constant

## Context
REQ-0037 (`docs/requirements/LOG.md`). Patterns opened: PAT-ARCH-003, 004, 012, 013; 014 from the INDEX.

| Fact | Where |
|---|---|
| Plain chat uses the narrator system prompt (DM role sentence "Narrate the world...", `dm_voice` text, VOICE line) + character + canon world + history | `inference_service._worker_loop` else-branch, `build_system_prompt` |
| `/narrate` is one-shot: `build_narrator_prompt(args)`, no history, character or canon | `tools/narrate.py` |
| PAT-ARCH-003 Context already anticipates tool-driven narration using this pipeline | PAT-ARCH-003 |
| `message_kind(None)` = narrative; plain replies written with `kind: narrative` | `tool_handler.py`, worker |
| Mining guard is `name in (None, "narrate")` | worker, PAT-ARCH-012 rule 3 |
| Admin rows: AdminCard (collapsible, no edit/regenerate, no entity marks), hidden by the narrative-only toggle, omitted from the diary | `NarrativeLog.tsx`, `AdminCard.tsx`, `DiaryModal.tsx` |
| Client turn counter counts only non-admin user rows without a tool reply; if none exist it renders nothing | `NarrativeLog.tsx` `VISIBLE_TURNS` loop |
| DESCRIPTIONs are 5-8 words, no syntax; `/rules` selector needs a rule-name token (MIN_SCORE 3); `/rule` is an unknown tool | `tools/*.py`, `rules.py` |
| `dm_analysis` voice text exists and is unused | `voice_configs.json` |

| Trigger | Fired | Fact |
|---|---|---|
| Two viable approaches | yes | D1, D2, D3 below |
| Accepted-pattern change | yes | PAT-ARCH-003, 004, 012, 013 wording |
| Cross-cutting convention | yes | what "plain chat" means for kind, mining, context |
| Hard to reverse / new dependency | no | no migration, no package |

## Decision Drivers
Scores 1-5; High 3, Medium 2, Low 1 (`docs/constraints.md`). Max 90.

| Dimension | W | Why |
|---|---|---|
| Simplicity, Reversibility, Maintainability | 3 each | standing |
| Reuse, Fun/learning | 2 each | standing |
| Performance, Security | 1 each | standing, de-prioritised |
| Requirement fit (added) | 3 | MUSTs: no narration in plain chat, tool-aware steering, narration only via `/narrate` |

## Considered Options
- **D1 narration route.** N1 `/narrate` unchanged (one-shot). N2 worker sends `/narrate <args>` through the existing chat pipeline (narrator system prompt unchanged, current text = args); plain text goes through the same pipeline with a side-chat system prompt. N3 the narrate tool assembles the conversational prompt itself from new context keys.
- **D2 kind.** K1 plain user row and side-chat reply are `admin`. K2 a third `MessageKind` (`aside`). K3 keep `narrative`, add a `meta.sidechat` flag.
- **D3 tool knowledge.** T1 inject `list_tool_descriptions()` only. T2 new per-tool `USAGE` field in the tool contract. T3 one `TOOL_GUIDE` constant in `prompt_builders.py` (per tool: when, syntax, example phrasing) plus a test that every discovered tool name appears in it.

## Rubric Scoring
Order: Simp, Rev, Maint (x3); Reuse, Fun (x2); Perf, Sec (x1); Fit (x3).

| Option | Scores and one-line facts | Total |
|---|---|---|
| N1 | 5 no change; 5; 4; 4; 2; 5 short prompt; 4; 2 sole narrator loses history, character, canon that chat has today | 69 |
| N2 | 4 one branch condition + args as current text; 4; 4 REST invoke keeps the one-shot path; 5 reuses builder, character, `_inject_world` as-is; 3; 4 up to 6x240 chars history; 4; 5 | **75** |
| N3 | 2 tool needs system prompt, species map, world store via context; 3; 3 duplicates worker assembly; 3; 4; 4; 3 new server context keys; 5 | 60 |
| K1 | 5 flip `message_kind(None)` + reply literal; 5 old rows untouched; 4 toggle-on hides side-chat; 5 AdminCard = visual cue, diary and context filters reused; 3; 5; 4; 4 loses edit/regenerate and marks in UI | **79** |
| K2 | 2 enum, builder filter, TS type, new render, diary, WS doc; 4; 3 every `isAdmin` reader must learn a third value; 3; 4; 5; 4; 5 | 65 |
| K3 | 3 new reserved key + filters; 4; 2 second classification axis against PAT-ARCH-013; 3; 2; 5; 4; 2 advice leaks into diary and narrative-only context unless every reader changes | 52 |
| T1 | 5; 5; 4 auto-tracks tools; 5 REQ-0034 method; 2; 5; 4; 2 no syntax or phrasing (`/attack ... vs <AC>`, rule-name keyword) | 71 |
| T2 | 2 five modules, service, contract test, PAT-ARCH-004 rule 1; 3; 4; 3 HELP in 3/5, `_USAGE` private in 2; 3; 5; 4; 5 | 63 |
| T3 | 4 one constant, one test; 5; 3 drift test catches names, not syntax changes; 4 constant style of `RULES_DIRECTIVES_*`, reuses `dm_analysis`; 4; 4 ~1 KB more system text; 4; 5 | **75** |

## Decision Outcome
**N2 (75) + K1 (79) + T3 (75).** The existing narrator pipeline moves to `/narrate` unchanged;
plain chat reuses the same builder with a different system message, so no new builder
shape. Traded away: edit/regenerate buttons and entity marks on side-chat (AdminCard),
and a single narrator implementation (REST `/intel/tools/narrate/invoke` stays one-shot).

| Concern | Decision |
|---|---|
| Plain user row kind | `admin` (`message_kind(None)`); legacy rows keep their stored/missing kind (narrative) |
| Side-chat reply kind | `admin`, `meta` has no `tool` |
| `narrative_only` on | builder drops prior side-chat rows from both narrate and side-chat context; client hides side-chat cards (as `/rules` today) |
| Admin card | side-chat renders as AdminCard (header = question, body = advice): the minimal cue, no new CSS |
| Diary | side-chat omitted (existing `isAdmin` filter) |
| Mining | `/narrate` replies only; guard becomes `name == "narrate"` |
| Canon + character injection | yes for side-chat: same branch, budget-bound, the advisor needs world facts |
| Entity marks | narrative Bubbles only; none in side-chat cards (PAT-ARCH-014 unchanged) |
| Side-chat system message | new pure builder: veteran-DM out-of-fiction role sentence (no narration, role-play or scene description), `dm_analysis` text, `TOOL_GUIDE`; no VOICE line; built once in `__init__` |
| Client | turn counter MUST count side-chat rows and `/narrate` commands as turn starts, else the log renders empty |

## Consequences
- Positive: no migration, Protocol or dependency change; narration gains nothing new, it just moves.
- Negative: plain chat no longer advances the story; toggle-on users see side-chat vanish.
- Risk: with the toggle off, side-chat advice is in narrator history (existing semantics).
- Tests to update: `test_message_kind` T-1, `test_messages_helper` (plain kind),
  `test_prompt_pipeline` (system prompt, reply kind), `test_inference_reply`,
  `test_slash_dispatch` (`/narrate` now via `client.chat`; plain reply kind),
  `test_world_detection_worker` (chat no longer mined), `test_character_wiring`,
  `test_world_injection` (system message variant). `test_prompt_builders` and
  `test_tool_calling` narrator assertions stay; new builder and guide-drift tests added.

## Pattern Impact
No new pattern. The owner accepted these amendments (applied in SPEC-0023 WP-6):
- **PAT-ARCH-013 rule 2:** no tool (plain chat = side-chat) is admin; `NARRATIVE_TOOLS` narrative; others admin.
- **PAT-ARCH-012 rule 3:** `/narrate` replies only; side-chat and other tools never mined.
- **PAT-ARCH-003 rules 3 and 5:** two system messages (narrator for `/narrate`, side-chat for plain text); `/narrate` jobs use the chat builder with args as current text; other slash jobs skip it.
- **PAT-ARCH-004 rule 3:** the worker routes `/narrate` to the PAT-ARCH-003 pipeline, not `invoke`; reply meta `{tool, kind, reply_to}` unchanged; module kept for discovery, picker and REST invoke.

Owner decisions: no `/rule` alias (the guide uses `/rules`); narrative-only hides plain Q&A like `/rules`; `/narrate` gets history, character and canon facts; `/narrate` args are not diary "You" entries; side-chat cards have no Edit/Regenerate and no entity marks; the empty-log text points at `/narrate`.
