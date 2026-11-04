import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules() })

describe('API base configuration', () => {
  it('uses localhost only in development without a configured URL', async () => {
    vi.resetModules(); vi.stubEnv('DEV', true); vi.stubEnv('VITE_API_URL', '')
    expect((await import('../services/api')).API_URL).toBe('http://localhost:8000')
  })
  it('rejects missing production configuration rather than contacting localhost', async () => {
    vi.resetModules(); vi.stubEnv('DEV', false); vi.stubEnv('VITE_API_URL', '')
    await expect(import('../services/api')).rejects.toThrow('VITE_API_URL must be configured')
  })
  it('uses the production origin for login, demo login and secure WebSockets', async () => {
    vi.resetModules(); vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_API_URL', 'https://maves-backend.onrender.com/')
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetcher)
    const auth = await import('../services/auth')
    await auth.login('qa@example.com', 'test-password')
    await auth.getDemoLogin()
    expect(fetcher.mock.calls.map(call => call[0])).toEqual([
      'https://maves-backend.onrender.com/api/v1/auth/login',
      'https://maves-backend.onrender.com/api/v1/auth/demo',
    ])
    const socket = vi.fn(function (_url: string) { return { readyState: 0, close: vi.fn() } })
    vi.stubGlobal('WebSocket', socket)
    const { DebateWebSocketClient } = await import('../services/websocket')
    const client = new DebateWebSocketClient('debate-id', { onEvent: vi.fn() })
    client.connect()
    expect(socket.mock.calls[0][0]).toMatch(/^wss:\/\/maves-backend\.onrender\.com\/ws\/debates\/debate-id\?token=/)
    client.disconnect()
  })
})
