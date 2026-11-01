import type { CharacterIn } from '../types'

export const ABILITY_KEYS = ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'] as const
export type AbilityKey = (typeof ABILITY_KEYS)[number]

export interface Character {
  id: string
  name: string
  lineage: string
  charClass: string
  level: number
  hpCurrent: number
  hpMax: number
  ac: number
  abilities: Record<AbilityKey, number>
  conditions: string[]
  /** Catalog species id (e.g. "elf"). Absent on legacy heroes; lineage stays free text. */
  speciesId?: string | null
}

export const PLACEHOLDER_CHARACTER: Character = {
  id: 'placeholder-hero',
  name: 'Kaelen',
  lineage: 'Wood Elf',
  charClass: 'Ranger',
  level: 3,
  hpCurrent: 24,
  hpMax: 28,
  ac: 14,
  abilities: { STR: 12, DEX: 16, CON: 13, INT: 11, WIS: 15, CHA: 10 },
  conditions: ['Blessed'],
}

export function newCharacter(): Character {
  return {
    id: crypto.randomUUID(),
    name: '',
    lineage: '',
    charClass: '',
    level: 1,
    hpCurrent: 10,
    hpMax: 10,
    ac: 10,
    abilities: { STR: 10, DEX: 10, CON: 10, INT: 10, WIS: 10, CHA: 10 },
    conditions: [],
  }
}

export function modifier(score: number): string {
  const mod = Math.floor((score - 10) / 2)
  return mod >= 0 ? `+${mod}` : `${mod}`
}

/** Classic 4d6 drop-the-lowest. */
export function rollAbilityScore(): number {
  const rolls = Array.from({ length: 4 }, () => 1 + Math.floor(Math.random() * 6))
  rolls.sort((a, b) => b - a)
  return rolls[0] + rolls[1] + rolls[2]
}

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

// Trim, then cap, then trim again so a cut never leaves trailing spaces.
const cap = (value: string, max: number) => value.trim().slice(0, max).trim()

const SPECIES_ID_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/

// Limits mirror the backend CharacterIn caps (ADR-0008 D4) so a save never 422s.
export function normalizeCharacter(c: Character): Character {
  const abilities = { ...c.abilities }
  for (const key of ABILITY_KEYS) {
    abilities[key] = clamp(Math.round(abilities[key] || 10), 3, 20)
  }
  const hpMax = clamp(Math.round(c.hpMax || 1), 1, 999)
  return {
    ...c,
    name: cap(c.name, 60) || 'Unnamed Hero',
    lineage: cap(c.lineage, 60) || 'Unknown lineage',
    charClass: cap(c.charClass, 40) || 'Adventurer',
    level: clamp(Math.round(c.level || 1), 1, 20),
    hpMax,
    hpCurrent: clamp(Math.round(c.hpCurrent || 0), 0, hpMax),
    ac: clamp(Math.round(c.ac || 10), 0, 30),
    abilities,
    // A legacy save may lack conditions entirely (ADR-0008 A-9).
    conditions: (c.conditions ?? []).map((s) => cap(s, 40)).filter(Boolean).slice(0, 8),
  }
}

/** Maps the app model to the snake_case body the backend expects. */
export function toCharacterIn(c: Character): CharacterIn {
  const n = normalizeCharacter(c)
  const speciesId = n.speciesId ?? ''
  const abilities = {} as Record<AbilityKey, number>
  for (const key of ABILITY_KEYS) {
    abilities[key] = n.abilities[key]
  }
  return {
    id: n.id.slice(0, 64),
    name: n.name,
    lineage: n.lineage,
    species_id: speciesId.length <= 64 && SPECIES_ID_PATTERN.test(speciesId) ? speciesId : null,
    char_class: n.charClass,
    level: n.level,
    hp_current: n.hpCurrent,
    hp_max: n.hpMax,
    ac: n.ac,
    abilities,
    conditions: n.conditions,
  }
}
