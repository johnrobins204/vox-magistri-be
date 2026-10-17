export type MessageStatus = 'queued' | 'running' | 'completed' | 'error' | 'cancelled'

export type Role = 'user' | 'assistant' | 'system'

export interface Message {
  id: string
  client_message_id: string | null
  role: Role | null
  content: string | null
  status: MessageStatus
  meta: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface SessionCreateResp {
  session_id: string
  capabilities: Record<string, unknown>
}

export interface MessageListResp {
  messages: Message[]
}

export interface WsSnapshotEvent {
  type: 'snapshot'
  session_id: string
  entries: Message[]
  snapshot_at: string
}

export interface WsEntryEvent {
  type: 'entry'
  entry: Message
}

export interface WsDoneEvent {
  type: 'done'
  message_id: string
  reply_id: string
}

export interface WsStatusEvent {
  type: 'status'
  queue_position: number | null
  estimated_wait_seconds: number | null
}

export interface WsErrorEvent {
  type: 'error'
  message: string
  message_id?: string
}

export type WsEvent =
  | WsSnapshotEvent
  | WsEntryEvent
  | WsDoneEvent
  | WsStatusEvent
  | WsErrorEvent
