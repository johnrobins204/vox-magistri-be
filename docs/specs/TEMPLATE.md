---
id: SPEC-0000
requirement: REQ-NNNN
adr: null
status: draft
date: YYYY-MM-DD
---

# <Spec Title>

## 1. Requirement
REQ-NNNN; restatement in `docs/requirements/LOG.md` (link, do not copy). ADR: none or
ADR-NNNN. At most five bullets of decisions the work packages depend on.

## 2. Test Spec
Write this section first, before any implementation work package. Give a short
intro (shared conventions, how tests run), then one `### WP-n` subsection per work
package listing the concrete tests (unit/integration) that define "done." Each
test MUST state:
- what it exercises,
- the expected observable outcome,
- the file it will live in (e.g. `tests/test_<thing>.py`).

## 3. Work Packages
Numbered, self-contained units sized for execution by a smaller/"mini" model.
Each package states its behavioural acceptance criteria in full and may point at its
own Test Spec subsection. Keep the whole spec under 20,000 bytes.

### WP-1: <title>
- **Files:** explicit list
- **Inputs:** what this package can assume exists
- **Outputs:** what this package must produce
- **Acceptance criteria:** behaviour in full; may cite this package's own Test Spec subsection
- **Patterns used/created:** pattern id(s) from `docs/patterns/`, or "none"

### WP-2: <title>
(same structure)

## 4. Other Details (at most ten lines)
- **Risks:**
- **Rollback plan:**
- **Patterns applied/created:** list with ids and status
- **Non-goals:** explicitly out of scope for this spec
