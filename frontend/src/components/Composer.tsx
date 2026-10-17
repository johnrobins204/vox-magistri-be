import type { FormEvent, KeyboardEvent } from 'react'

interface ComposerProps {
  draft: string
  onDraftChange: (value: string) => void
  onSubmit: () => void
  canSend: boolean
}

export function Composer({ draft, onDraftChange, onSubmit, canSend }: ComposerProps) {
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSubmit()
    }
  }

  return (
    <form className="composer panel" onSubmit={handleSubmit}>
      <label htmlFor="prompt">What do you do?</label>
      <textarea
        id="prompt"
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
        onKeyDown={handleKeyDown}
        maxLength={4096}
        placeholder="I inspect the runes carved into the old gate…  (Enter to act, Shift+Enter for a new line)"
      />
      <div className="composer-row">
        <span>{draft.length}/4096</span>
        <button type="submit" disabled={!canSend}>
          Act
        </button>
      </div>
    </form>
  )
}
