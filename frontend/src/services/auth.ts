import request from './api'

export interface User {
  id: string
  email: string
  created_at: string
  is_demo?: boolean
}

/** Demo credentials advertised by the backend; disabled unless configured. */
export interface DemoLogin {
  enabled: boolean
  email: string | null
  password: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export async function register(email: string, password: string): Promise<User> {
  const res = await request<User>('/api/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  return res
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const res = await request<TokenResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  return res
}

export async function getDemoLogin(): Promise<DemoLogin> {
  return request<DemoLogin>('/api/v1/auth/demo')
}

export async function fetchCurrentUser(): Promise<User> {
  return request<User>('/api/v1/auth/me', {}, true)
}
