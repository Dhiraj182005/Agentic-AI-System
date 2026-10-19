export default function ErrorBanner({
  title,
  message,
  onRetry,
  retryLabel = 'Retry',
}: {
  title?: string
  message: string
  onRetry?: () => void
  retryLabel?: string
}) {
  return (
    <div role="alert" className="alert-error flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        {title && <p className="font-semibold text-red-200">{title}</p>}
        <p className={title ? 'mt-0.5 text-red-300/90' : ''}>{message}</p>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-lg border border-red-800 bg-red-950/60 px-3 py-1.5 text-xs font-semibold text-red-200 transition-colors hover:bg-red-900/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
        >
          {retryLabel}
        </button>
      )}
    </div>
  )
}
