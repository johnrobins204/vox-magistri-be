import { useState } from 'react'
import type { Message } from '../types'
import { isCanon } from '../lib/corrections'

interface CanonToggleProps {
  message: Message
  onToggle: (message: Message) => void
}

export function CanonToggle({ message, onToggle }: CanonToggleProps) {
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

interface AdminCardProps {
  command: Message | null
  reply: Message | null
  onToggleCanon: (message: Message) => void
}

function stringMeta(message: Message | null, key: string): string | null {
  const value = message?.meta?.[key]
  return typeof value === 'string' && value ? value : null
}

/** One collapsible card per admin command: header = command, body = reply (ADR-0015). */
export function AdminCard({ command, reply, onToggleCanon }: AdminCardProps) {
  const [collapsed, setCollapsed] = useState(false)
  const primary = command ?? reply
  if (!primary) return null

  const title = command?.content || stringMeta(reply, 'tool') || 'Admin'
  const bodyText = reply?.content || stringMeta(reply, 'error') || stringMeta(command, 'error')

  return (
    <article className={`admin-card${isCanon(primary) ? '' : ' non-canon'}`}>
      <header>
        <button
          type="button"
          className="ghost admin-card-toggle"
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((value) => !value)}
        >
          {title}
        </button>
        <CanonToggle message={primary} onToggle={onToggleCanon} />
      </header>
      {collapsed ? null : bodyText ? <div className="admin-card-body">{bodyText}</div> : null}
    </article>
  )
}
