---
id: PAT-ARCH-011
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# Structured reference lookup tools: deterministic name match and deterministic render, no LLM on a hit

## Problem
Some slash tools look up one named reference entry and show its structured data, such as a
weapon for `/attack` or a monster stat block for `/monster`. If an LLM restates the entry, it
can change numbers that the DM reads out at the table, and it holds the shared Ollama lock for
a long generation. If each tool invents its own name matching, the same query behaves
differently from tool to tool.

## Context
Applies to PAT-ARCH-004 tools that read one PAT-ARCH-006 catalog entry by name. Decided in
[ADR-0012](../../adr/0012-monster-stat-block-tool.md).

It does not apply to questions answered from reference text. Those use PAT-ARCH-009's keyword
selector and excerpt budget.

## Solution
1. **Read the in-memory catalog only.** Use `context["reference"]["<dataset>"]`. Never read
   files, `dnd_data/` or the upstream source (PAT-ARCH-009 rule 1).
2. **Match names deterministically.**
   - Casefold and collapse non-word characters.
   - Try an exact name match first, then a substring match.
   - If several distinct names match, raise a `ToolError` that lists up to 5 of them.
   - If the same name exists in both editions, prefer 5.5e, unless the user adds an optional
     edition token.
3. **Render with code on a hit.** A pure function turns the entry into reply text. It is
   unit-tested against an exact string and never truncates the entry. No LLM call is made.
4. **Handle a miss explicitly.** Each tool picks one of these and documents it:
   - a `ToolError` (as `/attack` does);
   - or, for a near-typo, a `ToolError` with stdlib `difflib` suggestions, and otherwise one
     PAT-ARCH-009 training-mode call (rules 4-7: pure builder with no voice, fixed
     disclaimer, `meta.source = "training"`, empty ids list).
5. **Set `meta`.** On a hit it carries the matched entry id(s). Logs carry counts only, never
   the query.
6. **Share code at the third caller.** Two tools that differ on what a miss does do not justify
   a shared helper (constraints.md 2).

## Consequences
- Lookups are instant, faithful and offline-testable with literal entries.
- Formatting is hand-written per dataset.
- Name-only matching misses aliases, which are not in the open5e data.

## Examples
- `/attack`: `_norm` and `_lookup` in `app/intelligence/tools/attack.py` (lines 130-152). A miss
  is a `ToolError`.
- `/monster` (planned, ADR-0012): `app/intelligence/tools/monster.py`. A near-typo gives a
  `ToolError`. A true miss gives one flagged training call.
