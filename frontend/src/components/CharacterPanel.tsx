import { ABILITY_KEYS, modifier, type Character } from '../lib/character'

interface CharacterPanelProps {
  character: Character
}

export function CharacterPanel({ character }: CharacterPanelProps) {
  const hpPct = character.hpMax > 0 ? Math.round((character.hpCurrent / character.hpMax) * 100) : 0

  return (
    <aside className="panel character-rail">
      <div className="portrait" aria-hidden="true">
        <span>{character.name.charAt(0).toUpperCase() || '?'}</span>
      </div>
      <h2 className="char-name">{character.name}</h2>
      <p className="char-lineage">
        Level {character.level} · {character.lineage} {character.charClass}
      </p>

      <div className="hp-block">
        <div className="hp-labels">
          <span>HP</span>
          <span>
            {character.hpCurrent} / {character.hpMax}
          </span>
        </div>
        <div className="hp-bar" role="meter" aria-valuenow={hpPct} aria-valuemin={0} aria-valuemax={100}>
          <div className="hp-fill" style={{ width: `${hpPct}%` }} />
        </div>
      </div>

      <div className="ac-chip">
        <span className="ac-value">{character.ac}</span>
        <span className="ac-label">Armor Class</span>
      </div>

      <div className="ability-grid">
        {ABILITY_KEYS.map((key) => (
          <div key={key} className="ability">
            <span className="ability-key">{key}</span>
            <span className="ability-score">{character.abilities[key]}</span>
            <span className="ability-mod">{modifier(character.abilities[key])}</span>
          </div>
        ))}
      </div>

      <div className="conditions">
        {character.conditions.map((condition) => (
          <span key={condition} className="condition-chip">
            {condition}
          </span>
        ))}
      </div>
    </aside>
  )
}
