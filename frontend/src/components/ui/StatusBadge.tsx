import { debateStatusLabel, debateStatusTone } from '../../services/debates'

/** Debate status pill using the backend status values verbatim. */
export default function StatusBadge({
  status,
  short = false,
}: {
  status: string
  short?: boolean
}) {
  const label =
    short && status === 'pending' ? 'Not started' : debateStatusLabel(status)
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${debateStatusTone(status)}`}
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 rounded-full bg-current ${status === 'running' ? 'animate-pulse' : ''}`}
      />
      {label}
    </span>
  )
}
