import { useMemo, useState } from 'react'
import type { Weapon } from '../types'

interface DiceTrayProps {
  onRoll: (expression: string) => void
  disabled: boolean
  weapons?: Weapon[]
  hasCharacter?: boolean
  onAttack?: (name: string, ac: number | null) => void
}

const DICE = [4, 6, 8, 10, 12, 20, 100]
const NO_WEAPONS: Weapon[] = []

export function DiceTray({
  onRoll,
  disabled,
  weapons = NO_WEAPONS,
  hasCharacter = false,
  onAttack = () => {},
}: DiceTrayProps) {
  const [count, setCount] = useState(1)
  const [modifier, setModifier] = useState(0)
  const [custom, setCustom] = useState('')
  const [weapon, setWeapon] = useState('')
  const [targetAc, setTargetAc] = useState('')

  const modSuffix = modifier === 0 ? '' : modifier > 0 ? `+${modifier}` : `${modifier}`

  const weaponNames = useMemo(
    () => [...new Set(weapons.map((w) => w.name))].sort((a, b) => a.localeCompare(b)),
    [weapons],
  )

  // Empty AC means no `vs`; otherwise it must be a whole number 1-40.
  const acTrimmed = targetAc.trim()
  const acValue = acTrimmed === '' ? null : Number(acTrimmed)
  const acValid = acValue === null || (Number.isInteger(acValue) && acValue >= 1 && acValue <= 40)

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

  const attackWithWeapon = () => {
    onAttack(weapon, acValue)
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

      {weapons.length > 0 ? (
        <div className="attack-roll">
          <span className="attack-label">Attack</span>
          <div className="attack-row">
            <select
              value={weapon}
              onChange={(event) => setWeapon(event.target.value)}
              disabled={disabled}
              aria-label="Weapon"
            >
              <option value="">Weapon</option>
              {weaponNames.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <input
              type="number"
              min={1}
              max={40}
              step={1}
              value={targetAc}
              onChange={(event) => setTargetAc(event.target.value)}
              placeholder="AC"
              aria-label="Target AC"
              disabled={disabled}
            />
            <button
              type="button"
              onClick={attackWithWeapon}
              disabled={disabled || !hasCharacter || !weapon || !acValid}
              title={hasCharacter ? 'Attack with the selected weapon' : 'Needs a character'}
            >
              Attack
            </button>
          </div>
        </div>
      ) : null}
    </aside>
  )
}
