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

export interface Species {
  id: string
  name: string
  edition: '5e' | '5.5e' | null
  source: string
  publisher: string | null
  third_party: boolean
  creature_type: string
  description: string
  character_creation_implications: string
}

export interface SpeciesListResp {
  species: Species[]
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
