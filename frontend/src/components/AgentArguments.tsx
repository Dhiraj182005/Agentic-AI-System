import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { DebateAgent, TranscriptMessage } from '../services/debates'

/**
 * Each participant's own statements grouped together, so a reader can follow
 * one agent's line of argument without scanning the whole transcript. These
 * are agent opinions, not verified facts.
 */
export default function AgentArguments({
  agents,
  messages,
}: {
  agents: DebateAgent[]
  messages: TranscriptMessage[]
}) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-400">
        Each agent&apos;s statements in order. These are the agents&apos; own
        arguments and opinions - see Claims &amp; Verification for what the
        evidence supports.
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        {agents.map((agent) => {
          const own = messages
            .filter((message) => message.agent.id === agent.id)
            .sort((a, b) => a.round_number - b.round_number || a.turn_number - b.turn_number)
          return (
            <article
              key={agent.id}
              className="rounded-xl border border-gray-800 bg-gray-900/60 p-4"
              data-testid="agent-arguments"
            >
              <header className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="font-semibold text-white">{agent.name}</h3>
                  <p className="text-xs text-gray-400">{agent.description}</p>
                </div>
                <span className="rounded-full bg-gray-800 px-2.5 py-0.5 text-xs text-gray-300">
                  {own.length} {own.length === 1 ? 'statement' : 'statements'}
                </span>
              </header>
              {own.length === 0 ? (
                <p className="mt-3 text-sm text-gray-500">No statements stored for this agent.</p>
              ) : (
                <div className="mt-3 space-y-2">
                  {own.map((message, index) => (
                    <details
                      key={message.id}
                      open={index === 0}
                      className="group rounded-lg border border-gray-800 bg-gray-950/50"
                    >
                      <summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-gray-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500">
                        <span className="text-gray-500 group-open:hidden">+ </span>
                        <span className="hidden text-gray-500 group-open:inline">- </span>
                        Round {message.round_number} · {message.message_type.replace(/_/g, ' ')}
                      </summary>
                      <div className="px-3 pb-3 text-sm leading-relaxed text-gray-200 [&_li]:my-0.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-1.5 [&_strong]:text-white [&_ul]:list-disc [&_ul]:pl-5">
                        {message.structured ? (
                          <>
                            <p className="font-medium text-white">{message.structured.main_argument}</p>
                            <p className="mt-1 text-xs text-gray-400">
                              Position: {message.structured.position}
                            </p>
                            {message.structured.concession && (
                              <p className="mt-1 text-xs text-sky-300">
                                Concedes: {message.structured.concession}
                              </p>
                            )}
                          </>
                        ) : (
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                        )}
                      </div>
                    </details>
                  ))}
                </div>
              )}
            </article>
          )
        })}
      </div>
    </div>
  )
}
