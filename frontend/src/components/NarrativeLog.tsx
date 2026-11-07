import { useEffect, useMemo, useRef, useState } from 'react'
import type { Message } from '../types'
import { canCorrect, isCanon, isEdited } from '../lib/corrections'

interface NarrativeLogProps {
  messages: Message[]
  isSending: boolean
  onToggleCanon: (message: Message) => void
  onEdit: (message: Message, text: string) => void
  onRegenerate: (message: Message) => void
}

// Only the most recent turns render on screen; the full chronicle lives in
// state (and the Game Diary). A "turn" is a player action plus everything the
// table produced in response (DM narration, roll results).
const VISIBLE_TURNS = 6

function toClock(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) {
    return value
  }
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function rollMeta(message: Message): { expression: string; total: number } | null {
  const meta = message.meta as { tool?: string; expression?: string; total?: number } | null
  if (meta && meta.tool === 'roll' && typeof meta.total === 'number') {
    return { expression: meta.expression ?? '', total: meta.total }
  }
  return null
}

interface CanonToggleProps {
  message: Message
  onToggle: (message: Message) => void
}

function CanonToggle({ message, onToggle }: CanonToggleProps) {
  const canon = isCanon(message)
  return (
    <button
      type="button"
      className="ghost canon-toggle"
      title={canon ? 'Mark this entry as not canon' : 'Mark this entry as canon'}
      onClick={() => onToggle(message)}
    >
      {canon ? 'Canon' : 'Not canon'}
    </button>
  )
}

function RollCard({ message, onToggleCanon }: { message: Message; onToggleCanon: (message: Message) => void }) {
  const roll = rollMeta(message)
  if (!roll) return null
  return (
    <article className={`roll-card${isCanon(message) ? '' : ' non-canon'}`}>
      <div className="roll-die-face" aria-hidden="true">
        ⬢
      </div>
      <div className="roll-body">
        <span className="roll-expression">{roll.expression}</span>
        <span className="roll-total">{roll.total}</span>
        <span className="roll-detail">{message.content}</span>
      </div>
      <time>{toClock(message.created_at)}</time>
      <CanonToggle message={message} onToggle={onToggleCanon} />
    </article>
  )
}

interface BubbleProps {
  message: Message
  isSending: boolean
  onToggleCanon: (message: Message) => void
  onEdit: (message: Message, text: string) => void
  onRegenerate: (message: Message) => void
}

function Bubble({ message, isSending, onToggleCanon, onEdit, onRegenerate }: BubbleProps) {
  const isDm = message.role === 'assistant'
  const correctable = canCorrect(message)
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const trimmed = editText.trim()

  const startEdit = () => {
    setEditText(message.content ?? '')
    setEditing(true)
  }

  const saveEdit = () => {
    if (!trimmed) return
    onEdit(message, trimmed)
    setEditing(false)
  }

  return (
    <article className={`bubble ${isDm ? 'dm' : 'player'}${isCanon(message) ? '' : ' non-canon'}`}>
      <header>
        <strong>{isDm ? 'The Dungeon Master' : 'You'}</strong>
        <span className={`status-tag ${message.status}`}>{message.status}</span>
        {isEdited(message) ? <span className="edited-badge">edited</span> : null}
        <time>{toClock(message.created_at)}</time>
      </header>
      {editing ? (
        <div className="edit-form">
          <textarea
            aria-label="Edit this reply"
            value={editText}
            onChange={(event) => setEditText(event.target.value)}
            rows={4}
          />
          <div className="bubble-actions">
            <button type="button" className="correction-action" disabled={!trimmed} onClick={saveEdit}>
              Save
            </button>
            <button type="button" className="ghost correction-action" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <p>{message.content ?? ''}</p>
      )}
      <div className="bubble-actions">
        {correctable && !editing ? (
          <>
            <button type="button" className="ghost correction-action" onClick={startEdit}>
              Edit
            </button>
            <button
              type="button"
              className="ghost correction-action"
              disabled={isSending}
              onClick={() => onRegenerate(message)}
            >
              Regenerate
            </button>
          </>
        ) : null}
        <CanonToggle message={message} onToggle={onToggleCanon} />
      </div>
    </article>
  )
}

export function NarrativeLog({ messages, isSending, onToggleCanon, onEdit, onRegenerate }: NarrativeLogProps) {
  const logRef = useRef<HTMLDivElement | null>(null)
  const [expanded, setExpanded] = useState(false)

  const { visible, hiddenCount } = useMemo(() => {
    if (expanded || messages.length === 0) {
      return { visible: messages, hiddenCount: 0 }
    }
    // Walk backwards counting player (non-command) messages as turn starts.
    let turns = 0
    let cut = messages.length
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i]
      const isCommand = m.role === 'user' && (m.content ?? '').startsWith('/')
      if (m.role === 'user' && !isCommand) {
        turns += 1
        if (turns > VISIBLE_TURNS) {
          cut = i + 1
          break
        }
        cut = i
      }
    }
    return { visible: messages.slice(cut), hiddenCount: cut }
  }, [messages, expanded])

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [visible, isSending])

  return (
    <div className="thread-log" ref={logRef}>
      {hiddenCount > 0 ? (
        <button type="button" className="ghost earlier-note" onClick={() => setExpanded(true)}>
          ⬆ {hiddenCount} earlier {hiddenCount === 1 ? 'entry' : 'entries'} — reveal (full tale in the Game Diary)
        </button>
      ) : null}
      {expanded && messages.length > 0 ? (
        <button type="button" className="ghost earlier-note" onClick={() => setExpanded(false)}>
          ⬇ Show only recent turns
        </button>
      ) : null}
      {visible.length === 0 && !isSending ? (
        <p className="empty">The table is quiet. Describe your first move.</p>
      ) : (
        visible.map((message) => {
          if (message.role === 'assistant' && rollMeta(message)) {
            return <RollCard key={message.id} message={message} onToggleCanon={onToggleCanon} />
          }
          const content = message.content ?? ''
          if (message.role === 'user' && content.startsWith('/')) {
            return (
              <p key={message.id} className={`command-echo${isCanon(message) ? '' : ' non-canon'}`}>
                ⚄ {content} <CanonToggle message={message} onToggle={onToggleCanon} />
              </p>
            )
          }
          return (
            <Bubble
              key={message.id}
              message={message}
              isSending={isSending}
              onToggleCanon={onToggleCanon}
              onEdit={onEdit}
              onRegenerate={onRegenerate}
            />
          )
        })
      )}
      {isSending ? <p className="thinking">The DM is pondering…</p> : null}
    </div>
  )
}
