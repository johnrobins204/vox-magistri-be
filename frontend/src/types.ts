import type { AbilityKey } from './lib/character'

export type MessageStatus = 'queued' | 'running' | 'completed' | 'error' | 'cancelled'

/** Snake_case wire shape of the character sent on session create (ADR-0008 D4). */
export interface CharacterIn {
  id: string
  name: string
  lineage: string
  species_id: string | null
  char_class: string
  level: number
  hp_current: number
  hp_max: number
  ac: number
  abilities: Record<AbilityKey, number>
  conditions: string[]
}

export type Role = 'user' | 'assistant' | 'system'

export interface Message {
  id: string
  client_message_id: string | null
  role: Role | null
  content: string | null
  status: MessageStatus
  canon: boolean
  meta: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

/** Superseded content kept in `meta.revisions` (ADR-0011). */
export interface MessageRevision {
  content: string
  replaced_at: string
  reason: 'edit' | 'regenerate'
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

export interface Weapon {
  id: string
  name: string
  edition: '5e' | '5.5e' | null
  third_party: boolean
  damage_dice: string | null
  damage_type: string | null
  properties: string[]
}

export interface WeaponListResp {
  weapons: Weapon[]
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
