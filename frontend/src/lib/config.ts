const DEFAULT_API_URL = 'http://127.0.0.1:5000'
const DEFAULT_TOKEN = 'dev'

export function getApiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL as string | undefined
  return configured && configured.trim() ? configured : DEFAULT_API_URL
}

export function getApiToken(): string {
  const configured = import.meta.env.VITE_API_TOKEN as string | undefined
  return configured && configured.trim() ? configured : DEFAULT_TOKEN
}

export function toWebSocketUrl(sessionId: string): string {
  const base = new URL(getApiBaseUrl())
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:'
  base.pathname = `/api/v1/ws/sessions/${sessionId}`
  base.search = ''
  return base.toString()
}
