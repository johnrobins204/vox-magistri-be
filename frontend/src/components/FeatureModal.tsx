import { useEffect } from 'react'

export type FeatureKey = 'world-builder' | 'campaign-builder' | 'dice-log' | 'settings'

interface FeatureModalProps {
  feature: FeatureKey | null
  onClose: () => void
}

const FEATURES: Record<FeatureKey, { icon: string; title: string; body: string; roadmap: string }> = {
  'world-builder': {
    icon: '🗺',
    title: 'World Builder',
    body: 'Shape the realms your tales unfold in — geography, factions, deities, and the laws of magic. The DM will draw on this lore when narrating.',
    roadmap: 'Backed by the world guidance pipeline (world_guide.py); a dedicated editor arrives with the campaign domain (REQ-0015).',
  },
  'campaign-builder': {
    icon: '📜',
    title: 'Campaign Builder',
    body: 'Weave quests, arcs, and consequences into a campaign spine. Track hooks, NPCs, and what the party has set in motion.',
    roadmap: 'Quest guidance exists in the prompt pipeline (quest_guide.py); structured campaign state is part of REQ-0015.',
  },
  'dice-log': {
    icon: '⚄',
    title: 'Dice Log',
    body: 'Every roll this session, with full formula breakdowns. Roll cards already appear inline in the chronicle.',
    roadmap: 'A filterable roll history view is planned once sessions gain richer metadata.',
  },
  settings: {
    icon: '⚙',
    title: 'Settings',
    body: 'Table preferences — DM voice and tone, narration verbosity, and connection details.',
    roadmap: 'The backend already exposes prompt/voice settings (settings.json); a UI for them is a future increment.',
  },
}

export function FeatureModal({ feature, onClose }: FeatureModalProps) {
  useEffect(() => {
    if (!feature) return
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onEscape)
    return () => document.removeEventListener('keydown', onEscape)
  }, [feature, onClose])

  if (!feature) return null
  const content = FEATURES[feature]

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal panel"
        role="dialog"
        aria-modal="true"
        aria-label={content.title}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="modal-header">
          <span className="modal-icon" aria-hidden="true">
            {content.icon}
          </span>
          <h2>{content.title}</h2>
          <button type="button" className="ghost modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <p className="modal-body">{content.body}</p>
        <p className="modal-roadmap">{content.roadmap}</p>
      </div>
    </div>
  )
}
