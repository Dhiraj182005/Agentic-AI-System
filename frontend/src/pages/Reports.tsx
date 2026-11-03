import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage } from '../services/api'
import { listDebates, type Debate } from '../services/debates'
import { useReportDownload } from '../hooks/useReportDownload'
import PageShell from '../components/ui/PageShell'
import PageHeader from '../components/ui/PageHeader'
import ErrorBanner from '../components/ui/ErrorBanner'
import LoadingState from '../components/ui/LoadingState'
import StatusBadge from '../components/ui/StatusBadge'

// Debates that have finished running (successfully or not) have something to
// report. Pending and running debates are left out until they finish.
const REPORTABLE = new Set(['completed', 'failed', 'cancelled'])

export default function Reports() {
  const [debates, setDebates] = useState<Debate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const { download, downloadingId, error: downloadError } = useReportDownload()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await listDebates()
      setDebates(
        response.items
          .filter((debate) => REPORTABLE.has(debate.status))
          .sort(
            (a, b) =>
              Date.parse(b.completed_at ?? b.created_at) -
              Date.parse(a.completed_at ?? a.created_at),
          ),
      )
    } catch (err) {
      setError(apiErrorMessage(err, 'Unable to load reports.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <PageShell>
      <PageHeader
        title="Reports"
        description="Download a PDF report for any finished debate. Reports are built from stored results only; debates without a final judgment are clearly marked as partial inside the PDF."
      />

      {error && (
        <div className="mb-6">
          <ErrorBanner
            title="Could not load reports"
            message={error}
            onRetry={() => void load()}
          />
        </div>
      )}

      {loading && <LoadingState label="Loading reports..." />}

      {!loading && !error && debates.length === 0 && (
        <div className="card text-center">
          <p className="font-medium text-gray-200">No reports available yet</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-gray-400">
            A report becomes available once a debate has finished running. Run
            a debate, then judge it to include the final conclusion.
          </p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <Link to="/debates/new" className="btn-primary">
              Start a debate
            </Link>
            <Link to="/debates" className="btn-secondary">
              My Debates
            </Link>
          </div>
        </div>
      )}

      {!loading && debates.length > 0 && (
        <ul className="space-y-3">
          {debates.map((debate) => {
            const busy = downloadingId === debate.id
            const failed = downloadError?.id === debate.id
            return (
              <li
                key={debate.id}
                className="rounded-xl border border-gray-800 bg-gray-900 px-5 py-4"
              >
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={debate.status} short />
                      {debate.status !== 'completed' && (
                        <span className="text-xs text-amber-300">Partial report</span>
                      )}
                    </div>
                    <Link
                      to={`/debates/${debate.id}`}
                      className="mt-2 block rounded font-medium text-white hover:text-indigo-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                    >
                      {debate.topic}
                    </Link>
                    <p className="mt-1 text-xs text-gray-400">
                      {debate.completed_at
                        ? `Finished ${new Date(debate.completed_at).toLocaleString()}`
                        : `Created ${new Date(debate.created_at).toLocaleString()}`}{' '}
                      · {debate.agents.map((agent) => agent.name).join(', ')}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Link
                      to={`/debates/${debate.id}#verdict`}
                      className="btn-secondary"
                    >
                      View results
                    </Link>
                    <button
                      type="button"
                      onClick={() => void download(debate.id)}
                      disabled={downloadingId !== null}
                      aria-busy={busy}
                      className="btn-primary"
                    >
                      {busy ? 'Preparing PDF...' : 'Download PDF'}
                    </button>
                  </div>
                </div>
                {failed && (
                  <div className="mt-3">
                    <ErrorBanner
                      title="Report download failed"
                      message={downloadError.message}
                      onRetry={() => void download(debate.id)}
                    />
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </PageShell>
  )
}
