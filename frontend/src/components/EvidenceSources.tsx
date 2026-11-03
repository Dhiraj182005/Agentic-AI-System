import type {
  ClaimVerification,
  EvidenceItem,
  FactCheckStatus,
} from '../services/claims'
import { verdictLabel } from '../services/claims'

// Only http(s) links are opened; anything else renders as plain text.
function safeExternalUrl(url: string): string | null {
  return /^https?:\/\//i.test(url) ? url : null
}

function formatDate(value: string | null): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString()
}

function SourceLink({ url, children }: { url: string; children: React.ReactNode }) {
  const href = safeExternalUrl(url)
  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="break-words text-sm font-medium text-indigo-300 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
    >
      {children}
    </a>
  ) : (
    <span className="break-words text-sm font-medium text-gray-200">{children}</span>
  )
}

const FACT_CHECK_NOTICE: Record<Exclude<FactCheckStatus, 'matched'>, { text: string; warn: boolean }> = {
  no_match: { text: 'No matching published fact-check found.', warn: false },
  unavailable: {
    text: 'Published fact-check search is not configured (Google Fact Check API key missing). Web sources are still used.',
    warn: true,
  },
  failed: {
    text: 'Published fact-check search failed (service unavailable, quota or timeout). Web sources are still used; it is retried on the next analysis run.',
    warn: true,
  },
}

/** Evidence for one claim, split by source type: published fact-checks
 * (Google Fact Check Tools) and web search results (Tavily). The MAVES
 * verification status is shown separately from any external rating. */
export default function EvidenceSources({
  items,
  factCheckStatus,
  verification,
}: {
  items: EvidenceItem[]
  factCheckStatus: FactCheckStatus | null | undefined
  verification: ClaimVerification | undefined
}) {
  const factChecks = items.filter((item) => item.source_type === 'google_fact_check')
  const web = items.filter((item) => item.source_type !== 'google_fact_check')
  const notice =
    factChecks.length === 0 && factCheckStatus && factCheckStatus !== 'matched'
      ? FACT_CHECK_NOTICE[factCheckStatus]
      : null

  return (
    <div className="mt-3 space-y-3" data-testid="evidence-list">
      <p className="text-xs text-gray-400" data-testid="maves-status">
        <span className="font-semibold text-gray-300">MAVES verification: </span>
        {verification
          ? `${verdictLabel(verification.verdict)} (${verification.confidence} confidence)`
          : 'Not verified yet'}
      </p>

      <div data-testid="fact-check-section">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
          Published fact-checks · Google Fact Check
        </p>
        {notice && (
          <p
            className={`mt-1 text-xs ${notice.warn ? 'text-amber-300' : 'text-gray-400'}`}
            data-testid={notice.warn ? 'fact-check-warning' : 'fact-check-empty'}
          >
            {notice.text}
          </p>
        )}
        {!notice && factChecks.length === 0 && (
          <p className="mt-1 text-xs text-gray-500">Not searched yet.</p>
        )}
        {factChecks.length > 0 && (
          <ul className="mt-2 space-y-2">
            {factChecks.map((item) => (
              <li
                key={item.id}
                data-testid="fact-check-item"
                className="rounded-lg border border-sky-900/60 bg-sky-950/20 px-3 py-2"
              >
                <SourceLink url={item.url}>{item.title}</SourceLink>
                <p className="mt-0.5 text-xs text-gray-400">
                  {item.publisher || item.source_name}
                  {formatDate(item.review_date) ? ` · reviewed ${formatDate(item.review_date)}` : ''}
                </p>
                <p className="mt-1 text-xs text-gray-300">
                  <span className="text-gray-400">External fact-check rating: </span>
                  <span className="font-semibold" data-testid="external-rating">
                    {item.external_rating || 'No rating given'}
                  </span>
                </p>
                {item.claim_reviewed && (
                  <p className="mt-1 text-xs text-gray-400">
                    Claim they reviewed{item.claimant ? ` (by ${item.claimant})` : ''}: &quot;
                    {item.claim_reviewed}&quot;
                  </p>
                )}
                {item.relevance_score !== null && (
                  <p className="mt-0.5 text-xs text-gray-500">
                    Evidence relevance (word overlap with this claim):{' '}
                    {Math.round(item.relevance_score * 100)}%
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
        {factChecks.length > 0 && (
          <p className="mt-1 text-xs text-gray-500">
            External ratings are the publisher&apos;s view of the claim they reviewed, which may
            differ from this claim. MAVES weighs them as evidence, not as its verdict.
          </p>
        )}
      </div>

      <div data-testid="web-section">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
          Web sources · Tavily search
        </p>
        {web.length === 0 ? (
          <p className="mt-1 text-xs text-gray-400" data-testid="evidence-empty">
            No web sources found for this claim.
          </p>
        ) : (
          <ul className="mt-2 space-y-2">
            {web.map((item) => (
              <li
                key={item.id}
                data-testid="evidence-item"
                className="rounded-lg border border-gray-800 bg-gray-900/60 px-3 py-2"
              >
                <SourceLink url={item.url}>{item.title}</SourceLink>
                <p className="mt-0.5 text-xs text-gray-400">
                  {item.source_name} <span className="break-all">({item.url})</span>
                </p>
                {item.snippet && <p className="mt-1 text-xs text-gray-400">{item.snippet}</p>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
