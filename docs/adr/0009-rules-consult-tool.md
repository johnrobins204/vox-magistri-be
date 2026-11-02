---
id: ADR-0009
status: accepted
date: 2026-11-01
requirement: REQ-0024
supersedes: null
superseded_by: null
---

# `/rules` consult tool: deterministic keyword selection over an in-memory SRD `rules` catalog, a settings-held excerpt budget, and an explicit training-data fallback

## Context
REQ-0024 (`docs/requirements/LOG.md` line 17) asks for a slash tool that lets the DM ask a
rules question and get a plain, non-narrator answer grounded in SRD rules text. The tool must
use the in-memory reference catalog (PAT-ARCH-006), never `dnd_data/` or open5e at runtime
(PAT-ARCH-007), and must fall back to model training data, flagged in `meta.source`, when no
grounded answer is possible. The owner's words: "If the rules are too big at the moment, it
can just respond from training data."

The full SRD `rules` corpus (about 297,000 characters of `desc`) cannot go into one Ollama
prompt, so the tool needs a **selection step** and a **bounded budget**. How to select is the
real decision.

Patterns consulted (INDEX.md): PAT-ARCH-003 (prompt builders), PAT-ARCH-004 (slash tools),
PAT-ARCH-006 (reference data), PAT-ARCH-007 (bulk upstream ingest), PAT-CODE-001 (logging), all
accepted; PAT-ARCH-005 (proposed). PAT-ARCH-001/-002/-008 are not touched.

**ADR triggers (docs/adr/README.md):**

| Trigger | Result | Reason |
|---|---|---|
| Two or more viable approaches | **Fired** | Keyword selection (A), LLM-assisted selection (B) and LLM-picks-from-index (C) all work |
| Changes a cross-cutting convention | **Fired** | First reference dataset carrying verbatim rules text, which forces a scoping decision on REQ-0018's "short summaries" rule for all PAT-ARCH-006 datasets; first tool to read `context["reference"]`; introduces the `meta.source` grounding convention |
| Deviates from an accepted pattern | **Borderline** | PAT-ARCH-006 rule 5 / REQ-0018 read as "each dataset gets a GET route", but REQ-0024 freezes the reference routes. Resolved below without a deviation; a clarification is flagged for sign-off |
| New dependency / external service | Not fired | stdlib `re` plus existing pydantic, Ollama |
| Costly or hard to reverse | Not fired | Everything is additive. Rule ids are not referenced by user data |

**Verified facts (tree on 2026-11-01):**

| # | Fact | Where |
|---|---|---|
| F1 | `/narrate` builds a voice prompt with `build_narrator_prompt` and calls `context["inference"].generate(prompt)` once; returns `{"text","meta":{"tool"}}` | `app/intelligence/tools/narrate.py` |
| F2 | Tools in the package today: `roll`, `narrate`. No `rules` name collision | `app/intelligence/tools/*.py` |
| F3 | `reference` is already in the tool `default_context`, so clients cannot override it; no tool reads it yet | `app/services/build_services.py` lines 31-41, `app/services/tool_service.py` lines 15-19, 129-136 |
| F4 | Shared fail-soft loader exists: `load_entries(path, model, dataset)` (rule 8 of PAT-ARCH-006 already satisfied by `weapons`) | `app/reference/loader.py` |
| F5 | Ingest has per-dataset `DOCUMENT_ALLOWLIST`, `PROJECTION`, `CONSUMERS`, budget check (2,000,000 bytes / 2,000 entries) and edition-aware id assignment (5.5e owns the bare slug, 5e gets `-5e`) | `scripts/ingest_open5e.py` lines 27-68, 137-178, 225-233 |
| F6 | Raw `rules` entries carry `document` as a **plain string** (`"document": "srd-2024"`), and no `descriptions[]` and no `gamesystem` key. The generic `_flatten` reads `raw["document"]["key"]`, `doc["display_name"]`, `doc["publisher"]["name"]`, and `_description` reads `descriptions[]` | `dnd_data/rules.json` (first entries), `scripts/ingest_open5e.py` lines 84-129 |
| F7 | `rules` = 283 entries, 360,542 bytes raw; 227 `srd-2014`, 56 `srd-2024`; about 297,000 chars of `desc`, so about 1,050 chars per entry on average | measured profile (brief), consistent with F6 sample |
| F8 | The CI budget test globs every `app/reference/*.json`; open5e datasets register in `OPEN5E_MODELS` for the no-dropped-entry test | `tests/test_reference_budget.py` lines 17-56 |
| F9 | `OllamaClient.chat` sends no `options.num_ctx`, so the Ollama **server default** context applies (2,048 tokens on older releases, 4,096 on newer; the installed version was not verified) | `app/intelligence/client.py` lines 56-66 |
| F10 | One FIFO worker; tools run outside `_ollama_lock`, but each `generate` takes it, so every extra LLM call delays the next chat message | `app/services/inference_service.py` lines 68-72, 190, 250, 339-341 |
| F11 | PAT-ARCH-003 carve-out: one-shot prompts with no session history may return a single string (`build_narrator_prompt` does) | PAT-ARCH-003 Context; `app/intelligence/prompt_builders.py` line 137 |
| F12 | Settings are pydantic namespaces with defaults; `prompts` holds the narration knobs | `app/config.py` lines 63-67, `settings.json` |
| F13 | The "short summaries, no verbatim rules text" sentence sits in REQ-0018 between the species picker and Hollow One sentences; ADR-0006 gives its reason: "The data paraphrases commercial and third-party sourcebooks"; SPEC-0011 puts it in the species spec | LOG.md line 11, `docs/adr/0006-...md` line 167-168, `docs/specs/SPEC-0011-...md` line 23 |
| F14 | SPEC-0012 already planned **verbatim** SRD text in the `conditions` `description` field, on the grounds that SRD 5.1/5.2 and the OGL allow it with attribution; `ATTRIBUTION.md` already covers `srd-2014` (CC-BY-4.0; OGL 1.0a) and `srd-2024` (CC-BY-4.0), and `LICENSE-OGL.txt` is committed | `docs/specs/SPEC-0012-...md` line 228, `app/reference/ATTRIBUTION.md`, `app/reference/LICENSE-OGL.txt` |
| F15 | No `docs/api/openapi.json` exists yet; a new route would still extend the API surface REQ-0024 freezes | `docs/api/` absent |

## Decision Drivers
Weights: High = 3, Medium = 2, Low = 1. Scores 1 (poor) to 5 (strong). Maximum total 95.

| Dimension | Weight | Why it matters here |
|---|---|---|
| Simplicity / smallest edit (Simp) | High (3) | constraints.md 1 |
| Reversibility (Rev) | High (3) | constraints.md; all options are additive, so this separates code surface |
| Maintainability for one part-time person (Maint) | High (3) | Includes the REQ-0024 MUST that tests run without network or Ollama, and the cost of tuning prompts on an 8B local model |
| Reuse of patterns/dependencies (Reuse) | Medium (2) | F3, F4, F5 already exist |
| Fun / learning (Fun) | Medium (2) | constraints.md 5 |
| Performance / scalability (Perf) | Low (1) | CPU and memory of selection; de-prioritized |
| Security beyond sane defaults (Sec) | Low (1) | Read-only, reviewed SRD text into a local prompt |
| **Grounding quality (Ground)** (added) | Medium (2) | The point of the requirement is "respond based on the appropriate rule". Medium, not High, because the owner explicitly accepts a flagged training-data answer |
| **Play-loop latency (Lat)** (added) | Medium (2) | F10: each extra Ollama call holds the single worker and delays the next player message at the table. Distinct from Perf, which is about scale |

**Gate (REQ-0024 MUSTs):** an option that reads `dnd_data/` or does not answer from the
catalog is disqualified.

## Considered Options
- **A. Deterministic keyword selection in the tool.** Stdlib tokenization of the question,
  name-weighted lexical scoring over the in-memory `rules` entries, a minimum score, a
  character budget, one `generate` call. Training fallback when nothing qualifies.
- **B. LLM-assisted selection.** A's keyword prefilter returns top-N candidates; a first LLM
  call picks the relevant ones (or rewrites the question into rule terms); a second call
  answers.
- **C. LLM picks from the index.** Send all rule names (and ids) to the LLM, parse the chosen
  id, fetch its text, then a second call answers.
- **D. Read `dnd_data/rules.json` at runtime.** Rejected by REQ-0024 and PAT-ARCH-007; scored to
  show why.
- **E. Status quo plus a rules prompt: training data only.** A non-narrator builder and one
  call, no catalog. This is what the owner said is acceptable "at the moment"; scored as the
  simplicity baseline.

Not scored: embeddings / vector search through Ollama. It needs an embedding model pulled
into Ollama, an index built at startup and a new client endpoint, which is a new external
model dependency for 283 entries. Revisit only if A's fallback rate is unacceptable.

## Rubric Scoring
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | Ground (2) | Lat (2) | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| **A Keyword selection** | 4: one pure selection function over at most 283 entries with stdlib `re`, plus a model, a projection and one setting | 5: all new files plus one dict key (F3) and one settings field; delete to revert | 4: deterministic, unit-tested with literal entries and a stubbed `generate`; stopword and threshold tuning is ongoing | 5: `load_entries` (F4), ingest allowlist/projection/budget (F5), `context["reference"]` (F3), `generate` (F1) | 3: small information-retrieval exercise | 5: a scan of about 300 KB in memory per call | 3: SRD text is reviewed at ingest (PAT-ARCH-007) | 3: paraphrased questions ("can they hit me when I run away?" vs "Opportunity Attacks") miss and fall back, but the fallback is flagged in `meta.source` | 5: one Ollama call, same as `/narrate` | **79** |
| B LLM-assisted selection | 2: everything in A plus a second builder and parsing free-text selections from llama3.1:8b, with an invalid-output path | 4: additive, larger surface | 2: two prompts to tune; tests need sequenced stubs; nondeterministic parse failures | 4: same reuse, `generate` twice | 4: prompt chaining is real learning | 4: CPU trivial | 3 | 4: re-ranking drops wrong entries, but recall is still capped by the keyword prefilter | 2: two serialized calls under `_ollama_lock` (F10) double the wait for every queued message | 59 |
| C LLM picks from index | 3: no lexical scoring, but an index prompt, id parsing and validation, and an unknown-id fallback | 4: additive | 2: the index alone is about 6,000-14,000 chars (283 x 20-50 chars, estimate), which is 1.5k-3.5k tokens and at or over the server default context (F9). Fixing that means adding `num_ctx` to the shared client that `/narrate` and chat use | 3: needs a shared-client change REQ-0024 says must not affect `/narrate` | 4 | 3: large prefill on every call | 3 | 3: semantic matching of names, but one id from names only, edition duplicates, and silent truncation risk | 1: two calls, the first with a multi-thousand-token prompt | 55 |
| D Runtime `dnd_data/` read | 4: no ingest step | 4 | 1: `dnd_data/` is gitignored, so a fresh clone has no rules; upstream drift reaches play | 1: breaks PAT-ARCH-006 rule 6 and PAT-ARCH-007 rule 1; `test_t26` guards the app/scripts boundary (F8) | 2 | 3: file read or a home-made cache per call | 2: unreviewed upstream text into prompts | 3 | 5 | 54, **disqualified** (gate) |
| E Training data only | 5: one builder and one tool, no dataset | 5 | 5: nothing to tune but the prompt | 3: ignores the reference pipeline built for this | 2 | 5 | 4: no external text | 1: never grounded; every answer is unchecked | 5 | 76, **disqualified** (gate) |

**Sensitivity:**

| Change | A | B | C | E | Winner among eligible |
|---|---|---|---|---|---|
| Ground raised to High (3) | 82 | 63 | 58 | 77 | A |
| Lat lowered to Low (1) | 74 | 57 | 54 | 71 | A |
| Fun raised to High (3) | 82 | 63 | 59 | 78 | A |
| Ground High, Fun High, Lat Low (most favourable to B) | 80 | 65 | 60 | 73 | A |

E's closeness to A is honest: on pure simplicity, "just answer from training data" is almost as
good. The gap is grounding, which is the reason the requirement exists. E's behaviour survives
inside A as the fallback.

## Decision Outcome
**Chosen: A, deterministic keyword selection** (79, against 59 for B and 55 for C; D and E are
disqualified by the REQ-0024 gate).

A gets most of the grounding for one Ollama call, with no new dependency. The training-data
fallback (which the owner already accepts) covers its weak spot, paraphrased questions, and the
fallback is visible in `meta.source`. B's and C's real advantage, semantic matching, costs a
second serialized call on the shared worker and, for C, a context window this client does not
control.

The decision, at the level an ADR fixes (constants, stopword list and tests belong in the spec):

1. **Tool name `rules`** (`/rules <question>`), module `app/intelligence/tools/rules.py`,
   discovered by the existing path (ADR-0001). It is plain and matches the dataset name, and
   F2 shows no collision. The name is pending human confirmation. Empty or whitespace input
   raises `ToolError` with a usage line.
2. **Dataset `app/reference/rules.json`** (canonical-file tier; not the SQLite fallback).
   - Ingested by `scripts/ingest_open5e.py`: `DOCUMENT_ALLOWLIST["rules"] = [srd-2014,
     srd-2024]`; `CONSUMERS["rules"] = "/rules tool (REQ-0024)"` (PAT-ARCH-007 rule 2: this
     tool is the named consumer).
   - Projection: `id, name, edition, source, publisher, third_party, source_key, description`,
     where `description` is the verbatim upstream `desc`. Nothing else (`index`,
     `initialHeaderLevel`, `ruleset`, `crossreferences` are dropped) unless the spec's
     selection rule demonstrably needs one.
   - F6: `rules` entries need a rules-specific document lookup (string key resolved through
     `_documents.json` for `source`/`publisher`) and read `desc` directly. This is a spec item,
     not a pattern change.
   - Id rule: the existing edition-aware assignment (F5). If two entries in the **same**
     document share a name slug, `_assign_ids` raises "no free id". The spec MUST measure this
     on the snapshot and, if it happens, define a rules-only disambiguation (for example a
     ruleset-prefixed slug) rather than weaken the shared rule.
   - Size: 283 entries; about 300-400 KB after projection and `indent=2` (estimate, the spec
     measures). Well under 2 MB / 2,000.
   - Model `app/reference/rules.py` (`Rule`, `extra="forbid"`, `RULES_PATH`), loaded with
     `load_entries` into `reference["rules"]` in `build_services.py`. Register in
     `OPEN5E_MODELS` in `tests/test_reference_budget.py`.
3. **No read-only route in this requirement.** REQ-0024 freezes the reference routes; the only
   consumer is a backend tool; and PAT-ARCH-007 rule 2's "no consumer, no surface" logic
   applies equally to routes. A full-list `GET /api/v1/reference/rules` would send about
   350 KB of verbatim text to no client. Adding it later is about 10 lines plus a response
   model, with no rework. A clarification of PAT-ARCH-006 rule 5 is flagged below.
4. **Selection (pure function in the tool module, one call site, no shared retrieval module).**
   - Tokenize the question in lowercase with stdlib `re`, drop a small fixed stopword set,
     and apply naive plural folding.
   - Score each entry: a match on a name token outweighs a match in the description (the spec
     fixes the weights). An entry is **relevant** only above a minimum score that requires at
     least one name match, or several distinct description matches.
   - Rank by score. On a tie, prefer `5.5e` (`srd-2024`), which matches ingest `_rank` (F5)
     and REQ-0018's 5.5e-first species picker. When the same rule name is selected in both
     editions, keep only the preferred edition.
   - Pack in rank order, up to a small fixed number of entries (a module constant, suggested
     3). **Never truncate an entry**: truncated rules text can cut off the exception clause
     and mislead. An entry that does not fit is skipped. If the top-ranked relevant entry
     alone exceeds the budget, the result is training mode (REQ-0024 "would exceed the
     budget").
5. **Budget setting: `prompts.rules_budget_chars: int`, default `6000`, `ge=0`.**
   - It counts the excerpt text only, not the fixed instructions or the question.
   - Why 6,000: the average entry is about 1,050 chars (F7), so 6,000 holds one long section or
     3-5 typical entries. That is about 1,500 tokens (about 4 chars per token for English),
     which leaves room in a 4,096-token context for the instructions, the question and a
     several-hundred-token answer.
   - F9 caveat: if the local Ollama still defaults to 2,048 tokens, 6,000 is too large. Use
     about 3,000 there. Raising `num_ctx` in the client is out of scope, because it would
     change `/narrate` and chat.
   - `0` always yields training mode, which is a free off-switch and not a new feature.
6. **Prompt builder `build_rules_prompt(question, excerpts) -> str`** in
   `app/intelligence/prompt_builders.py`.
   - It is pure and takes plain values (each excerpt is `name`, `edition`, `text`; no pydantic
     reference models and no settings object). It returns a single string under PAT-ARCH-003's
     one-shot carve-out (F11).
   - It uses no `NarratorVoiceParams`, no `DM_ROLE_PROMPT` and no voice config. The role is a
     neutral rules referee: answer plainly, cite the rule name, and do not narrate.
   - Order: excerpts first, then the question, then the directives. If Ollama trims over-long
     input from the front, it then loses excerpt text rather than the question or the
     instructions.
   - With an empty excerpt list it produces the training-mode prompt (answer from general
     knowledge of D&D 5e, and say if unsure).
7. **Fallback and `meta`.** `run` returns
   `{"text": ..., "meta": {"tool": "rules", "source": "rules" | "training", "rule_ids": [...]}}`.
   - `rule_ids` holds the catalog `id`s placed in the prompt, in order. It is `[]` in training
     mode. The key is always present, so the shape is uniform.
   - Training mode happens when the catalog key is missing, the catalog is empty, no entry is
     relevant, or the top entry exceeds the budget. A missing `reference`/`rules` key is not an
     error, matching the PAT-ARCH-006 fail-soft rule.
   - In training mode the tool appends a **fixed** sentence to the reply, for example "Not
     checked against the SRD rules text." It is deterministic and testable, instead of trusting
     an 8B model to say it.
8. **Logging:** at most one `get_logger(__name__)` record per call, with `source`, the number of
   entries and the excerpt character count. No question text and no prompt (PAT-CODE-001,
   PAT-ARCH-003 rule 7).
9. **REQ-0018 "short summaries, no verbatim rules text" is scoped to curated or consultant
   datasets that paraphrase commercial or third-party books (species today), not to every
   PAT-ARCH-006 dataset.**
   - Evidence: the sentence's position among species-only clauses (F13), ADR-0006's own reason
     for it, which is paraphrased commercial books (F13), and SPEC-0012's prior plan for
     verbatim SRD `conditions` text on licensing grounds (F14).
   - Effect: `rules.json` MAY carry verbatim SRD 5.1/5.2 text, because both documents license
     reproduction with attribution, which `ATTRIBUTION.md` and `LICENSE-OGL.txt` already
     provide.
   - REQ-0018 is **not edited**. The scoping is flagged for the human below.
   - The REQ-0018 rule that the app must not read `docs/from_consultant/` is untouched. This
     tool reads only `app/reference/rules.json` through the catalog.
10. **Unchanged:** `narrate.py`, `roll.py`, the REQ-0022 `/attack` work, `OllamaClient`, the
    worker, the existing routes and schemas, and `ToolService`.

**What was traded away:**
- Semantic matching of paraphrased questions (B, C, embeddings). Those questions get a flagged
  training-data answer instead.
- Rules outside the open5e `rules` endpoint, such as conditions, spells and monsters. They are
  not in this catalog and fall back to training. Widening needs a new requirement.
- Entry truncation as a way to fit long sections. Long sections fall back instead.

## Consequences
- Positive:
  - One LLM call, deterministic and offline. Tests run with literal `Rule` entries and a
    stubbed `generate`.
  - Reuses the whole PAT-ARCH-006/-007 pipeline unchanged; the only new runtime knob is one
    settings field.
  - The `meta.source` / `rule_ids` convention lets the frontend (later) show grounded vs unchecked
    answers and lets the developer measure the fallback rate from stored messages.
- Negative:
  - Lexical recall is limited. Stopword and threshold tuning is ongoing hobby maintenance.
  - Both SRD editions coexist. A 5.5e-first tie-break can surface 2024 text to a table playing
    2014 rules (see open questions). The edition label is in the prompt.
  - About 0.4 MB more resident memory and about 350 KB more committed JSON.
- Follow-up work and accepted risks:
  - The spec measures the projected size, any same-document id collisions, and the
    longest-entry distribution (how many entries alone exceed 6,000 chars). It also defines the
    stopword list, the weights, the threshold and the max-entry constant, and gives a
    fallback-rate smoke list of about 10 typical table questions.
  - The spec adds `rules_budget_chars` to `settings.json` so the knob is visible.
  - F9 risk: confirm the local Ollama default context before trusting the 6,000 default.

**Revisit triggers. Reopen if:**
- the training fallback rate on real table questions is high enough to annoy the DM. Consider B
  or embeddings then, and accept the extra call;
- a second grounded tool (spells, monsters, conditions) appears. Extract the selection function
  into a shared module then (two call sites, constraints.md 2);
- the client gains `num_ctx` control for another reason. Revisit the budget default then.

## Pattern Impact
- **Uses** PAT-ARCH-003 (one-shot pure builder), PAT-ARCH-004 (tool contract, dispatch,
  meta), PAT-ARCH-006 (catalog, fail-soft, tools read memory), PAT-ARCH-007 (consumer-gated
  ingest, allowlist, projection, budget) and PAT-CODE-001. None is modified.
- **Creates PAT-ARCH-009** (`proposed`): "Reference-grounded LLM tools: deterministic
  in-memory selection, bounded excerpt budget, flagged training fallback". It records the
  `meta.source` / `rule_ids` convention and the never-truncate / fall-back rule for the next
  grounded tool. It has one call site, so it shares no code yet.
- **Clarifications to PAT-ARCH-006 (accepted), flagged for human sign-off and NOT applied:**
  1. Rule 5 ("Serve read-only"). Add: "A dataset gets a GET route when a frontend or API
     consumer needs one. A dataset consumed only by backend tools MAY have no route (same
     consumer gate as PAT-ARCH-007 rule 2)."
  2. Rule 3 (normalize at ingest). Add a content rule: "Entries derived from paraphrased
     commercial or third-party sources (consultant deliveries) MUST be short summaries with no
     verbatim rules text (REQ-0018). Entries from openly licensed documents on the
     PAT-ARCH-007 allowlist (SRD 5.1, SRD 5.2) MAY carry verbatim text, provided
     `ATTRIBUTION.md` (and `LICENSE-OGL.txt` where required) covers the document."
- **Requirement scoping flagged, NOT applied:** a note on REQ-0018 in `docs/requirements/LOG.md`
  that its "short summaries" sentence is species/consultant-scoped (decision 9). REQ-0018 is
  not edited by this ADR.
