import { useEffect, useMemo, useRef, useState } from 'react'
import type { Message } from '../types'

interface NarrativeLogProps {
  messages: Message[]
  isSending: boolean
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

function RollCard({ message }: { message: Message }) {
  const roll = rollMeta(message)
  if (!roll) return null
  return (
    <article className="roll-card">
      <div className="roll-die-face" aria-hidden="true">
        ⬢
      </div>
      <div className="roll-body">
        <span className="roll-expression">{roll.expression}</span>
        <span className="roll-total">{roll.total}</span>
        <span className="roll-detail">{message.content}</span>
      </div>
      <time>{toClock(message.created_at)}</time>
    </article>
  )
}

export function NarrativeLog({ messages, isSending }: NarrativeLogProps) {
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
            return <RollCard key={message.id} message={message} />
          }
          const content = message.content ?? ''
          if (message.role === 'user' && content.startsWith('/')) {
            return (
              <p key={message.id} className="command-echo">
                ⚄ {content}
              </p>
            )
          }
          const isDm = message.role === 'assistant'
          return (
            <article key={message.id} className={`bubble ${isDm ? 'dm' : 'player'}`}>
              <header>
                <strong>{isDm ? 'The Dungeon Master' : 'You'}</strong>
                <span className={`status-tag ${message.status}`}>{message.status}</span>
                <time>{toClock(message.created_at)}</time>
              </header>
              <p>{message.content ?? ''}</p>
            </article>
          )
        })
      )}
      {isSending ? <p className="thinking">The DM is pondering…</p> : null}
    </div>
  )
}
