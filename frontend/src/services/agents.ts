import request from './api'

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
  return request<AgentTestResponse>(
    '/api/v1/agents/test',
    { method: 'POST', body: JSON.stringify({ agent, message }) },
    true,
  )
}
