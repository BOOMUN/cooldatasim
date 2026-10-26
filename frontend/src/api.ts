import { serverErrorMessage } from './localization'
export { statusLabel, dateTime } from './localization'

let csrfToken = ''

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export function setCsrf(token: string) { csrfToken = token }
export function clearSession() { csrfToken = '' }

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method, credentials: 'same-origin',
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(method !== 'GET' && csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  const data = response.status === 204 ? null : await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') {
      clearSession()
      window.dispatchEvent(new CustomEvent('session-expired'))
    }
    const detail = data?.detail
    throw new ApiError(response.status, serverErrorMessage(detail, response.status))
  }
  return data as T
}

export function errorMessage(error: unknown): string {
  return error instanceof TypeError ? '無法連接服務，請確認本機服務正在運行。' : error instanceof Error && /\p{Script=Han}/u.test(error.message) ? error.message : '操作失敗，請重試或查看服務狀態。'
}

export function safeLink(value?: string | null): string | undefined {
  if (!value) return undefined
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined } catch { return undefined }
}
