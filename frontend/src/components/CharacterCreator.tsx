import { useEffect, useState } from 'react'
import {
  ABILITY_KEYS,
  modifier,
  newCharacter,
  normalizeCharacter,
  rollAbilityScore,
  type Character,
} from '../lib/character'
import { getSpecies } from '../lib/api'
import type { Species } from '../types'
import { SpeciesBrowser } from './SpeciesBrowser'

interface CharacterCreatorProps {
  open: boolean
  roster: Character[]
  activeId: string | null
  onSave: (character: Character) => void
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onClose: () => void
  onBrowseAll?: () => void
}

const CLASS_SUGGESTIONS = ['Barbarian', 'Bard', 'Cleric', 'Druid', 'Fighter', 'Monk', 'Paladin', 'Ranger', 'Rogue', 'Sorcerer', 'Warlock', 'Wizard']

export function CharacterCreator({
  open,
  roster,
  activeId,
  onSave,
  onSelect,
  onDelete,
  onClose,
  onBrowseAll,
}: CharacterCreatorProps) {
  const [editing, setEditing] = useState<Character | null>(null)
  const [conditionsText, setConditionsText] = useState('')
  const [species, setSpecies] = useState<Species[] | null>(null)
  const [speciesFailed, setSpeciesFailed] = useState(false)
  const [browsing, setBrowsing] = useState(false)

  useEffect(() => {
    if (open) {
      setEditing(null) // always land on the roster
      setBrowsing(false)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !browsing) {
        if (editing) {
          setEditing(null)
        } else {
          onClose()
        }
      }
    }
    document.addEventListener('keydown', onEscape)
    return () => document.removeEventListener('keydown', onEscape)
  }, [open, editing, browsing, onClose])

  const editorOpen = open && editing !== null

  useEffect(() => {
    if (!editorOpen) return
    let cancelled = false
    setSpeciesFailed(false)
    getSpecies()
      .then((list) => {
        if (!cancelled) setSpecies(list)
      })
      .catch(() => {
        if (!cancelled) setSpeciesFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [editorOpen])

  // Preselects the one 5.5e species matching a legacy lineage; saved only on Forge Hero.
  useEffect(() => {
    if (!editing || editing.speciesId || !species) return
    const lineage = editing.lineage.trim().toLowerCase()
    const matches = species.filter((s) => s.edition === '5.5e' && s.name.toLowerCase() === lineage)
    if (matches.length === 1) {
      const id = matches[0].id
      setEditing((d) => (d && !d.speciesId ? { ...d, speciesId: id } : d))
    }
  }, [species, editing?.id])

  if (!open) return null

  const baseSpecies = species?.filter((s) => s.edition === '5.5e') ?? []
  const speciesReady = species !== null && !speciesFailed

  const openBrowser = () => {
    setBrowsing(true)
    onBrowseAll?.()
  }

  const startEdit = (character: Character) => {
    setEditing(character)
    setConditionsText(character.conditions.join(', '))
  }

  const saveEdit = () => {
    if (!editing) return
    onSave(normalizeCharacter({ ...editing, conditions: conditionsText.split(',') }))
    setEditing(null)
  }

  const patch = (changes: Partial<Character>) =>
    setEditing((d) => (d ? { ...d, ...changes } : d))

  const pickSpecies = (picked: Species) => {
    patch({ lineage: picked.name, speciesId: picked.id })
    setBrowsing(false)
  }

  const setAbility = (key: (typeof ABILITY_KEYS)[number], score: number) =>
    setEditing((d) => (d ? { ...d, abilities: { ...d.abilities, [key]: score } } : d))

  const isExisting = editing !== null && roster.some((c) => c.id === editing.id)

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal panel creator"
        role="dialog"
        aria-modal="true"
        aria-label="Character Builder"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="modal-header">
          <span className="modal-icon" aria-hidden="true">
            ⚔
          </span>
          <h2>{editing ? (isExisting ? 'Edit Hero' : 'New Hero') : 'Your Heroes'}</h2>
          <button type="button" className="ghost modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        {editing === null ? (
          <>
            <div className="creator-scroll">
              {roster.length === 0 ? (
                <p className="empty">No heroes yet — forge your first.</p>
              ) : (
                <ul className="roster-list">
                  {roster.map((c) => (
                    <li key={c.id} className={`roster-row ${c.id === activeId ? 'active' : ''}`}>
                      <button
                        type="button"
                        className="roster-main"
                        onClick={() => onSelect(c.id)}
                        title={c.id === activeId ? 'At the table' : 'Bring to the table'}
                      >
                        <span className="roster-initial">{c.name.charAt(0).toUpperCase() || '?'}</span>
                        <span className="roster-text">
                          <span className="roster-name">{c.name}</span>
                          <span className="roster-sub">
                            Level {c.level} · {c.lineage} {c.charClass}
                          </span>
                        </span>
                        {c.id === activeId ? <span className="roster-active-tag">At the table</span> : null}
                      </button>
                      <button type="button" className="ghost" onClick={() => startEdit(c)} title="Edit">
                        ✎
                      </button>
                      <button
                        type="button"
                        className="ghost roster-delete"
                        onClick={() => onDelete(c.id)}
                        title="Retire this hero"
                      >
                        🗑
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <footer className="creator-actions">
              <span className="roster-count">
                {roster.length} {roster.length === 1 ? 'hero' : 'heroes'}
              </span>
              <button type="button" onClick={() => startEdit(newCharacter())}>
                Forge New Hero
              </button>
            </footer>
          </>
        ) : (
          <>
            <div className="creator-scroll">
              <div className="creator-grid">
                <label className="field span-2">
                  <span>Name</span>
                  <input
                    type="text"
                    value={editing.name}
                    onChange={(e) => patch({ name: e.target.value })}
                    placeholder="Kaelen"
                    maxLength={40}
                    autoFocus
                  />
                </label>
                <label className="field">
                  <span>Lineage</span>
                  <input
                    type="text"
                    value={editing.lineage}
                    onChange={(e) => patch({ lineage: e.target.value })}
                    placeholder="Wood Elf"
                    maxLength={40}
                  />
                </label>
                <label className="field">
                  <span>Class</span>
                  <input
                    type="text"
                    list="class-options"
                    value={editing.charClass}
                    onChange={(e) => patch({ charClass: e.target.value })}
                    placeholder="Ranger"
                    maxLength={40}
                  />
                  <datalist id="class-options">
                    {CLASS_SUGGESTIONS.map((c) => (
                      <option key={c} value={c} />
                    ))}
                  </datalist>
                </label>
                <label className="field">
                  <span>Level</span>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={editing.level}
                    onChange={(e) => patch({ level: Number(e.target.value) })}
                  />
                </label>
                <label className="field">
                  <span>HP (current)</span>
                  <input
                    type="number"
                    min={0}
                    max={999}
                    value={editing.hpCurrent}
                    onChange={(e) => patch({ hpCurrent: Number(e.target.value) })}
                  />
                </label>
                <label className="field">
                  <span>HP (max)</span>
                  <input
                    type="number"
                    min={1}
                    max={999}
                    value={editing.hpMax}
                    onChange={(e) => patch({ hpMax: Number(e.target.value) })}
                  />
                </label>
                <label className="field">
                  <span>Armor Class</span>
                  <input
                    type="number"
                    min={0}
                    max={30}
                    value={editing.ac}
                    onChange={(e) => patch({ ac: Number(e.target.value) })}
                  />
                </label>
              </div>

              <div className="species-picker">
                <h3 className="creator-section">Base Species</h3>
                {speciesFailed ? (
                  <p className="empty">Species list unavailable</p>
                ) : species === null ? (
                  <p className="empty">Loading species…</p>
                ) : baseSpecies.length === 0 ? (
                  <p className="empty">No base species on file.</p>
                ) : (
                  <ul className="species-list">
                    {baseSpecies.map((s) => (
                      <li key={s.id}>
                        <button
                          type="button"
                          className={`species-option ${editing.speciesId === s.id ? 'selected' : ''}`}
                          aria-pressed={editing.speciesId === s.id}
                          onClick={() => patch({ lineage: s.name, speciesId: s.id })}
                        >
                          <span className="species-name">{s.name}</span>
                          <span className="species-desc">{s.description}</span>
                          <span className="species-impl">{s.character_creation_implications}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="species-footer">
                  <button type="button" className="ghost" onClick={openBrowser} disabled={!speciesReady}>
                    Browse all species
                  </button>
                </div>
              </div>

              <h3 className="creator-section">Ability Scores</h3>
              <div className="creator-abilities">
                {ABILITY_KEYS.map((key) => (
                  <div key={key} className="creator-ability">
                    <span className="ability-key">{key}</span>
                    <div className="stepper">
                      <button type="button" onClick={() => setAbility(key, editing.abilities[key] - 1)}>
                        −
                      </button>
                      <span>{editing.abilities[key]}</span>
                      <button type="button" onClick={() => setAbility(key, editing.abilities[key] + 1)}>
                        +
                      </button>
                    </div>
                    <span className="ability-mod">{modifier(editing.abilities[key])}</span>
                    <button
                      type="button"
                      className="ghost roll-ability"
                      title="Roll 4d6, drop the lowest"
                      onClick={() => setAbility(key, rollAbilityScore())}
                    >
                      ⚄
                    </button>
                  </div>
                ))}
              </div>

              <label className="field">
                <span>Conditions (comma separated)</span>
                <input
                  type="text"
                  value={conditionsText}
                  onChange={(e) => setConditionsText(e.target.value)}
                  placeholder="Blessed, Inspired"
                  maxLength={120}
                />
              </label>
              {isExisting && editing.id === activeId ? (
                <p className="roster-sub">Changes reach the DM at the next New Tale.</p>
              ) : null}
            </div>

            <footer className="creator-actions">
              <button type="button" className="ghost" onClick={() => setEditing(null)}>
                ← Roster
              </button>
              <button type="button" onClick={saveEdit}>
                Forge Hero
              </button>
            </footer>
          </>
        )}
      </div>
      {browsing && species ? (
        <SpeciesBrowser species={species} onPick={pickSpecies} onClose={() => setBrowsing(false)} />
      ) : null}
    </div>
  )
}
