---
id: PAT-ARCH-009
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# Reference-grounded LLM tools: deterministic in-memory selection, bounded excerpt budget, flagged training fallback

## Problem
A tool that answers from reference text, such as rules today and spells or monsters later,
cannot put the whole catalog into a local Ollama prompt. The client sends no `num_ctx`, so the
server default context applies. If selection is ad hoc, grounding quality, prompt size and
honesty about ungrounded answers drift from tool to tool. If an excerpt is silently truncated
or the model silently falls back to its training data, the DM sees a rules-sounding answer
that was never checked.

## Context
Applies to slash tools (PAT-ARCH-004) that place PAT-ARCH-006 catalog text into a one-shot
prompt (the PAT-ARCH-003 carve-out). Decided in
[ADR-0009](../../adr/0009-rules-consult-tool.md) for `/rules` (REQ-0024).

It does not apply to:
- the chat pipeline (PAT-ARCH-003 rules 1-5);
- structured lookups that need no LLM, such as `/attack` reading weapon stats (REQ-0022).

There is one call site so far. Do not extract shared code until a second grounded tool exists
(constraints.md 2).

## Solution
1. **Read the in-memory catalog only.** Use `context.get("reference", {}).get("<dataset>")`.
   Never open files, never read `dnd_data/`, never call the upstream source. A missing or
   empty catalog means training mode, not an error.
2. **Select deterministically.** Use a pure, stdlib function over the catalog entries:
   tokenize, score with name matches weighted above body matches, apply a minimum relevance
   threshold, use a fixed edition tie-break, and remove duplicates of the same rule across
   editions. The function is unit-tested with literal entries. Do not use an LLM call to select
   unless an ADR accepts the extra worker time.
3. **Bound the excerpt.** One `int` setting holds the budget in characters of excerpt text.
   Pack entries in rank order up to a small constant count. **Never truncate an entry**: skip
   an entry that does not fit. If the top-ranked entry alone does not fit, use training mode.
4. **Pure builder.** `build_<x>_prompt(question, excerpts) -> str` in
   `app/intelligence/prompt_builders.py` takes plain values (name, edition, text). It uses no
   narrator voice. It orders the prompt as excerpts, then the question, then the directives.
   With no excerpts it builds the training-mode prompt.
5. **Flag the grounding in `meta`.** The tool returns
   `{"tool": NAME, "source": "<dataset>" | "training", "<entity>_ids": [...]}`. The ids list is
   always present and is empty in training mode.
6. **Disclaim deterministically.** In training mode the tool appends a fixed "not checked
   against the rules text" sentence to the reply. It does not rely on the model to say it.
7. **Log counts only:** the source, the number of entries and the excerpt character count.
   Never log the question or the prompt (PAT-CODE-001).

## Consequences
- One Ollama call per question, so the play-loop latency matches `/narrate`. Tests need no
  network or Ollama.
- Lexical selection misses paraphrased questions. The flagged fallback makes those misses
  visible rather than hidden.
- The budget depends on the Ollama server's default context until the client controls
  `num_ctx`.

## Examples
`/rules` (REQ-0024, ADR-0009) is the first and only call site:
- Tool: `app/intelligence/tools/rules.py` (selection, budget, `meta.source`, disclaimer).
- Builder: `build_rules_prompt` in `app/intelligence/prompt_builders.py`.
- Setting: `prompts.rules_budget_chars` in `app/config.py` and `settings.json`.
- Catalog: `app/reference/rules.py` (model) and `app/reference/rules.json` (dataset, loaded
  once at startup into `context["reference"]["rules"]`).
- Tests: `tests/test_rules_selection.py`, `tests/test_rules_prompt.py`,
  `tests/test_rules_tool.py`, `tests/test_rules_wiring.py`, plus the discovery and slash
  dispatch cases in `tests/test_tool_calling.py` and `tests/test_slash_dispatch.py`.
