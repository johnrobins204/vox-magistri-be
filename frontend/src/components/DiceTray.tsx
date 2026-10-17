import { useState } from 'react'

interface DiceTrayProps {
  onRoll: (expression: string) => void
  disabled: boolean
}

const DICE = [4, 6, 8, 10, 12, 20, 100]

export function DiceTray({ onRoll, disabled }: DiceTrayProps) {
  const [count, setCount] = useState(1)
  const [modifier, setModifier] = useState(0)
  const [custom, setCustom] = useState('')

  const modSuffix = modifier === 0 ? '' : modifier > 0 ? `+${modifier}` : `${modifier}`

  const rollDie = (sides: number) => {
    onRoll(`${count}d${sides}${modSuffix}`)
  }

  const rollCustom = () => {
    const expr = custom.trim()
    if (expr) {
      onRoll(expr)
      setCustom('')
    }
  }

  return (
    <aside className="panel dice-tray">
      <h2>Dice</h2>

      <div className="dice-grid">
        {DICE.map((sides) => (
          <button
            key={sides}
            type="button"
            className={`die d${sides}`}
            onClick={() => rollDie(sides)}
            disabled={disabled}
            title={`Roll ${count}d${sides}${modSuffix}`}
          >
            d{sides}
          </button>
        ))}
      </div>

      <div className="tray-steppers">
        <label>
          Count
          <div className="stepper">
            <button type="button" onClick={() => setCount((c) => Math.max(1, c - 1))} disabled={disabled}>
              −
            </button>
            <span>{count}</span>
            <button type="button" onClick={() => setCount((c) => Math.min(20, c + 1))} disabled={disabled}>
              +
            </button>
          </div>
        </label>
        <label>
          Mod
          <div className="stepper">
            <button type="button" onClick={() => setModifier((m) => Math.max(-20, m - 1))} disabled={disabled}>
              −
            </button>
            <span>{modifier >= 0 ? `+${modifier}` : modifier}</span>
            <button type="button" onClick={() => setModifier((m) => Math.min(20, m + 1))} disabled={disabled}>
              +
            </button>
          </div>
        </label>
      </div>

      <div className="fate-buttons">
        <button type="button" onClick={() => onRoll('adv')} disabled={disabled} title="Roll with advantage (2d20kh1)">
          Adv
        </button>
        <button type="button" onClick={() => onRoll('dis')} disabled={disabled} title="Roll with disadvantage (2d20kl1)">
          Dis
        </button>
      </div>

      <div className="custom-roll">
        <input
          type="text"
          value={custom}
          onChange={(event) => setCustom(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') rollCustom()
          }}
          placeholder="2d6+3"
          maxLength={64}
          disabled={disabled}
        />
        <button type="button" onClick={rollCustom} disabled={disabled || !custom.trim()}>
          Roll
        </button>
      </div>
    </aside>
  )
}
