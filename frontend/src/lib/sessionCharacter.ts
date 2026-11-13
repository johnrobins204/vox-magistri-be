import type { CharacterDocumentV1 } from './characterDocument'
import type { CharacterIn } from '../types'

export function createSessionCharacterSnapshot(
  document: CharacterDocumentV1,
): CharacterIn {
  const c = document.character

  return {
    id: c.id,
    name: c.name,
    lineage: c.lineage,
    species_id: c.speciesId ?? null,
    char_class: c.charClass,
    level: c.level,
    hp_current: c.hpCurrent,
    hp_max: c.hpMax,
    ac: c.ac,
    abilities: c.abilities,
    conditions: [...c.conditions],
  }
}