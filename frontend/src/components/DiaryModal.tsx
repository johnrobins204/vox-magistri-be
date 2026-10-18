import { useEffect, useMemo, useState } from 'react'
import type { Message } from '../types'

interface DiaryModalProps {
  open: boolean
  messages: Message[]
  sessionId: string
  onClose: () => void
}

interface DiaryEntry {
  id: string
  speaker: 'The Dungeon Master' | 'You'
  text: string
  time: string
}

function toClock(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return value
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function isRollResult(message: Message): boolean {
  const meta = message.meta as { tool?: string } | null
  return meta?.tool === 'roll'
}

function isSlashCommand(message: Message): boolean {
  return message.role === 'user' && (message.content ?? '').startsWith('/')
}

export function DiaryModal({ open, messages, sessionId, onClose }: DiaryModalProps) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!open) return
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onEscape)
    return () => document.removeEventListener('keydown', onEscape)
  }, [open, onClose])

  const entries = useMemo<DiaryEntry[]>(
    () =>
      messages
        .filter((m) => !isRollResult(m) && !isSlashCommand(m) && (m.content ?? '').trim())
        .map((m) => ({
          id: m.id,
          speaker: m.role === 'assistant' ? 'The Dungeon Master' : 'You',
          text: m.content ?? '',
          time: toClock(m.created_at),
        })),
    [messages],
  )

  const rollCount = useMemo(() => messages.filter(isRollResult).length, [messages])

  if (!open) return null

  const copyDiary = async () => {
    const lines = entries.map((e) => `${e.speaker} (${e.time})\n${e.text}`)
    const text = `Vox Magistri — Session Diary\nSession ${sessionId}\n\n${lines.join('\n\n')}`
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard unavailable; leave the button state unchanged.
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal panel diary"
        role="dialog"
        aria-modal="true"
        aria-label="Game Diary"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="modal-header">
          <span className="modal-icon" aria-hidden="true">
            📖
          </span>
          <h2>Game Diary</h2>
          <span className="diary-stats">
            {entries.length} entries · {rollCount} rolls
          </span>
          <button type="button" className="ghost" onClick={() => void copyDiary()}>
            {copied ? 'Copied!' : 'Copy'}
          </button>
          <button type="button" className="ghost modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="diary-scroll">
          {entries.length === 0 ? (
            <p className="empty">The diary is blank — the tale has not yet begun.</p>
          ) : (
            entries.map((entry) => (
              <section key={entry.id} className={`diary-entry ${entry.speaker === 'You' ? 'player' : 'dm'}`}>
                <header>
                  <strong>{entry.speaker}</strong>
                  <time>{entry.time}</time>
                </header>
                <p>{entry.text}</p>
              </section>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
