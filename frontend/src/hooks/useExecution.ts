import { useCallback, useEffect, useRef, useState } from 'react'
import { getExecution, type ExecutionSnapshot } from '../services/execution'
import type { WebSocketState } from '../services/websocket'

export default function useExecution(id: string | undefined, connection: WebSocketState) {
  const [execution, setExecution] = useState<ExecutionSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const current = useRef(id)
  current.current = id
  const request = useRef(0)
  const timer = useRef<number | null>(null)
  const refresh = useCallback(async () => {
    if (!id) return
    const sequence = ++request.current
    try {
      const next = await getExecution(id)
      if (id !== current.current || sequence !== request.current || next.debate_id !== id) return
      setExecution(prev => prev && prev.sequence > next.sequence ? prev : next)
      setError(null)
    } catch {
      if (id === current.current) setError('Execution progress could not be refreshed. Saved work is retained.')
    }
  }, [id])
  const notify = useCallback(() => {
    if (timer.current !== null) return
    timer.current = window.setTimeout(() => { timer.current = null; void refresh() }, 120)
  }, [refresh])
  useEffect(() => () => { if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null } }, [id])
  useEffect(() => { setExecution(null); setError(null); void refresh() }, [refresh])
  const active = execution && ['starting', 'running', 'analyzing', 'generating_verdict'].includes(execution.execution_state)
  useEffect(() => {
    if (!active || connection === 'connected') return
    const timer = window.setInterval(() => void refresh(), 8000)
    return () => window.clearInterval(timer)
  }, [active, connection, refresh])
  return { execution, refresh, notify, error }
}
