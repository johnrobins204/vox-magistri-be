# Pattern Repository

A discoverable, versioned library of architecture/spec/code patterns that every
workflow stage (senior-architect, spec-writer, developer) MUST consult before
producing new design or code for this project.

## Categories
- `architecture/` — system/design patterns (e.g. service-locator DI, settings
  namespace convention).
- `spec/` — conventions for writing specs and work packages.
- `code/` — reusable code-level patterns, snippets, or conventions.

## Status lifecycle
- `proposed` — any agent MAY author a new pattern at this status without waiting
  for human approval.
- `accepted` — confirmed by the human. Mutating or deprecating an existing
  `accepted` pattern MUST go through the senior-architect agent, which MUST flag
  the change for explicit human sign-off before the status changes.
- `deprecated` — superseded; file is kept for history and linked via
  `supersedes` / `superseded_by` frontmatter.

## How to consult (required before any design/spec/code work)
1. Read [INDEX.md](./INDEX.md) for the full table of patterns by id/category/status.
2. If a relevant entry exists, open its file and apply it, or explicitly justify
   why it doesn't fit before proposing a new one.
3. If none exists, author a new pattern file from [TEMPLATE.md](./TEMPLATE.md) and
   add a row to `INDEX.md` with `status: proposed`.
