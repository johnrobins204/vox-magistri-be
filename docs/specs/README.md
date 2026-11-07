# Spec Lifecycle & Traceability

Specs are produced by the spec-writer agent after a requirement has been
restated (`docs/requirements/LOG.md`) and, if the senior-architect agent
determined one was required, an ADR exists (`docs/adr/`).

Traceability chain: `REQ-ID` → `ADR-ID` (optional) → `SPEC-ID` → Work Packages → Tests.

File naming: `docs/specs/<SPEC-ID>-<slug>.md`, e.g.
`docs/specs/SPEC-0001-dice-roll-parser.md`.

## Required section order
Per [TEMPLATE.md](./TEMPLATE.md), in this order:
1. **Requirement** — `REQ-ID`, link to its row in `docs/requirements/LOG.md`
   (do not copy the restatement), linked ADR if any, and at most five bullets of
   decisions the work packages depend on.
2. **Test Spec** — written first; defines pass/fail before any work package. One
   `### WP-n` subsection per package so it can be sliced.
3. **Work Packages** — sized for isolated execution by smaller models (see
   sizing rules below). Headings are `### WP-n: title`.
4. **Other Details** — risks, rollback plan, patterns applied/created, non-goals
   (at most ten lines).

## Size budget and slicing
New specs (SPEC-0015 onwards) MUST stay under 20,000 bytes; split the requirement
rather than growing the spec (`tests/test_patterns.py` enforces it). The Implementer
never reads the whole spec: `python scripts/spec_slice.py SPEC-NNNN WP-n` prints the
front matter, the Test Spec intro, that package's Test Spec subsection and the
package itself. `--list` shows the package titles.

## Work package sizing rules
Each work package MUST be self-contained within its slice:
- explicit file list (no "see above"),
- stated inputs/outputs,
- acceptance criteria that state the behaviour in full; they MAY point at the
  package's own Test Spec subsection (it is in the slice) instead of repeating
  its test table, but MUST NOT point at another package or the Requirement,
- no hidden dependency on conversational context from other packages.
