# Architecture Decision Records (MADR)

ADRs are produced by the senior-architect agent when a requirement meets one of
the triggers below. Format: MADR-style (Decision Drivers / Considered Options /
Rubric / Decision Outcome). Files are numbered sequentially:
`docs/adr/0001-slug.md`.

## When an ADR is required
An ADR MUST be written when a requirement:
- is costly or hard to reverse,
- introduces a new dependency or external service,
- changes a cross-cutting convention (e.g. the DI pattern, settings schema, error
  handling convention),
- deviates from or supersedes an `accepted` entry in `docs/patterns/`,
- has two or more genuinely viable implementation approaches.

An ADR is NOT required for a small, easily-reversible, single-module change with
one obvious approach.

## Rubric
Every ADR MUST score its considered options against the rubric dimensions in
[docs/constraints.md](../constraints.md) (plus any requirement-specific
dimensions the architect adds), with a weighted total — not prose preference
alone.

## Status lifecycle
`proposed` (agent-authored) → `accepted` (human sign-off) → `superseded` (linked
to the ADR that replaces it).
