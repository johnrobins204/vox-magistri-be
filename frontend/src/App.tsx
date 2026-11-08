import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createSession, getIntelStatus, getWeapons, listMessages, updateMessage } from './lib/api'
import { openSessionSocket, type SessionSocket } from './lib/ws'
import { isCanon } from './lib/corrections'
import { CharacterCreator } from './components/CharacterCreator'
import { CharacterPanel } from './components/CharacterPanel'
import { Composer } from './components/Composer'
import { DiaryModal } from './components/DiaryModal'
import { DiceTray } from './components/DiceTray'
import { FeatureModal, type FeatureKey } from './components/FeatureModal'
import { NarrativeLog } from './components/NarrativeLog'
import { SceneBar } from './components/SceneBar'
import { loadActiveId, loadRoster, removeCharacter, resolveActive, saveActiveId, saveRoster, sendableHero, upsertCharacter } from './lib/roster'
import type { Character } from './lib/character'
import type { MenuAction } from './components/Menu'
import type { Message, WsEvent, Weapon } from './types'

const SESSION_STORAGE_KEY = 'vox.session_id'

function byNewest(messages: Message[]): Message[] {
  return [...messages].sort((a, b) => a.created_at.localeCompare(b.created_at))
}

function upsertMessage(messages: Message[], nextMessage: Message): Message[] {
  const index = messages.findIndex((entry) => entry.id === nextMessage.id)
  if (index === -1) {
    return byNewest([...messages, nextMessage])
  }
  const clone = [...messages]
  clone[index] = nextMessage
  return byNewest(clone)
}

function App() {
  const [sessionId, setSessionId] = useState<string>('')
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState<string>('')
  const [socketStatus, setSocketStatus] = useState<'connecting' | 'open' | 'closed'>('connecting')
  const [queuePosition, setQueuePosition] = useState<number | null>(null)
  const [eta, setEta] = useState<number | null>(null)
  const [modelLoaded, setModelLoaded] = useState<boolean>(false)
  const [errorText, setErrorText] = useState<string>('')
  const [isSending, setIsSending] = useState<boolean>(false)
  const [activeFeature, setActiveFeature] = useState<FeatureKey | null>(null)
  const [diaryOpen, setDiaryOpen] = useState<boolean>(false)
  const [creatorOpen, setCreatorOpen] = useState<boolean>(false)
  const [roster, setRoster] = useState<Character[]>(() => loadRoster())
  const [activeCharacterId, setActiveCharacterId] = useState<string | null>(() => loadActiveId())
  const [weapons, setWeapons] = useState<Weapon[]>([])
  const socketRef = useRef<SessionSocket | null>(null)

  const character = resolveActive(roster, activeCharacterId)
  const hasCharacter = sendableHero(roster, activeCharacterId) !== null

  const canSend = useMemo(
    () => socketStatus === 'open' && draft.trim().length > 0 && !isSending,
    [socketStatus, draft, isSending],
  )

  // Weapon picker source: loaded once; on failure the tray simply shows no picker.
  useEffect(() => {
    let mounted = true
    getWeapons()
      .then((list) => {
        if (mounted) setWeapons(list)
      })
      .catch(() => {
        // Keep []: the dice tray works without the picker.
      })
    return () => {
      mounted = false
    }
  }, [])

  // Bootstrap: intel status, then restore the stored session or create a new one.
  useEffect(() => {
    let mounted = true

    const start = async () => {
      try {
        const intel = await getIntelStatus()
        if (!mounted) return
        setModelLoaded(intel.model_loaded)
        setQueuePosition(intel.queue_position)
        setEta(intel.estimated_wait_seconds)

        const storedId = localStorage.getItem(SESSION_STORAGE_KEY)
        if (storedId) {
          try {
            await listMessages(storedId) // 404 -> fall through to a new session
            if (!mounted) return
            setSessionId(storedId)
            return
          } catch {
            localStorage.removeItem(SESSION_STORAGE_KEY)
          }
        }

        const session = await createSession(sendableHero(roster, activeCharacterId))
        if (!mounted) return
        localStorage.setItem(SESSION_STORAGE_KEY, session.session_id)
        setSessionId(session.session_id)
      } catch (error) {
        if (!mounted) return
        setErrorText(error instanceof Error ? error.message : 'Failed to reach the backend')
        setSocketStatus('closed')
      }
    }

    void start()
    return () => {
      mounted = false
    }
  }, [])

  // Connect the socket and load history whenever the session changes.
  useEffect(() => {
    if (!sessionId) return
    let mounted = true
    setSocketStatus('connecting')

    const load = async () => {
      try {
        const messageList = await listMessages(sessionId)
        if (!mounted) return
        setMessages(byNewest(messageList.messages))
      } catch (error) {
        if (!mounted) return
        setErrorText(error instanceof Error ? error.message : 'Failed to load messages')
      }
    }
    void load()

    const socket = openSessionSocket(sessionId, {
      onOpen: () => mounted && setSocketStatus('open'),
      onClose: () => {
        if (!mounted) return
        setSocketStatus('closed')
        setIsSending(false)
      },
      onError: (message) => {
        if (!mounted) return
        setErrorText(message)
        setIsSending(false)
      },
      onEvent: (event: WsEvent) => {
        if (!mounted) return
        if (event.type === 'snapshot') {
          setMessages(byNewest(event.entries))
        } else if (event.type === 'entry') {
          setMessages((existing) => upsertMessage(existing, event.entry))
        } else if (event.type === 'status') {
          setQueuePosition(event.queue_position)
          setEta(event.estimated_wait_seconds)
        } else if (event.type === 'done') {
          // The server never pushes the user message's own status flip; apply it locally.
          setMessages((existing) =>
            existing.map((m) =>
              m.id === event.message_id ? { ...m, status: 'completed' } : m,
            ),
          )
          setIsSending(false)
        } else if (event.type === 'error') {
          setErrorText(event.message)
          setIsSending(false)
        }
      },
    })
    socketRef.current = socket

    return () => {
      mounted = false
      socketRef.current = null
      socket.close()
    }
  }, [sessionId])

  const sendText = useCallback(
    (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || !socketRef.current || socketStatus !== 'open' || isSending) return
      setErrorText('')
      setIsSending(true)
      socketRef.current.sendUserMessage(trimmed, crypto.randomUUID())
    },
    [socketStatus, isSending],
  )

  const submitDraft = useCallback(() => {
    sendText(draft)
    setDraft('')
  }, [sendText, draft])

  const rollDice = useCallback(
    (expression: string) => {
      sendText(`/roll ${expression}`)
    },
    [sendText],
  )

  const attack = useCallback(
    (name: string, ac: number | null) => {
      sendText(ac === null ? `/attack ${name}` : `/attack ${name} vs ${ac}`)
    },
    [sendText],
  )

  const changeMessage = async (message: Message, changes: { content?: string; canon?: boolean }) => {
    if (!sessionId) return
    try {
      const updated = await updateMessage(sessionId, message.id, changes)
      setMessages((existing) => upsertMessage(existing, updated))
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : 'Failed to update the message')
    }
  }

  const toggleCanon = (message: Message) => changeMessage(message, { canon: !isCanon(message) })

  const editMessage = (message: Message, text: string) => changeMessage(message, { content: text })

  const regenerate = (message: Message) => {
    if (!socketRef.current || socketStatus !== 'open') return
    setErrorText('')
    setIsSending(true)
    socketRef.current.sendRegenerate(message.id)
  }

  const startNewSession = async (hero: Character | null = sendableHero(roster, activeCharacterId)) => {
    try {
      setErrorText('')
      setMessages([])
      const session = await createSession(hero)
      localStorage.setItem(SESSION_STORAGE_KEY, session.session_id)
      setSessionId(session.session_id)
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : 'Failed to create a session')
    }
  }

  const handleMenuAction = (action: MenuAction) => {
    if (action === 'new-tale') {
      void startNewSession()
      return
    }
    if (action === 'copy-session') {
      return // handled inside the menu itself
    }
    if (action === 'game-diary') {
      setDiaryOpen(true)
      return
    }
    if (action === 'character-builder') {
      setCreatorOpen(true)
      return
    }
    setActiveFeature(action)
  }

  // ADR-0008 D3: a hero change at the table starts a new tale, after a confirm.
  const handleSaveCharacter = (next: Character) => {
    const nextRoster = upsertCharacter(roster, next)
    saveRoster(nextRoster)
    setRoster(nextRoster)
    const saved = nextRoster.find((c) => c.id === next.id) ?? next
    if (saved.id === character.id) {
      saveActiveId(saved.id)
      setActiveCharacterId(saved.id)
      return
    }
    if (!window.confirm(`Start a new tale with ${saved.name}?`)) return
    saveActiveId(saved.id)
    setActiveCharacterId(saved.id)
    void startNewSession(saved)
  }

  const handleSelectCharacter = (id: string) => {
    if (id === character.id) return
    const target = roster.find((c) => c.id === id)
    if (!target || !window.confirm(`Start a new tale with ${target.name}?`)) return
    saveActiveId(id)
    setActiveCharacterId(id)
    void startNewSession(target)
  }

  const handleDeleteCharacter = (id: string) => {
    const nextRoster = removeCharacter(roster, id)
    if (id !== character.id) {
      saveRoster(nextRoster)
      setRoster(nextRoster)
      return
    }
    const fallback = nextRoster[0] ?? null
    const question = fallback
      ? `Start a new tale with ${fallback.name}?`
      : 'Start a new tale without a hero?'
    if (!window.confirm(question)) return
    saveRoster(nextRoster)
    setRoster(nextRoster)
    saveActiveId(fallback?.id ?? null)
    setActiveCharacterId(fallback?.id ?? null)
    void startNewSession(fallback)
  }

  const askStatus = () => {
    if (socketStatus === 'open') socketRef.current?.sendStatus()
  }

  return (
    <main className="playboard">
      <SceneBar
        sessionId={sessionId}
        socketStatus={socketStatus}
        modelLoaded={modelLoaded}
        queuePosition={queuePosition}
        eta={eta}
        onMenuAction={handleMenuAction}
        onRefreshStatus={askStatus}
      />

      <div className="board-grid">
        <CharacterPanel character={character} />

        <section className="panel thread">
          <NarrativeLog
            messages={messages}
            isSending={isSending}
            onToggleCanon={toggleCanon}
            onEdit={editMessage}
            onRegenerate={regenerate}
          />
        </section>

        <DiceTray
          onRoll={rollDice}
          disabled={socketStatus !== 'open' || isSending}
          weapons={weapons}
          hasCharacter={hasCharacter}
          onAttack={attack}
        />
      </div>

      {errorText ? <p className="error-banner">{errorText}</p> : null}

      <Composer draft={draft} onDraftChange={setDraft} onSubmit={submitDraft} canSend={canSend} />

      <FeatureModal
        feature={activeFeature}
        onClose={() => setActiveFeature(null)}
      />

      <DiaryModal
        open={diaryOpen}
        messages={messages}
        sessionId={sessionId}
        onClose={() => setDiaryOpen(false)}
      />
      <CharacterCreator
        open={creatorOpen}
        roster={roster}
        activeId={character.id}
        onSave={handleSaveCharacter}
        onSelect={handleSelectCharacter}
        onDelete={handleDeleteCharacter}
        onClose={() => setCreatorOpen(false)}
      />
    </main>
  )
}

export default App
