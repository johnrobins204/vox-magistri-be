import { getApiBaseUrl, getApiToken } from './config'
import type { MessageListResp, SessionCreateResp } from '../types'

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
      const body = (await response.json()) as { detail?: string }
      if (body.detail) {
        detail = body.detail
      }
    } catch {
      // Ignore parse errors and keep the default message.
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

export async function createSession(): Promise<SessionCreateResp> {
  const url = `${getApiBaseUrl()}/api/v1/sessions`
  const response = await fetch(url, {
    method: 'POST',
  })
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

export async function getIntelStatus(): Promise<{
  model_loaded: boolean
  queue_position: number | null
  estimated_wait_seconds: number | null
}> {
  const url = `${getApiBaseUrl()}/api/v1/intel/status`
  const response = await fetch(url)
  return parseJson(response)
}
