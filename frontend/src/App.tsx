import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createSession, getIntelStatus, listMessages } from './lib/api'
import { openSessionSocket, type SessionSocket } from './lib/ws'
import { CharacterPanel } from './components/CharacterPanel'
import { Composer } from './components/Composer'
import { DiceTray } from './components/DiceTray'
import { NarrativeLog } from './components/NarrativeLog'
import { SceneBar } from './components/SceneBar'
import type { Message, WsEvent } from './types'

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
  const socketRef = useRef<SessionSocket | null>(null)

  const canSend = useMemo(
    () => socketStatus === 'open' && draft.trim().length > 0 && !isSending,
    [socketStatus, draft, isSending],
  )

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

        const session = await createSession()
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

  const startNewSession = async () => {
    try {
      setErrorText('')
      setMessages([])
      const session = await createSession()
      localStorage.setItem(SESSION_STORAGE_KEY, session.session_id)
      setSessionId(session.session_id)
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : 'Failed to create a session')
    }
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
        onNewSession={startNewSession}
        onRefreshStatus={askStatus}
      />

      <div className="board-grid">
        <CharacterPanel />

        <section className="panel thread">
          <NarrativeLog messages={messages} isSending={isSending} />
        </section>

        <DiceTray onRoll={rollDice} disabled={socketStatus !== 'open' || isSending} />
      </div>

      {errorText ? <p className="error-banner">{errorText}</p> : null}

      <Composer draft={draft} onDraftChange={setDraft} onSubmit={submitDraft} canSend={canSend} />
    </main>
  )
}

export default App
