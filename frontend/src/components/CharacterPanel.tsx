// Stub character panel — visual anchor only. Real character data belongs to the
// campaign domain (REQ-0015); until then this is a fixed placeholder hero.

const STUB_CHARACTER = {
  name: 'Kaelen',
  lineage: 'Wood Elf Ranger',
  level: 3,
  hp: { current: 24, max: 28 },
  ac: 14,
  abilities: [
    { key: 'STR', score: 12 },
    { key: 'DEX', score: 16 },
    { key: 'CON', score: 13 },
    { key: 'INT', score: 11 },
    { key: 'WIS', score: 15 },
    { key: 'CHA', score: 10 },
  ],
  conditions: ['Blessed'],
}

function modifier(score: number): string {
  const mod = Math.floor((score - 10) / 2)
  return mod >= 0 ? `+${mod}` : `${mod}`
}

export function CharacterPanel() {
  const hpPct = Math.round((STUB_CHARACTER.hp.current / STUB_CHARACTER.hp.max) * 100)

  return (
    <aside className="panel character-rail">
      <div className="portrait" aria-hidden="true">
        <span>{STUB_CHARACTER.name.charAt(0)}</span>
      </div>
      <h2 className="char-name">{STUB_CHARACTER.name}</h2>
      <p className="char-lineage">
        Level {STUB_CHARACTER.level} · {STUB_CHARACTER.lineage}
      </p>

      <div className="hp-block">
        <div className="hp-labels">
          <span>HP</span>
          <span>
            {STUB_CHARACTER.hp.current} / {STUB_CHARACTER.hp.max}
          </span>
        </div>
        <div className="hp-bar" role="meter" aria-valuenow={hpPct} aria-valuemin={0} aria-valuemax={100}>
          <div className="hp-fill" style={{ width: `${hpPct}%` }} />
        </div>
      </div>

      <div className="ac-chip">
        <span className="ac-value">{STUB_CHARACTER.ac}</span>
        <span className="ac-label">Armor Class</span>
      </div>

      <div className="ability-grid">
        {STUB_CHARACTER.abilities.map((ability) => (
          <div key={ability.key} className="ability">
            <span className="ability-key">{ability.key}</span>
            <span className="ability-score">{ability.score}</span>
            <span className="ability-mod">{modifier(ability.score)}</span>
          </div>
        ))}
      </div>

      <div className="conditions">
        {STUB_CHARACTER.conditions.map((condition) => (
          <span key={condition} className="condition-chip">
            {condition}
          </span>
        ))}
      </div>
    </aside>
  )
}
