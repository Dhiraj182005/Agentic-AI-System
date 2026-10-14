import { API_URL, getStoredToken } from './api'

export type WebSocketState = 'connecting' | 'connected' | 'disconnected' | 'error'

export interface DebateEvent {
  type: string
  debate_id: string
  timestamp: string
  data: Record<string, unknown> & {
    status?: string
    round_number?: number
    turn_number?: number
    message_type?: string
    message_id?: string
    content?: string
    agent?: { id: string; name: string; role: string }
    message?: string
  }
}

export type DebateEventHandlers = {
  onEvent: (event: DebateEvent) => void
  onStateChange?: (state: WebSocketState) => void
}

// Close codes sent by the backend for auth/ownership failures: retrying can
// never succeed, so the client stops instead of looping.
const PERMANENT_CLOSE_CODES = [4401, 4403, 4404]

const MAX_RECONNECT_DELAY_MS = 15000

export class DebateWebSocketClient {
  private socket: WebSocket | null = null
  private reconnectTimer: number | null = null
  private attempts = 0
  private stopped = false
  private currentState: WebSocketState = 'disconnected'

  constructor(
    private readonly debateId: string,
    private readonly handlers: DebateEventHandlers,
  ) {}

  get state(): WebSocketState {
    return this.currentState
  }

  connect(): void {
    if (
      this.socket &&
      (this.socket.readyState === WebSocket.OPEN ||
        this.socket.readyState === WebSocket.CONNECTING)
    ) {
      return
    }
    this.stopped = false
    this.setState('connecting')

    const token = getStoredToken()
    const wsBase = API_URL.replace(/^http/, 'ws')
    const url = `${wsBase}/ws/debates/${this.debateId}?token=${encodeURIComponent(
      token ?? '',
    )}`

    let socket: WebSocket
    try {
      socket = new WebSocket(url)
    } catch {
      this.setState('error')
      this.scheduleReconnect()
      return
    }
    this.socket = socket

    socket.onopen = () => {
      this.attempts = 0
      this.setState('connected')
    }
    socket.onmessage = (message: MessageEvent) => {
      try {
        const event = JSON.parse(String(message.data)) as DebateEvent
        if (event && typeof event.type === 'string') {
          this.handlers.onEvent(event)
        }
      } catch {
        // Ignore frames that are not valid events.
      }
    }
    socket.onerror = () => {
      // A close event follows; reconnection is handled there.
    }
    socket.onclose = (event: CloseEvent) => {
      this.socket = null
      if (this.stopped) {
        this.setState('disconnected')
        return
      }
      if (PERMANENT_CLOSE_CODES.includes(event.code)) {
        this.setState('error')
        return
      }
      this.setState('disconnected')
      this.scheduleReconnect()
    }
  }

  disconnect(): void {
    this.stopped = true
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    const socket = this.socket
    this.socket = null
    if (
      socket &&
      (socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING)
    ) {
      try {
        socket.close(1000, 'client disconnected')
      } catch {
        // Already closing.
      }
    }
    this.setState('disconnected')
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.reconnectTimer !== null) return
    const delay = Math.min(1000 * 2 ** this.attempts, MAX_RECONNECT_DELAY_MS)
    this.attempts += 1
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }

  private setState(state: WebSocketState): void {
    if (this.currentState === state) return
    this.currentState = state
    this.handlers.onStateChange?.(state)
  }
}
