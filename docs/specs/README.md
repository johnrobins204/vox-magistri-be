# Spec Lifecycle & Traceability

Specs are produced by the spec-writer agent after a requirement has been
restated (`docs/requirements/LOG.md`) and, if the senior-architect agent
determined one was required, an ADR exists (`docs/adr/`).

Traceability chain: `REQ-ID` → `ADR-ID` (optional) → `SPEC-ID` → Work Packages → Tests.

File naming: `docs/specs/<SPEC-ID>-<slug>.md`, e.g.
`docs/specs/SPEC-0001-dice-roll-parser.md`.

## Required section order
Per [TEMPLATE.md](./TEMPLATE.md), in this order:
1. **Requirement** — verbatim RFC 2119 restatement, `REQ-ID`, linked ADR if any.
2. **Test Spec** — written first; defines pass/fail before any work package.
3. **Work Packages** — sized for isolated execution by smaller models (see
   sizing rules below).
4. **Other Details** — risks, rollback plan, patterns applied/created, non-goals.

## Work package sizing rules
Each work package MUST be self-contained:
- explicit file list (no "see above"),
- stated inputs/outputs,
- acceptance criteria restated in full, not referenced,
- no hidden dependency on conversational context from other packages.
