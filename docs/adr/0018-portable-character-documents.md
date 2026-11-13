---
id: ADR-0018
status: proposed
date: 2026-11-13
requirement: REQ-TBD
supersedes: null
superseded_by: null
---

# Characters are portable documents; rosters and sessions are separate concerns

## Context

The current implementation treats a character primarily as browser-managed state. The
frontend character model is persisted in local storage through roster utilities and an
active-character pointer. A session may be created with a character payload, and that
payload becomes session context used by prompt construction. Existing functionality works,
but several architectural concerns are currently coupled:

- Character creation ("forge").
- Character library management ("roster").
- Browser persistence.
- Active-character selection.
- Session attachment.
- Future character sharing between player instances.

Verified facts:

- Characters are currently persisted through local browser storage using
  `vox.characters`, `vox.active_character`, and legacy migration support from
  `vox.character` (`frontend/src/lib/roster.ts`).
- The canonical frontend character shape is defined in
  `frontend/src/lib/character.ts`.
- The roster stores complete character records rather than references.
- Session creation supports sending character data which is then stored with the
  session (`app/api/v1/session.py`, ADR-0008).
- The current UX combines roster management and character editing in the same
  workflow (`frontend/src/components/CharacterCreator.tsx`).

The project vision includes player-owned characters that can move between machines,
player instances, campaigns, and future deployment models. Treating characters as local
UI state makes portability, migration, sharing, backup, import/export, and future cloud
storage more difficult than necessary.

## Decision

Characters SHALL become versioned portable documents.

A character document becomes the canonical representation of a player character. The
roster, active-character selection, and session attachment mechanisms become separate
layers built on top of that document.

The system SHALL distinguish three separate concepts:

1. Character Document
2. Character Library
3. Session Character Snapshot

### Character Document

A character document is the authoritative player-owned record.

Properties:

- Versioned.
- Self-contained.
- Portable.
- Validated through a schema.
- Stored and exchanged as JSON.
- Independent of any specific browser session.

The document SHALL contain gameplay identity and statistics such as:

- Character identity.
- Species.
- Lineage.
- Classes and levels.
- Ability scores.
- HP and AC.
- Conditions.
- Notes.
- Future extensible gameplay data.

The document SHALL include:

- A format identifier.
- A format version.
- Stable character identifier.
- Revision metadata.

The recommended exchange format is:

`*.voxcharacter.json`

The file extension is a user-facing convention only. Runtime processing SHALL validate
file contents rather than relying on extension names.

### Character Library

A player's roster SHALL become a character library.

The library is not the source of truth. It is an index of character documents available
to the user on a given device or deployment.

Library entries SHOULD contain lightweight metadata only:

- Character identifier.
- Name.
- Summary information.
- Last modified timestamp.
- Storage reference.

The library SHALL manage:

- Import.
- Export.
- Deletion from the local library.
- Selection of an active character.
- Local browsing and filtering.

The library SHALL NOT redefine the character schema.

### Session Character Snapshot

When a player joins a game, the selected character SHALL be converted into a normalized
session snapshot.

The session snapshot becomes part of the session state.

The snapshot SHALL:

- Preserve session reproducibility.
- Survive later edits to the source character.
- Be suitable for prompt construction.
- Remain compatible with ADR-0008's existing character-aware session model.

Sessions SHALL NOT depend on continued access to the original character document.

## Consequences

### Positive

- Characters become portable across installations.
- Import/export becomes a first-class capability.
- Backups become straightforward.
- Future cloud synchronization becomes easier.
- Schema migrations become explicit and versioned.
- Session integrity improves because sessions depend on snapshots rather than mutable
  references.
- The forge can evolve independently of library management.
- Multiple storage implementations become possible without changing the document model.

### Negative

- Additional migration work is required.
- Validation and format-version handling must be implemented.
- Existing local-storage data requires migration.
- Character editing and session synchronization rules must be defined explicitly.

### Neutral

- Local storage may remain the initial repository implementation.
- IndexedDB may later replace local storage without affecting document format.
- Future cloud storage becomes an implementation detail rather than an architectural
  concern.

## Implementation Guidance

The migration SHOULD proceed incrementally:

1. Define CharacterDocumentV1.
2. Introduce validation and normalization helpers.
3. Add import/export support.
4. Migrate existing roster data into character documents.
5. Introduce a repository abstraction.
6. Separate Character Library from Character Forge UI.
7. Attach normalized snapshots during session creation.
8. Remove direct dependencies on legacy local-storage structures.

Repository abstractions SHOULD support:

- list()
- get(id)
- save(character)
- remove(id)
- importFile(file)
- exportFile(id)

## Decision Rule

The architectural source of truth SHALL be the character document.

Roster state represents a library of character documents.

Session state represents a snapshot of a character document.

No component may treat browser-specific storage structures as the canonical character
model.
