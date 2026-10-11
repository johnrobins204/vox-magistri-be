---
id: SPEC-0000
requirement: REQ-NNNN
adr: null
status: draft
date: YYYY-MM-DD
---

# <Spec Title>

## 1. Requirement
Verbatim RFC 2119 restatement from `docs/requirements/LOG.md` (REQ-NNNN).

## 2. Test Spec
Write this section first, before any implementation work package. List the
concrete tests (unit/integration) that define "done." Each test MUST state:
- what it exercises,
- the expected observable outcome,
- the file it will live in (e.g. `tests/test_<thing>.py`).

## 3. Work Packages
Numbered, self-contained units sized for execution by a smaller/"mini" model.
Each package MUST restate its own acceptance criteria in full.

### WP-1: <title>
- **Files:** explicit list
- **Inputs:** what this package can assume exists
- **Outputs:** what this package must produce
- **Acceptance criteria:** restated in full, not "see Test Spec"
- **Patterns used/created:** pattern id(s) from `docs/patterns/`, or "none"

### WP-2: <title>
(same structure)

## 4. Other Details
- **Risks:**
- **Rollback plan:**
- **Patterns applied/created:** list with ids and status
- **Non-goals:** explicitly out of scope for this spec
