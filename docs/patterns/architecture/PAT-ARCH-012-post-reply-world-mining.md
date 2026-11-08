---
id: PAT-ARCH-012
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# Post-reply world mining: fail-soft worker step after the reply is visible; proposals are pending entity rows

## Problem
World memory needs facts pulled out of narrator replies (REQ-0028 deterministic now,
REQ-0030 small-model later) without delaying or failing the reply and without pushing
unreviewed facts into prompts.

## Context
Applies to any processing of a finished assistant reply that writes world state. Does not
apply to prompt building (PAT-ARCH-003) or slash tools (PAT-ARCH-004). Decided in
[ADR-0013](../../adr/0013-world-mention-detection-approval-queue.md).

## Solution
1. **Placement.** A direct method call on the worker thread after the user message is set
   `completed` (the reply is visible) and after `job.completed` is logged. No hook registry
   or extra thread until a second step needs one.
2. **Fail-soft.** The step has its own `try/except`, logs a warning and never changes any
   message status.
3. **What is mined.** Chat replies and `/narrate` replies only (`meta.tool` absent or
   `narrate`; other tools' output is never mined), and only when the reply is canon
   (PAT-ARCH-010 rule 5).
4. **Pure detection.** Matching and proposal logic lives in
   `app/intelligence/world_mentions.py`: stdlib only, no store, HTTP or model client; the
   worker does all I/O. (Enforced in `tests/test_patterns.py`.)
5. **Proposals are rows.** New candidates are `world_entities` rows with `status=pending`,
   campaign-wide scope, and provenance in the `evidence` JSON column (`detector`,
   `session_id`, `source_message_id`, `snippet`, `first_seen_at`, `message_ids`). A name
   matching any existing row of any status is never re-proposed; rejected rows are the
   memory. Only `canon` is injected.
6. **Switch and logs.** A `world.*` settings switch turns the step off; logs carry counts and
   duration only.

## Consequences
- Each step adds its runtime to the start of the next queued job (milliseconds for regex; a
  model-based step must measure and justify its cost under the shared `_ollama_lock`).
- Edits made through the corrections API are not re-mined; regenerate is.

## Examples
None yet. Planned for REQ-0028: `app/intelligence/world_mentions.py`,
`app/services/inference_service._detect_mentions`, ladder v5 in `app/services/repos.py`.
