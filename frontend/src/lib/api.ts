import { getApiBaseUrl, getApiToken } from './config'
import { toCharacterIn, type Character } from './character'
import type {
  Message,
  MessageListResp,
  SessionCreateResp,
  Species,
  SpeciesListResp,
} from '../types'

function authHeaders(): HeadersInit {
  return {
    Authorization: `Bearer ${getApiToken()}`,
    'Content-Type': 'application/json',
  }
}

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed: ${response.status}`
    try {
      // FastAPI 422 bodies carry an array here; only a string is a readable message.
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string' && body.detail) {
        detail = body.detail
      }
    } catch {
      // Ignore parse errors and keep the default message.
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

export async function createSession(character?: Character | null): Promise<SessionCreateResp> {
  const url = `${getApiBaseUrl()}/api/v1/sessions`
  const init: RequestInit = character
    ? {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character: toCharacterIn(character) }),
      }
    : { method: 'POST' }
  const response = await fetch(url, init)
  return parseJson<SessionCreateResp>(response)
}

export async function listMessages(sessionId: string): Promise<MessageListResp> {
  const url = `${getApiBaseUrl()}/api/v1/sessions/${sessionId}/messages`
  const response = await fetch(url, {
    headers: authHeaders(),
  })
  // Backend currently returns a bare array; SPEC-0010 will wrap it in {"messages": [...]}.
  const body = await parseJson<MessageListResp | MessageListResp['messages']>(response)
  return Array.isArray(body) ? { messages: body } : body
}

export async function updateMessage(
  sessionId: string,
  messageId: string,
  changes: { content?: string; canon?: boolean },
): Promise<Message> {
  const url = `${getApiBaseUrl()}/api/v1/sessions/${sessionId}/messages/${messageId}`
  const response = await fetch(url, {
    method: 'PATCH',
    headers: authHeaders(),
    body: JSON.stringify(changes),
  })
  return parseJson<Message>(response)
}

export async function getIntelStatus(): Promise<{
  model_loaded: boolean
  queue_position: number | null
  estimated_wait_seconds: number | null
}> {
  const url = `${getApiBaseUrl()}/api/v1/intel/status`
  const response = await fetch(url)
  return parseJson(response)
}

export async function getSpecies(): Promise<Species[]> {
  const url = `${getApiBaseUrl()}/api/v1/reference/species`
  const response = await fetch(url)
  const body = await parseJson<SpeciesListResp>(response)
  return body.species
}
