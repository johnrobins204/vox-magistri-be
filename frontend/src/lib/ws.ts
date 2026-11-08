import { toWebSocketUrl } from './config'
import type { WsEvent } from '../types'

interface SessionSocketHandlers {
  onEvent: (event: WsEvent) => void
  onOpen: () => void
  onClose: () => void
  onError: (error: string) => void
}

export interface SessionSocket {
  sendUserMessage: (text: string, clientMessageId: string, narrativeOnly: boolean) => void
  sendStatus: () => void
  sendRegenerate: (messageId: string) => void
  close: () => void
}

export function openSessionSocket(
  sessionId: string,
  handlers: SessionSocketHandlers,
): SessionSocket {
  const socket = new WebSocket(toWebSocketUrl(sessionId))

  socket.addEventListener('open', () => handlers.onOpen())

  socket.addEventListener('close', () => handlers.onClose())

  socket.addEventListener('error', () => {
    handlers.onError('WebSocket error')
  })

  socket.addEventListener('message', (event) => {
    try {
      const payload = JSON.parse(event.data as string) as WsEvent
      handlers.onEvent(payload)
    } catch {
      handlers.onError('Invalid event payload from server')
    }
  })

  return {
    sendUserMessage: (text: string, clientMessageId: string, narrativeOnly: boolean) => {
      socket.send(
        JSON.stringify({
          action: 'user_message',
          text,
          client_message_id: clientMessageId,
          narrative_only: narrativeOnly,
        }),
      )
    },
    sendStatus: () => {
      socket.send(
        JSON.stringify({
          action: 'status',
        }),
      )
    },
    sendRegenerate: (messageId: string) => {
      socket.send(
        JSON.stringify({
          action: 'regenerate',
          message_id: messageId,
        }),
      )
    },
    close: () => {
      socket.close()
    },
  }
}
