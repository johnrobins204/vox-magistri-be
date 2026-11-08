import type { Message, MessageKind } from '../types'

const ADMIN: MessageKind = 'admin'

/** Admin rows are classified by the server only (`meta.kind`), never by text (ADR-0015). */
export function isAdmin(message: Message): boolean {
  return message.meta?.kind === ADMIN
}

/** Maps each user message id to its reply via `meta.reply_to`. */
export function replyIndex(messages: Message[]): Map<string, Message> {
  const index = new Map<string, Message>()
  for (const message of messages) {
    const replyTo = message.meta?.reply_to
    if (typeof replyTo === 'string') {
      index.set(replyTo, message)
    }
  }
  return index
}
