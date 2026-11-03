import type { AnalysisStatus } from '../services/verdict'

export const ANALYSIS_STAGES = [
  ['transcript', 'Debate transcript', 'Loading the saved debate transcript...'],
  ['extraction', 'Factual claims', 'Extracting and classifying claims from agent arguments...'],
  ['fact_check', 'Published fact-checks', 'Searching Google for previously published fact-checks...'],
  ['retrieval', 'Web evidence', 'Retrieving sources through Tavily or reusing stored evidence...'],
  ['verification', 'Claim verification', 'Comparing retrieved sources with extracted factual claims...'],
  ['fallacy', 'Fallacy analysis', 'Checking each participant’s reasoning for logical fallacies...'],
  ['evaluation', 'Argument quality', 'Evaluating arguments against the published rubric...'],
  ['performance', 'Agent performance', 'Assessing all participants, separately from the factual verdict...'],
  ['verdict', 'Judge AI verdict', 'Judge AI is weighing the persisted arguments and evidence...'],
  ['publishing', 'Save verdict', 'Saving the verdict before publishing the result...'],
] as const

export default function AnalysisTimeline({ analysis }: { analysis: AnalysisStatus | null }) {
  const stages = analysis?.stages ?? {}
  const complete = Object.values(stages).filter(s => s.state === 'completed').length
  const active = ANALYSIS_STAGES.find(([key]) => key === analysis?.current_stage)
  const running = analysis?.state === 'running'
  const coverage = analysis?.coverage
  return <section className="analysis-workspace rounded-2xl border border-purple-500/25 bg-gray-950/60 p-5" data-testid="analysis-timeline" aria-live="polite">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-[11px] font-semibold uppercase tracking-[.2em] text-purple-300">Analysis workspace</p>
        <h3 className="mt-1 text-lg font-semibold text-white">{running ? 'Analyzing debate...' : analysis?.state === 'completed' ? 'Analysis completed' : analysis?.state === 'partial' ? 'Analysis partially completed' : analysis?.state === 'failed' ? 'Analysis needs attention' : 'Ready for analysis'}</h3>
        <p className="mt-1 text-sm text-gray-400">{running ? active?.[2] ?? 'Waiting for the next persisted progress update...' : 'Stage status comes from saved backend operations. Missing work can be retried.'}</p>
      </div><span className="rounded-full border border-gray-700 px-3 py-1 text-xs text-gray-300">{complete} / {ANALYSIS_STAGES.length} stages completed</span>
    </div>
    {running && <div className="mt-4 flex items-center gap-2 text-xs text-purple-300" role="status"><span className="activity-spinner" aria-hidden="true" />{active?.[1] ?? 'Processing'} — task completion time is unknown.</div>}
    <dl className="my-5 grid grid-cols-3 gap-2">
      {([['Claims extracted', coverage?.claims ?? analysis?.claims_total ?? 0], ['Claims verified', coverage?.claims_verified ?? (analysis?.verified ?? 0) + (analysis?.already_verified ?? 0)], ['Evidence sources', coverage ? coverage.google_fact_checks + coverage.tavily_sources : null]] as const).map(([name, value]) => <div key={name} className="rounded-lg bg-gray-900 p-3"><dd className="text-xl font-semibold tabular-nums text-gray-100">{value ?? '—'}</dd><dt className="mt-1 text-[11px] text-gray-400">{name}</dt></div>)}
    </dl>
    <ol className="grid gap-2 md:grid-cols-2">
      {ANALYSIS_STAGES.map(([key, title, description], index) => {
        const stage = stages[key]
        const state = stage?.state ?? 'pending'
        return <li key={key} className={`stage-row rounded-xl border p-3 ${state === 'running' ? 'border-purple-500/60 bg-purple-500/10' : state === 'failed' ? 'border-amber-700/60 bg-amber-950/20' : 'border-gray-800 bg-gray-900/40'}`} aria-current={state === 'running' ? 'step' : undefined}>
          <div className="flex items-center justify-between gap-2"><p className="text-sm font-medium text-gray-200"><span className="mr-2 text-xs text-gray-500">{String(index + 1).padStart(2, '0')}</span>{title}</p><span className={`text-[11px] capitalize ${state === 'completed' ? 'text-emerald-300' : state === 'running' ? 'text-purple-300' : state === 'failed' ? 'text-amber-300' : 'text-gray-500'}`}>{state}</span></div>
          {state === 'running' && <p className="mt-2 text-xs text-gray-400">{description}</p>}
          {stage?.summary && <p className="mt-2 text-xs text-gray-400">{Object.entries(stage.summary).filter(([, value]) => typeof value === 'number' || typeof value === 'string').slice(0, 5).map(([name, value]) => `${name.replace(/_/g, ' ')}: ${value}`).join(' · ')}</p>}
          {stage?.error && <p className="mt-2 text-xs text-amber-200" role="alert">{stage.error}</p>}
          {(stage?.started_at || stage?.finished_at) && <p className="mt-2 text-[10px] tabular-nums text-gray-500">{stage.started_at ? `Started ${new Date(stage.started_at).toLocaleTimeString()}` : ''}{stage.finished_at ? ` · Finished ${new Date(stage.finished_at).toLocaleTimeString()}` : ''}</p>}
        </li>
      })}
    </ol>
  </section>
}
