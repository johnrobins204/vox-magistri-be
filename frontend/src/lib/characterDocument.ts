import type { AbilityKey } from './character'

export interface CharacterData {
  id: string
  name: string
  lineage: string
  speciesId?: string | null
  charClass: string
  level: number
  hpCurrent: number
  hpMax: number
  ac: number
  abilities: Record<AbilityKey, number>
  conditions: string[]
  notes?: string
}

export interface CharacterRevision {
  revision: number
  createdAt: string
  modifiedAt: string
}

export interface CharacterDocumentV1 {
  format: 'vox-character'
  formatVersion: 1

  characterId: string

  revision: CharacterRevision

  character: CharacterData

  extensions?: Record<string, unknown>
}

export interface CharacterLibraryEntry {
  characterId: string
  name: string
  lineage: string
  level: number
  charClass: string
  modifiedAt: string
  storageRef: string
}

export interface ParseResult {
  document: CharacterDocumentV1
}

export class CharacterDocumentError extends Error {}

export class UnsupportedVersionError extends CharacterDocumentError {}

export class InvalidDocumentError extends CharacterDocumentError {}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function validateAbilities(
  abilities: unknown,
): abilities is Record<AbilityKey, number> {
  if (!isObject(abilities)) return false

  const keys = ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA']

  return keys.every(
    (key) => typeof (abilities as Record<string, unknown>)[key] === 'number',
  )
}

export function isCharacterDocumentV1(
  value: unknown,
): value is CharacterDocumentV1 {
  if (!isObject(value)) return false

  if (value.format !== 'vox-character') return false
  if (value.formatVersion !== 1) return false

  const character = value.character

  if (!isObject(character)) return false

  if (typeof value.characterId !== 'string') return false

  if (!validateAbilities(character.abilities)) return false

  return true
}

export function createCharacterDocument(
  character: CharacterData,
): CharacterDocumentV1 {
  const now = new Date().toISOString()

  return {
    format: 'vox-character',
    formatVersion: 1,
    characterId: character.id,
    revision: {
      revision: 1,
      createdAt: now,
      modifiedAt: now,
    },
    character,
  }
}

export function reviseCharacterDocument(
  existing: CharacterDocumentV1,
  nextCharacter: CharacterData,
): CharacterDocumentV1 {
  return {
    ...existing,
    character: nextCharacter,
    revision: {
      ...existing.revision,
      revision: existing.revision.revision + 1,
      modifiedAt: new Date().toISOString(),
    },
  }
}

export function serializeCharacterDocument(
  document: CharacterDocumentV1,
): string {
  return JSON.stringify(document, null, 2)
}

export function parseCharacterDocumentJson(
  text: string,
): CharacterDocumentV1 {
  let raw: unknown

  try {
    raw = JSON.parse(text)
  } catch {
    throw new InvalidDocumentError('Invalid JSON')
  }

  if (!isObject(raw)) {
    throw new InvalidDocumentError('Document must be an object')
  }

  if (raw.format !== 'vox-character') {
    throw new InvalidDocumentError('Unknown format')
  }

  if (raw.formatVersion !== 1) {
    throw new UnsupportedVersionError(
      `Unsupported format version: ${String(raw.formatVersion)}`,
    )
  }

  if (!isCharacterDocumentV1(raw)) {
    throw new InvalidDocumentError('Document validation failed')
  }

  return raw
}

export function toLibraryEntry(
  document: CharacterDocumentV1,
  storageRef: string,
): CharacterLibraryEntry {
  return {
    characterId: document.characterId,
    name: document.character.name,
    lineage: document.character.lineage,
    level: document.character.level,
    charClass: document.character.charClass,
    modifiedAt: document.revision.modifiedAt,
    storageRef,
  }
}