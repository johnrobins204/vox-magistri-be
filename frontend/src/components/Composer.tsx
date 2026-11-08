import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { getTools } from '../lib/api'
import { applyToolSelection, filterTools, slashQuery } from '../lib/slash'
import type { ToolInfo } from '../types'
import { SlashPicker } from './SlashPicker'

interface ComposerProps {
  draft: string
  onDraftChange: (value: string) => void
  onSubmit: () => void
  canSend: boolean
}

export function Composer({ draft, onDraftChange, onSubmit, canSend }: ComposerProps) {
  const [tools, setTools] = useState<ToolInfo[] | null>(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const [dismissedFor, setDismissedFor] = useState<string | null>(null)
  const toolsRequested = useRef(false)

  const query = slashQuery(draft)
  const matches = tools && query !== null ? filterTools(tools, query) : []
  const open = query !== null && matches.length > 0 && dismissedFor !== draft

  // Fetch the tool list once, on the first "/". On error, tools stays null so the next "/" retries.
  useEffect(() => {
    if (query === null || tools !== null || toolsRequested.current) return
    toolsRequested.current = true
    getTools()
      .then((result) => setTools(result))
      .catch(() => {})
      .finally(() => {
        toolsRequested.current = false
      })
  }, [query, tools])

  // Reset the highlighted row whenever the query changes.
  useEffect(() => {
    setActiveIndex(0)
  }, [query])

  const select = (tool: ToolInfo) => {
    onDraftChange(applyToolSelection(tool, draft))
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (open) {
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setActiveIndex((i) => (i + 1) % matches.length)
        return
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        setActiveIndex((i) => (i - 1 + matches.length) % matches.length)
        return
      }
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        select(matches[activeIndex])
        return
      }
      if (event.key === 'Escape') {
        event.preventDefault()
        setDismissedFor(draft)
        return
      }
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSubmit()
    }
  }

  return (
    <form className="composer panel" onSubmit={handleSubmit}>
      <label htmlFor="prompt">What do you do?</label>
      {open && (
        <SlashPicker
          tools={matches}
          activeIndex={activeIndex}
          onSelect={select}
          onHover={setActiveIndex}
        />
      )}
      <textarea
        id="prompt"
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
        onKeyDown={handleKeyDown}
        maxLength={4096}
        placeholder="I inspect the runes carved into the old gate…  (Enter to act, Shift+Enter for a new line)"
        aria-controls="slash-picker"
        aria-expanded={open}
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
