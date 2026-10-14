import { useEffect, useState } from 'react'
import { accentFor } from './agentAccents'

const THINKING_LINES = [
  'Reviewing the topic',
  'Weighing relevant considerations',
  'Checking evidence and assumptions',
  'Structuring the response',
  'Writing the analysis',
]

export default function AgentThinking({ agent }: { agent: string }) {
  const [step, setStep] = useState(0)
  const accent = accentFor(agent)

  useEffect(() => {
    const id = window.setInterval(() => {
      setStep((prev) => (prev + 1) % THINKING_LINES.length)
    }, 2600)
    return () => window.clearInterval(id)
  }, [])

  return (
    <div
      className={`overflow-hidden rounded-2xl border border-gray-800 bg-gray-900 ring-1 ${accent.ring}`}
      role="status"
      aria-live="polite"
    >
      <header className="flex items-center gap-2.5 border-b border-gray-800 bg-gray-900/60 px-5 py-3">
        <span className={`h-2 w-2 rounded-full ${accent.dot} animate-pulse`} />
        <h3 className={`text-sm font-semibold ${accent.text}`}>
          Generating response
        </h3>
      </header>

      <div className="px-5 py-6">
        <div className="flex items-center gap-2.5">
          <span className="flex items-center gap-1" aria-hidden="true">
            <span
              className={`h-1.5 w-1.5 rounded-full ${accent.dot} animate-bounce`}
              style={{ animationDelay: '0ms' }}
            />
            <span
              className={`h-1.5 w-1.5 rounded-full ${accent.dot} animate-bounce`}
              style={{ animationDelay: '150ms' }}
            />
            <span
              className={`h-1.5 w-1.5 rounded-full ${accent.dot} animate-bounce`}
              style={{ animationDelay: '300ms' }}
            />
          </span>
          <span className="text-sm text-gray-400">{THINKING_LINES[step]}</span>
          <span className="text-sm text-gray-600">…</span>
        </div>

        <div className="mt-5 space-y-2.5" aria-hidden="true">
          {[100, 95, 88, 72].map((width, index) => (
            <div
              key={width}
              className="h-2.5 animate-pulse rounded-full bg-gray-800"
              style={{
                width: `${width}%`,
                animationDelay: `${index * 160}ms`,
              }}
            />
          ))}
        </div>
      </div>

      <div className="h-0.5 w-full bg-gray-800" aria-hidden="true">
        <div
          className={`h-full w-full bg-gradient-to-r ${accent.bar} animate-progress-sweep`}
        />
      </div>
    </div>
  )
}
