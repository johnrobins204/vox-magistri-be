---
id: PAT-ARCH-010
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# Non-destructive message corrections: `canon` column, in-place revisions, canon-only history

## Problem
The operator needs to fix or retcon what the narrator said (REQ-0027) without losing the
original text, and every place that feeds conversation history to a model must agree on
which messages count.

## Context
Applies to any write that changes a stored message after creation (edit, regenerate,
retcon) and to every reader that turns messages into model input or world facts (the chat
builder today, world extraction later). Decided in
[ADR-0011](../../adr/0011-message-corrections-canon-edit-regenerate.md). Builds on
PAT-ARCH-001 (shared helper, worker writes replies), PAT-ARCH-003 (pure builders) and
PAT-ARCH-008 (the `canon` column is ladder step v4).

## Solution
1. **Canon is a column.** `messages.canon` (nullable, default 1; NULL counts as canon) is
   exposed as `canon: bool` on every message dict and on `MessageResp`. Clients cannot set
   it through create payloads.
2. **Nothing is deleted.** Changing `content` appends `{content, replaced_at, reason}` to
   `meta.revisions` in the same transaction; `revisions[0]` is the original. `revisions`
   is a reserved meta key. Retcon sets `canon` false and leaves the row.
3. **One store write method** updates `content` and/or `canon`; edit, canon toggle and the
   worker's regenerate all use it.
4. **One reply per user message.** Regenerate re-enqueues the user message; the worker
   revises its existing reply in place. No second status vocabulary and no extra reply rows.
5. **Every history consumer filters on `canon`** in addition to its own status/role rules.

## Consequences
- The frontend shows edited state from `meta.revisions` and retcon state from `canon`.
- A failed regenerate leaves the user message in `error`, dropping that turn from history
  until the operator retries.
- Revision history is not queryable by SQL; it is display-only.

## Examples
None yet. Planned for REQ-0027: `app/services/repos.py` (v4 step, write method),
`app/services/messages.py`, `app/intelligence/prompt_builders.build_chat_messages`,
`app/services/inference_service._append_reply`.
