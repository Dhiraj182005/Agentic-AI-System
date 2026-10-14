import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { AgentTestResponse } from '../services/agents'
import { accentFor } from './agentAccents'

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(value)
    } catch {
      return
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2000)
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="rounded-md border border-gray-700 bg-gray-800 px-2.5 py-1 text-xs text-gray-300 transition-colors hover:border-gray-600 hover:text-white"
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

export default function AgentMessage({ result }: { result: AgentTestResponse }) {
  const accent = accentFor(result.agent)

  return (
    <article
      className={`animate-fade-in-up overflow-hidden rounded-2xl border border-gray-800 bg-gray-900 ring-1 ${accent.ring}`}
    >
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 bg-gray-900/60 px-5 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className={`h-2 w-2 shrink-0 rounded-full ${accent.dot}`} />
          <h3 className={`truncate text-sm font-semibold ${accent.text}`}>
            {result.role}
          </h3>
          <code className="shrink-0 rounded bg-gray-800 px-1.5 py-0.5 font-mono text-xs text-gray-400">
            {result.agent}
          </code>
        </div>

        <div className="flex items-center gap-3">
          <span className="hidden font-mono text-xs text-gray-500 sm:inline">
            {result.provider} / {result.model}
          </span>
          <CopyButton value={result.response} />
        </div>
      </header>

      <div className="max-h-[32rem] overflow-y-auto px-5 py-4">
        <div className="agent-prose animate-fade-in text-sm leading-relaxed text-gray-300 [animation-delay:80ms]">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              h1: ({ children }) => (
                <h1 className="mb-3 mt-6 text-lg font-semibold text-white first:mt-0">
                  {children}
                </h1>
              ),
              h2: ({ children }) => (
                <h2 className="mb-2.5 mt-6 text-base font-semibold text-white first:mt-0">
                  {children}
                </h2>
              ),
              h3: ({ children }) => (
                <h3 className="mb-2 mt-5 text-sm font-semibold text-gray-100 first:mt-0">
                  {children}
                </h3>
              ),
              h4: ({ children }) => (
                <h4 className="mb-2 mt-4 text-sm font-semibold text-gray-200 first:mt-0">
                  {children}
                </h4>
              ),
              p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
              ul: ({ children }) => (
                <ul className="mb-3 list-disc space-y-1.5 pl-5 marker:text-gray-600">
                  {children}
                </ul>
              ),
              ol: ({ children }) => (
                <ol className="mb-3 list-decimal space-y-1.5 pl-5 marker:text-gray-600">
                  {children}
                </ol>
              ),
              li: ({ children }) => <li className="pl-1">{children}</li>,
              a: ({ children, href }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-indigo-400 underline decoration-indigo-400/40 underline-offset-2 hover:text-indigo-300"
                >
                  {children}
                </a>
              ),
              strong: ({ children }) => (
                <strong className="font-semibold text-gray-100">{children}</strong>
              ),
              em: ({ children }) => <em className="text-gray-200 italic">{children}</em>,
              del: ({ children }) => (
                <del className="text-gray-500 line-through">{children}</del>
              ),
              blockquote: ({ children }) => (
                <blockquote className="mb-3 border-l-2 border-gray-700 pl-4 text-gray-400 italic">
                  {children}
                </blockquote>
              ),
              hr: () => <hr className="my-5 border-gray-800" />,
              code: ({ children, className }) => {
                const isBlock = typeof className === 'string' && className.includes('language-')
                if (isBlock) {
                  return (
                    <code className="block overflow-x-auto rounded-lg border border-gray-800 bg-gray-950 p-4 font-mono text-xs text-gray-300">
                      {children}
                    </code>
                  )
                }
                return (
                  <code className="rounded bg-gray-800 px-1.5 py-0.5 font-mono text-xs text-indigo-300">
                    {children}
                  </code>
                )
              },
              pre: ({ children }) => (
                <pre className="mb-3 overflow-x-auto rounded-lg border border-gray-800 bg-gray-950 p-4">
                  {children}
                </pre>
              ),
              table: ({ children }) => (
                <div className="mb-4 overflow-x-auto rounded-lg border border-gray-800">
                  <table className="w-full border-collapse text-left text-xs">
                    {children}
                  </table>
                </div>
              ),
              thead: ({ children }) => (
                <thead className="bg-gray-800/80">{children}</thead>
              ),
              th: ({ children }) => (
                <th className="border-b border-gray-700 px-3 py-2 font-semibold text-gray-100">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="border-b border-gray-800 px-3 py-2 align-top text-gray-300">
                  {children}
                </td>
              ),
              tr: ({ children }) => (
                <tr className="even:bg-gray-800/20">{children}</tr>
              ),
            }}
          >
            {result.response}
          </ReactMarkdown>
        </div>
      </div>
    </article>
  )
}
