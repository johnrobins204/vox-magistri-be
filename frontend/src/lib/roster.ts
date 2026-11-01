import {
  PLACEHOLDER_CHARACTER,
  normalizeCharacter,
  type Character,
} from './character'

// Roster persistence: all of the player's characters plus a pointer to the one
// currently at the table. Legacy single-character saves (vox.character) are
// migrated on first load.

const ROSTER_KEY = 'vox.characters'
const ACTIVE_KEY = 'vox.active_character'
const LEGACY_KEY = 'vox.character'

function isValidCharacter(value: unknown): value is Character {
  const c = value as Character
  return !!c && typeof c.id === 'string' && typeof c.name === 'string' && !!c.abilities
}

export function loadRoster(): Character[] {
  try {
    const raw = localStorage.getItem(ROSTER_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Character[]
      if (Array.isArray(parsed)) {
        return parsed.filter(isValidCharacter)
      }
    }
    // Legacy migration: a single character saved by the first builder version.
    const legacy = localStorage.getItem(LEGACY_KEY)
    if (legacy) {
      const parsed = JSON.parse(legacy) as Partial<Character>
      if (parsed && typeof parsed.name === 'string' && parsed.abilities) {
        const migrated = { ...parsed, id: crypto.randomUUID() } as Character
        localStorage.setItem(ROSTER_KEY, JSON.stringify([migrated]))
        localStorage.setItem(ACTIVE_KEY, migrated.id)
        localStorage.removeItem(LEGACY_KEY)
        return [migrated]
      }
      localStorage.removeItem(LEGACY_KEY)
    }
    return []
  } catch {
    return []
  }
}

export function saveRoster(roster: Character[]): void {
  localStorage.setItem(ROSTER_KEY, JSON.stringify(roster))
}

export function loadActiveId(): string | null {
  return localStorage.getItem(ACTIVE_KEY)
}

export function saveActiveId(id: string | null): void {
  if (id) {
    localStorage.setItem(ACTIVE_KEY, id)
  } else {
    localStorage.removeItem(ACTIVE_KEY)
  }
}

/** The hero shown on the rail: the active pick, else the first roster entry, else the placeholder. */
export function resolveActive(roster: Character[], activeId: string | null): Character {
  const found = roster.find((c) => c.id === activeId)
  return found ?? roster[0] ?? PLACEHOLDER_CHARACTER
}

/** The hero to send on session create, or null for the placeholder (never sent). */
export function sendableHero(roster: Character[], activeId: string | null): Character | null {
  const hero = resolveActive(roster, activeId)
  return hero.id === PLACEHOLDER_CHARACTER.id ? null : hero
}

export function upsertCharacter(roster: Character[], character: Character): Character[] {
  const normalized = normalizeCharacter(character)
  const index = roster.findIndex((c) => c.id === normalized.id)
  if (index === -1) {
    return [...roster, normalized]
  }
  const clone = [...roster]
  clone[index] = normalized
  return clone
}

export function removeCharacter(roster: Character[], id: string): Character[] {
  return roster.filter((c) => c.id !== id)
}
