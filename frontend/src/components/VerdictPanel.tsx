import {
  ASSUMPTION_TONE,
  type AnalysisStatus,
  CONFIDENCE_MEANING,
  EVIDENCE_BASIS_TEXT,
  INCONCLUSIVE_REASON_TEXT,
  positionLabel,
  positionTone,
  type Verdict,
  type VerdictArgument,
  type VerdictClaimRef,
} from '../services/verdict'
import { verdictLabel } from '../services/claims'
import ErrorBanner from './ui/ErrorBanner'
import LoadingState from './ui/LoadingState'
import AnalysisTimeline from './AnalysisTimeline'

function safeUrl(url: string): string | null {
  return /^https?:\/\//i.test(url.trim()) ? url.trim() : null
}

function claimTone(verdict: string | null): string {
  switch (verdict) {
    case 'supported':
      return 'text-emerald-300 border-emerald-500/40'
    case 'contradicted':
      return 'text-rose-300 border-rose-500/40'
    case 'insufficient_evidence':
      return 'text-amber-300 border-amber-500/40'
    default:
      return 'text-gray-400 border-gray-600'
  }
}

function CitedClaim({ claim }: { claim: VerdictClaimRef }) {
  return (
    <li className="rounded-lg border border-gray-800 bg-gray-950/60 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${claimTone(claim.verdict)}`}
        >
          {claim.verdict ? verdictLabel(claim.verdict) : 'Not verified'}
        </span>
        <span className="text-xs text-gray-500">claim by {claim.agent_name}</span>
      </div>
      <p className="mt-1 text-sm text-gray-200">{claim.text}</p>
      {claim.sources.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {claim.sources.slice(0, 3).map((source) => {
            const href = safeUrl(source.url)
            return (
              <li key={source.url} className="truncate text-xs">
                {href ? (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-indigo-300 hover:underline"
                  >
                    {source.title || href}
                  </a>
                ) : (
                  <span className="text-gray-400">{source.title}</span>
                )}
                <span className="text-gray-500">
                  {' '}
                  ·{' '}
                  {source.source_type === 'google_fact_check'
                    ? `published fact-check by ${source.publisher || source.source_name}${
                        source.external_rating ? ` (external rating: ${source.external_rating})` : ''
                      }`
                    : source.source_name}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </li>
  )
}

function ArgumentList({
  title,
  items,
  empty,
  testId,
}: {
  title: string
  items: VerdictArgument[]
  empty: string
  testId: string
}) {
  return (
    <div data-testid={testId}>
      <h3 className="mb-3 text-sm font-semibold text-gray-200">{title}</h3>
      {items.length === 0 ? (
        <p className="text-sm text-gray-500">{empty}</p>
      ) : (
        <ul className="space-y-3">
          {items.map((item, index) => (
            <li key={index} className="rounded-xl border border-gray-800 bg-gray-900/60 p-4">
              <p className="text-sm text-gray-100">{item.point}</p>
              {item.agent_name && (
                <p className="mt-1 text-xs text-gray-400">
                  Argued by <span className="text-gray-300">{item.agent_name}</span>{' '}
                  (agent opinion)
                </p>
              )}
              {item.impact && (
                <p className="mt-2 text-xs text-gray-300">
                  <span className="font-semibold text-gray-400">Effect on the conclusion: </span>
                  {item.impact}
                </p>
              )}
              {item.claims.length > 0 && (
                <ul className="mt-3 space-y-2">
                  {item.claims.map((claim) => (
                    <CitedClaim key={claim.id} claim={claim} />
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const CONFIDENCE_STEPS = ['low', 'medium', 'high'] as const

export default function VerdictPanel({
  status,
  verdict,
  loading,
  generating,
  error,
  notice,
  onGenerate,
  analysis,
  info = null,
  onNavigate,
  onDownload,
  downloading = false,
}: {
  status: string
  verdict: Verdict | null
  loading: boolean
  generating: boolean
  error: string | null
  notice: string | null
  onGenerate: (regenerate: boolean) => void
  analysis: AnalysisStatus | null
  info?: string | null
  onNavigate?: (tab: string) => void
  onDownload?: () => void
  downloading?: boolean
}) {
  if (status !== 'completed') {
    return (
      <p className="text-sm text-gray-400" data-testid="verdict-pending">
        {status === 'failed'
          ? 'This debate did not finish, so it has no final verdict. Resume it from the Overview tab first.'
          : 'The final verdict becomes available once the debate has completed.'}
      </p>
    )
  }

  const snapshot = verdict?.evidence_snapshot
  const decisive = snapshot ? snapshot.supported + snapshot.contradicted : 0

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-2xl text-sm text-gray-400">
          The answer to the debate question, based on the transcript and the
          stored claim verifications. It is separate from Agent Performance:
          the best-performing agent is never assumed to be right.
        </p>
        <button
          type="button"
          onClick={() => onGenerate(verdict !== null)}
          disabled={generating || loading || analysis?.state === 'running'}
          aria-busy={generating}
          className={verdict ? 'btn-secondary' : 'btn-primary'}
          data-testid="generate-verdict"
        >
          {generating
            ? 'Verifying claims and analysing...'
            : verdict
              ? 'Regenerate verdict'
              : 'Generate final verdict'}
        </button>
      </div>

      {verdict && analysis?.state !== 'running' ? <details className="rounded-xl border border-gray-800 p-3">
        <summary className="cursor-pointer text-sm text-gray-300">{analysis?.state === 'completed' ? 'Analysis completed' : 'Analysis status'} · View saved stage timeline</summary>
        <div className="mt-3"><AnalysisTimeline analysis={analysis} /></div>
      </details> : <AnalysisTimeline analysis={analysis} />}
      {analysis?.state === 'running' && <p role="status" className="text-sm text-purple-200">Analysis already in progress — showing live progress. You can inspect evidence as it is saved.</p>}
      <div className="flex flex-wrap gap-2">
        <button className="btn-secondary text-sm" onClick={() => onNavigate?.('evidence')} disabled={!onNavigate || !(analysis?.coverage?.claims || verdict)}>View Evidence</button>
        <button className="btn-secondary text-sm" onClick={() => onNavigate?.('claims')} disabled={!onNavigate || !(analysis?.coverage?.claims || verdict)}>View Claims &amp; Verification</button>
        <button className="btn-secondary text-sm" onClick={onDownload} disabled={!onDownload || !verdict || downloading}>{downloading ? 'Preparing PDF...' : 'Download PDF Report'}</button>
      </div>

      {info && (
        <p role="status" className="alert-info" data-testid="verdict-unchanged">
          {info}
        </p>
      )}

      {error && (
        <div data-testid="verdict-error">
          <ErrorBanner title="The verdict could not be generated" message={error} />
        </div>
      )}
      {loading && <LoadingState label="Loading the stored verdict..." className="py-4" />}
      {!loading && !verdict && analysis?.state !== 'running' && notice && (
        <div className="rounded-xl border border-dashed border-gray-700 px-5 py-6 text-center" data-testid="verdict-empty">
          <p className="font-medium text-gray-200">No final verdict yet</p>
          <p className="mx-auto mt-1 max-w-lg text-sm text-gray-400">{notice}</p>
        </div>
      )}

      {verdict?.stale && (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200"
          data-testid="verdict-stale"
        >
          <span>Claims or verifications changed after this verdict was generated.</span>
          <button
            type="button"
            onClick={() => onGenerate(true)}
            disabled={generating}
            className="btn-secondary px-3 py-1.5 text-xs"
          >
            Regenerate with new evidence
          </button>
        </div>
      )}

      {verdict && (
        <>
          <div
            className={`rounded-2xl border p-6 ${positionTone(verdict.position)}`}
            data-testid="verdict-card"
          >
            <p className="text-xs font-semibold uppercase tracking-wider" data-testid="verdict-position">
              {positionLabel(verdict.position)}
            </p>
            <p className="mt-2 text-xl font-semibold leading-snug text-white" data-testid="verdict-answer">
              {verdict.answer}
            </p>
            {verdict.preferred_position && (
              <p className="mt-2 text-sm text-gray-200">
                <span className="text-gray-400">Better-supported position: </span>
                {verdict.preferred_position}
              </p>
            )}
            <p className="mt-3 text-sm leading-relaxed text-gray-300">{verdict.summary}</p>
            {verdict.inconclusive_reason && (
              <p className="mt-3 rounded-lg bg-gray-950/40 px-3 py-2 text-sm text-amber-200" data-testid="verdict-inconclusive-reason">
                {INCONCLUSIVE_REASON_TEXT[verdict.inconclusive_reason]}
              </p>
            )}
          </div>

          <section className="rounded-xl border border-gray-800 bg-gray-900/60 p-4" data-testid="verdict-takeaways">
            <h3 className="text-sm font-semibold text-gray-200">Key takeaways</h3>
            <ul className="mt-2 list-disc space-y-2 pl-4 text-sm text-gray-300"><li>{verdict.summary}</li>{verdict.supporting_arguments.slice(0, 2).map((item, index) => <li key={index}>{item.point}</li>)}</ul>
          </section>

          {(verdict.assumptions?.length || verdict.sub_verdicts?.length) ? (
            <div className="grid gap-4 md:grid-cols-2" data-testid="verdict-bias">
              {verdict.assumptions && verdict.assumptions.length > 0 && (
                <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4">
                  <h3 className="text-sm font-semibold text-gray-200">
                    Assumptions in the question
                  </h3>
                  <p className="mt-0.5 text-xs text-gray-500">
                    Checked against the evidence instead of taken as given.
                  </p>
                  <ul className="mt-3 space-y-2">
                    {verdict.assumptions.map((item) => (
                      <li key={item.assumption} className="text-sm">
                        <span className={`mr-2 rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${ASSUMPTION_TONE[item.status]}`}>
                          {item.status}
                        </span>
                        <span className="text-gray-100">{item.assumption}</span>
                        <p className="mt-0.5 text-xs text-gray-400">{item.assessment}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {verdict.sub_verdicts && verdict.sub_verdicts.length > 0 && (
                <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4">
                  <h3 className="text-sm font-semibold text-gray-200">Each part of the question</h3>
                  <ul className="mt-3 space-y-3">
                    {verdict.sub_verdicts.map((item) => (
                      <li key={item.question} className="text-sm">
                        <p className="text-gray-100">{item.question}</p>
                        <p className="mt-1">
                          <span className={`mr-2 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${positionTone(item.position)}`}>
                            {positionLabel(item.position)}
                          </span>
                          <span className="text-xs text-gray-300">{item.answer}</span>
                        </p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : null}

          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4 md:col-span-2">
              <h3 className="text-sm font-semibold text-gray-200">
                Reasoning <span className="font-normal text-gray-500">· MAVES assessment</span>
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-gray-300" data-testid="verdict-reasoning">
                {verdict.reasoning}
              </p>
            </div>
            <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4" data-testid="verdict-confidence">
              <h3 className="text-sm font-semibold text-gray-200">Confidence</h3>
              <div className="mt-2 flex gap-1" aria-hidden="true">
                {CONFIDENCE_STEPS.map((step, index) => (
                  <span
                    key={step}
                    className={`h-1.5 flex-1 rounded-full ${
                      index <= CONFIDENCE_STEPS.indexOf(verdict.confidence)
                        ? 'bg-indigo-400'
                        : 'bg-gray-700'
                    }`}
                  />
                ))}
              </div>
              <p className="mt-2 text-lg font-semibold capitalize text-white">{verdict.confidence}</p>
              <p className="mt-1 text-xs text-gray-300">{CONFIDENCE_MEANING[verdict.confidence]}</p>
              <p className="mt-1 text-xs text-gray-500">{verdict.confidence_basis}</p>
              <p className="mt-2 text-[11px] text-gray-500">
                A qualitative label capped by evidence coverage - not a calibrated probability.
              </p>
            </div>
          </div>

          {snapshot && (
            <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4" data-testid="verdict-evidence">
              <h3 className="text-sm font-semibold text-gray-200">
                Established evidence <span className="font-normal text-gray-500">· stored claim verifications</span>
              </h3>
              <dl className="mt-3 grid grid-cols-2 gap-3 text-center sm:grid-cols-5">
                {(
                  [
                    ['Supported', snapshot.supported, 'text-emerald-300'],
                    ['Partly supported', snapshot.partially_supported ?? 0, 'text-teal-300'],
                    ['Contradicted', snapshot.contradicted, 'text-rose-300'],
                    ['Insufficient', snapshot.insufficient_evidence, 'text-amber-300'],
                    ['Not verified', snapshot.unverified, 'text-gray-300'],
                    ['Sources', snapshot.evidence_sources, 'text-indigo-300'],
                  ] as const
                ).map(([label, value, tone]) => (
                  <div key={label} className="rounded-lg bg-gray-950/60 px-2 py-3">
                    <dd className={`text-xl font-semibold tabular-nums ${tone}`}>{value}</dd>
                    <dt className="mt-0.5 text-[11px] uppercase tracking-wide text-gray-500">{label}</dt>
                  </div>
                ))}
              </dl>
              {!!snapshot.non_factual_claims && <p className="mt-3 text-xs text-gray-400">{snapshot.non_factual_claims} opinions, predictions or other non-factual statements are excluded from factual verification coverage.</p>}
              {snapshot && (
                <p className="mt-3 text-xs text-gray-400" data-testid="verdict-evidence-basis">
                  Evidence basis: <span className="font-semibold capitalize text-gray-200">{verdict.evidence_basis}</span>{' '}
                  - {EVIDENCE_BASIS_TEXT[verdict.evidence_basis]}
                </p>
              )}
              {decisive === 0 && (
                <p className="mt-3 text-xs text-amber-300">
                  No claim is supported or contradicted by stored evidence yet. Extract and verify
                  claims in the Claims tab, then regenerate the verdict.
                </p>
              )}
            </div>
          )}

          <div className="grid gap-6 lg:grid-cols-2">
            <ArgumentList
              title="Strongest supporting arguments"
              items={verdict.supporting_arguments}
              empty="No supporting arguments were recorded."
              testId="verdict-supporting"
            />
            <ArgumentList
              title="Strongest counterarguments"
              items={verdict.counterarguments}
              empty="No counterarguments were recorded."
              testId="verdict-counter"
            />
          </div>

          {(verdict.limitations.length > 0 || verdict.unresolved_questions.length > 0) && (
            <div className="grid gap-4 md:grid-cols-2">
              {verdict.limitations.length > 0 && (
                <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4" data-testid="verdict-limitations">
                  <h3 className="text-sm font-semibold text-gray-200">Limitations</h3>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-300">
                    {verdict.limitations.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
              {verdict.unresolved_questions.length > 0 && (
                <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4">
                  <h3 className="text-sm font-semibold text-gray-200">Unresolved questions</h3>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-300">
                    {verdict.unresolved_questions.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <p className="text-xs text-gray-500">
            Generated {new Date(verdict.updated_at).toLocaleString()}
            {verdict.evidence_snapshot?.model ? ` by ${verdict.evidence_snapshot.model}` : ''}. LLM-generated assessments
            can be wrong; check the cited sources before relying on this conclusion.
          </p>
        </>
      )}
    </div>
  )
}
