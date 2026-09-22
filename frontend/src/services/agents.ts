const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const TOKEN_STORAGE_KEY = 'ai_debate_arena_token'

export type ApiError = { detail?: string | { msg: string }[] } | null

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export interface AgentTestResponse {
  agent: string
  role: string
  response: string
  provider: string
  model: string
}

export async function testAgent(
  agent: string,
  message: string,
): Promise<AgentTestResponse> {
  const token = getStoredToken()
  const res = await fetch(`${API_URL}/api/v1/agents/test`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ agent, message }),
  })

  if (!res.ok) {
    let detail = 'Request failed'
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* ignore parse errors */
    }
    throw new Error(detail)
  }

  return (await res.json()) as AgentTestResponse
}