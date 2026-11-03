export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const TOKEN_STORAGE_KEY = 'ai_debate_arena_token'

export type ApiError = { detail?: string | { msg: string }[] } | null

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function storeToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}

/**
 * Cheap local check before calling an authenticated endpoint.
 *
 * A token that is structurally broken or whose `exp` has already passed can
 * never authenticate, so the app drops it locally instead of sending a
 * request that is guaranteed to answer 401. The signature is NOT verified
 * here: the backend remains the only authority, and a token that passes this
 * check is always re-validated by the server.
 */
export function isUsableToken(token: string | null): boolean {
  if (!token) return false
  const parts = token.split('.')
  if (parts.length !== 3 || !parts[0] || !parts[1] || !parts[2]) return false
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
    const payload = JSON.parse(atob(padded)) as { exp?: unknown }
    if (typeof payload.exp !== 'number') return true // let the server decide
    return payload.exp * 1000 > Date.now()
  } catch {
    return false
  }
}

export class ApiClientError extends Error {
  status: number
  detail: string

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.detail = message
  }
}

/**
 * User-facing message for a failed API call. Keeps every page on the same
 * wording instead of re-implementing error unwrapping locally.
 */
export function apiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiClientError) return err.detail
  if (err instanceof TypeError) {
    // fetch network failure ("Failed to fetch") — never show raw text.
    return 'Cannot reach the server. Check your connection and try again.'
  }
  return fallback
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  authenticated = false,
): Promise<T> {
  const headers = new Headers(options.headers || {})
  headers.set('Content-Type', 'application/json')

  if (authenticated) {
    const token = getStoredToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  })

  if (res.status === 401 && authenticated) {
    clearStoredToken()
    window.dispatchEvent(new Event('auth:unauthorized'))
  }

  if (!res.ok) {
    let detail = 'Request failed'
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (Array.isArray(body?.detail)) {
        detail = body.detail.map((d: { msg?: string }) => d.msg || '').join(', ')
      }
    } catch {
      /* ignore parse errors */
    }
    throw new ApiClientError(res.status, detail)
  }

  return res.json() as Promise<T>
}

/**
 * Fetch a binary resource (e.g. the PDF report) with the same auth and 401
 * handling as the JSON client. Errors keep the ApiClientError contract so
 * callers can reuse `apiErrorMessage`. The Content-Disposition filename, when
 * present, is returned alongside the blob so the save dialog can use the
 * server-provided name.
 */
export async function requestBlob(
  path: string,
  authenticated = true,
): Promise<{ blob: Blob; filename: string | null }> {
  const headers = new Headers()

  if (authenticated) {
    const token = getStoredToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }

  const res = await fetch(`${API_URL}${path}`, {
    method: 'GET',
    headers,
  })

  if (res.status === 401 && authenticated) {
    clearStoredToken()
    window.dispatchEvent(new Event('auth:unauthorized'))
  }

  if (!res.ok) {
    let detail = 'Request failed'
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (Array.isArray(body?.detail)) {
        detail = body.detail.map((d: { msg?: string }) => d.msg || '').join(', ')
      }
    } catch {
      /* ignore parse errors */
    }
    throw new ApiClientError(res.status, detail)
  }

  const disposition = res.headers.get('Content-Disposition') ?? ''
  const match = /filename="?([^";]+)"?/i.exec(disposition)

  return { blob: await res.blob(), filename: match ? match[1] : null }
}

export default request
