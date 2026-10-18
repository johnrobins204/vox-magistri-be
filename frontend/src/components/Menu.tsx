import { useEffect, useRef, useState } from 'react'

export type MenuAction =
  | 'world-builder'
  | 'campaign-builder'
  | 'character-builder'
  | 'game-diary'
  | 'dice-log'
  | 'settings'
  | 'new-tale'
  | 'copy-session'

interface MenuProps {
  sessionId: string
  onAction: (action: MenuAction) => void
}

const ITEMS: { action: MenuAction; icon: string; label: string; hint: string }[] = [
  { action: 'world-builder', icon: '🗺', label: 'World Builder', hint: 'Realms, regions, and lore' },
  { action: 'campaign-builder', icon: '📜', label: 'Campaign Builder', hint: 'Quests and story arcs' },
  { action: 'character-builder', icon: '⚔', label: 'Character Builder', hint: 'Your roster of heroes' },
  { action: 'game-diary', icon: '📖', label: 'Game Diary', hint: 'The tale so far, as a journal' },
  { action: 'dice-log', icon: '⚄', label: 'Dice Log', hint: 'Every roll this session' },
  { action: 'settings', icon: '⚙', label: 'Settings', hint: 'Table preferences' },
]

export function Menu({ sessionId, onAction }: MenuProps) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onEscape)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onEscape)
    }
  }, [open])

  const copySession = async () => {
    try {
      await navigator.clipboard.writeText(sessionId)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard unavailable (non-secure context); nothing sensible to do.
    }
  }

  return (
    <div className="menu-root" ref={rootRef}>
      <button
        type="button"
        className="menu-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        title="Table menu"
      >
        ☰
      </button>

      {open ? (
        <div className="menu-dropdown" role="menu">
          {ITEMS.map((item) => (
            <button
              key={item.action}
              type="button"
              role="menuitem"
              className="menu-item"
              onClick={() => {
                setOpen(false)
                onAction(item.action)
              }}
            >
              <span className="menu-icon" aria-hidden="true">
                {item.icon}
              </span>
              <span className="menu-text">
                <span className="menu-label">{item.label}</span>
                <span className="menu-hint">{item.hint}</span>
              </span>
            </button>
          ))}

          <div className="menu-separator" role="separator" />

          <button
            type="button"
            role="menuitem"
            className="menu-item"
            onClick={() => {
              void copySession()
            }}
          >
            <span className="menu-icon" aria-hidden="true">
              ⧉
            </span>
            <span className="menu-text">
              <span className="menu-label">{copied ? 'Copied!' : 'Copy Session ID'}</span>
              <span className="menu-hint mono">{sessionId ? sessionId.slice(0, 8) : '…'}</span>
            </span>
          </button>

          <button
            type="button"
            role="menuitem"
            className="menu-item danger"
            onClick={() => {
              setOpen(false)
              onAction('new-tale')
            }}
          >
            <span className="menu-icon" aria-hidden="true">
              ✦
            </span>
            <span className="menu-text">
              <span className="menu-label">New Tale</span>
              <span className="menu-hint">Abandon this session, start fresh</span>
            </span>
          </button>
        </div>
      ) : null}
    </div>
  )
}
