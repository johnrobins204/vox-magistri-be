---
id: ADR-0000
status: proposed
date: YYYY-MM-DD
requirement: REQ-NNNN
supersedes: null
superseded_by: null
---

# <Decision Title>

## Context
Why the requirement forces a decision, in a few lines. Link the requirement
(`docs/requirements/LOG.md`, do not copy it) and applicable pattern ids. Keep the
whole ADR under 10,000 bytes (`tests/test_patterns.py` enforces this for new ADRs):
tables over prose, no quoted source code.

## Decision Drivers
List the rubric dimensions in play (start from `docs/constraints.md`, add any
requirement-specific dimensions with a stated weight and justification).

| Dimension | Weight | Why it matters here |
|---|---|---|

## Considered Options
1. <Option A>
2. <Option B>
3. <Option C — may be "do nothing" / status quo>

## Rubric Scoring
| Option | Dimension 1 | Dimension 2 | ... | Weighted Total |
|---|---|---|---|---|

Each cell MUST carry a one-line justification grounded in real facts about this
codebase (file references, measured constraints) — not unsupported preference.

## Decision Outcome
Chosen option and why it won on the weighted rubric (a short paragraph). State
explicitly what was traded away.

## Consequences
- Positive:
- Negative:
- Follow-up work or risks accepted:

## Pattern Impact
Does this decision create, use, or supersede an entry in `docs/patterns/`? List
the pattern id(s) and the status change requested (if any requires human
sign-off per `docs/patterns/README.md`).
