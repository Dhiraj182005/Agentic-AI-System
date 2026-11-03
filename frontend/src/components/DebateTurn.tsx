import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { StructuredTurn, TranscriptMessage } from '../services/debates'

const TURN_STYLES: Record<string, { label: string; badge: string; border: string }> = {
  opening: {
    label: 'Opening',
    badge: 'border-indigo-500/40 bg-indigo-500/10 text-indigo-300',
    border: 'border-l-indigo-500',
  },
  rebuttal: {
    label: 'Rebuttal',
    badge: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
    border: 'border-l-amber-500',
  },
  argument: {
    label: 'Argument',
    badge: 'border-sky-500/40 bg-sky-500/10 text-sky-300',
    border: 'border-l-sky-500',
  },
  closing: {
    label: 'Closing',
    badge: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
    border: 'border-l-emerald-500',
  },
}

const PROSE =
  'text-sm leading-relaxed text-gray-200 [&_li]:my-0.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-1.5 [&_strong]:text-white [&_ul]:list-disc [&_ul]:pl-5'

function List({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  if (items.length === 0) return null
  return (
    <div>
      <p className={`text-[11px] font-semibold uppercase tracking-wide ${tone}`}>{title}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-gray-300">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

function StructuredBody({ turn, onJump }: { turn: StructuredTurn; onJump: (id: string) => void }) {
  const rebuttal = turn.rebuttal_to
  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-300">
        <span className="font-semibold text-gray-400">Position: </span>
        {turn.position}
      </p>

      {rebuttal && (
        <blockquote className="rounded-lg border border-gray-700 bg-gray-950/50 px-3 py-2 text-sm" data-testid="turn-rebuttal">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-300">
            Responding to{' '}
            {rebuttal.agent_name && rebuttal.message_id ? (
              <button
                type="button"
                onClick={() => onJump(rebuttal.message_id!)}
                className="rounded underline decoration-dotted underline-offset-2 hover:text-amber-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
              >
                {rebuttal.agent_name} · round {rebuttal.round_number}
              </button>
            ) : (
              'an earlier argument'
            )}
          </p>
          {rebuttal.argument && <p className="mt-1 italic text-gray-300">&ldquo;{rebuttal.argument}&rdquo;</p>}
        </blockquote>
      )}

      <p className="text-base font-medium leading-snug text-white" data-testid="turn-main-argument">
        {turn.main_argument}
      </p>
      <p className="text-sm leading-relaxed text-gray-300">{turn.reasoning}</p>

      {turn.concession && (
        <p className="rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm text-sky-100" data-testid="turn-concession">
          <span className="font-semibold text-sky-300">Concedes: </span>
          {turn.concession}
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <List title="Factual claims" items={turn.factual_claims} tone="text-gray-400" />
        <List
          title="Evidence cited by the agent (not yet verified)"
          items={turn.evidence_references}
          tone="text-gray-400"
        />
      </div>

      {turn.recommendation && (
        <p className="text-sm text-gray-300">
          <span className="font-semibold text-gray-400">Recommendation: </span>
          {turn.recommendation}
        </p>
      )}
      <List title="Uncertainties" items={turn.uncertainties} tone="text-amber-300/90" />
    </div>
  )
}

/**
 * One debate turn. Structured turns show their parts at a glance; the full
 * stored text stays available for auditing. Older free-text messages fall
 * back to a collapsible rendering of their content.
 */
export default function DebateTurn({
  message,
  agentRole,
}: {
  message: TranscriptMessage
  agentRole?: string
}) {
  const [expanded, setExpanded] = useState(false)
  const style = TURN_STYLES[message.message_type] ?? {
    label: message.message_type,
    badge: 'border-gray-600 text-gray-300',
    border: 'border-l-gray-600',
  }
  const turn = message.structured ?? null
  const role = agentRole ?? message.agent.role

  const jump = (id: string) => {
    const target = document.getElementById(`msg-${id}`)
    target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    target?.focus({ preventScroll: true })
  }

  return (
    <div className={`border-l-4 pl-4 ${style.border}`}>
      <header className="mb-3 flex flex-wrap items-center gap-2">
        <p className="font-semibold text-white">{message.agent.name}</p>
        {role && role.toLowerCase() !== message.agent.name.toLowerCase() && (
          <span className="rounded-full bg-gray-800 px-2 py-0.5 text-[11px] capitalize text-gray-300">
            {role.replace(/_/g, ' ')}
          </span>
        )}
        <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${style.badge}`} data-testid="turn-type">
          {style.label}
        </span>
        <span className="text-xs text-gray-500">Round {message.round_number}</span>
        {turn?.position_changed && (
          <span className="rounded-full border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 text-[11px] font-semibold text-violet-300">
            Position revised
          </span>
        )}
      </header>

      {turn ? (
        <StructuredBody turn={turn} onJump={jump} />
      ) : (
        <div className={`${PROSE} ${expanded ? '' : 'line-clamp-6'}`}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
        </div>
      )}

      <button
        type="button"
        onClick={() => setExpanded((open) => !open)}
        aria-expanded={expanded}
        className="mt-3 rounded text-xs font-medium text-indigo-300 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
      >
        {turn
          ? expanded
            ? 'Hide full response'
            : 'Show full response'
          : expanded
            ? 'Show less'
            : 'Show full message'}
      </button>
      {turn && expanded && (
        <div className={`mt-2 rounded-lg border border-gray-800 bg-gray-950/50 p-3 ${PROSE}`}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
        </div>
      )}
    </div>
  )
}
