import { Menu, type MenuAction } from './Menu'

interface SceneBarProps {
  sessionId: string
  socketStatus: 'connecting' | 'open' | 'closed'
  modelLoaded: boolean
  queuePosition: number | null
  eta: number | null
  onMenuAction: (action: MenuAction) => void
  onRefreshStatus: () => void
}

export function SceneBar({
  sessionId,
  socketStatus,
  modelLoaded,
  queuePosition,
  eta,
  onMenuAction,
  onRefreshStatus,
}: SceneBarProps) {
  return (
    <header className="scene-bar">
      <div className="scene-title">
        <h1>Vox Magistri</h1>
        <span className="scene-subtitle">The table is set. The story waits.</span>
      </div>
      <div className="scene-status">
        <span className={`badge ${socketStatus}`} title="WebSocket connection">
          {socketStatus === 'open' ? '●' : '○'} {socketStatus}
        </span>
        <span className={`badge ${modelLoaded ? 'loaded' : 'cold'}`} title="Inference model">
          {modelLoaded ? 'DM ready' : 'DM warming'}
        </span>
        <button type="button" className="ghost" onClick={onRefreshStatus} disabled={socketStatus !== 'open'}>
          Queue {queuePosition ?? '-'} · {eta ?? '-'}s
        </button>
        <Menu sessionId={sessionId} onAction={onMenuAction} />
      </div>
    </header>
  )
}
