import { toWebSocketUrl } from './config'
import type { WsEvent } from '../types'

interface SessionSocketHandlers {
  onEvent: (event: WsEvent) => void
  onOpen: () => void
  onClose: () => void
  onError: (error: string) => void
}

export interface SessionSocket {
  sendUserMessage: (text: string, clientMessageId: string) => void
  sendStatus: () => void
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
    sendUserMessage: (text: string, clientMessageId: string) => {
      socket.send(
        JSON.stringify({
          action: 'user_message',
          text,
          client_message_id: clientMessageId,
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
    close: () => {
      socket.close()
    },
  }
}
