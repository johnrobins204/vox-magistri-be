import type { Message, MessageRevision } from '../types'

/** A message is canon unless it was explicitly marked not canon (ADR-0011). */
export function isCanon(message: Message): boolean {
  return message.canon !== false
}

/** Superseded versions recorded in `meta.revisions`; empty when absent or malformed. */
export function revisionsOf(message: Message): MessageRevision[] {
  const revisions = message.meta?.revisions
  return Array.isArray(revisions) ? (revisions as MessageRevision[]) : []
}

export function isEdited(message: Message): boolean {
  return revisionsOf(message).length > 0
}

/** Only completed assistant replies can be edited, regenerated, or excluded from canon. */
export function canCorrect(message: Message): boolean {
  return message.role === 'assistant' && message.status === 'completed'
}
