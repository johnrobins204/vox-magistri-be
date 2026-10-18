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

export function normalizeCharacter(c: Character): Character {
  const abilities = { ...c.abilities }
  for (const key of ABILITY_KEYS) {
    abilities[key] = clamp(Math.round(abilities[key] || 10), 3, 20)
  }
  const hpMax = clamp(Math.round(c.hpMax || 1), 1, 999)
  return {
    ...c,
    name: c.name.trim() || 'Unnamed Hero',
    lineage: c.lineage.trim() || 'Unknown lineage',
    charClass: c.charClass.trim() || 'Adventurer',
    level: clamp(Math.round(c.level || 1), 1, 20),
    hpMax,
    hpCurrent: clamp(Math.round(c.hpCurrent), 0, hpMax),
    ac: clamp(Math.round(c.ac || 10), 0, 30),
    abilities,
    conditions: c.conditions.map((s) => s.trim()).filter(Boolean).slice(0, 8),
  }
}
