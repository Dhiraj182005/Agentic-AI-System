export default function LoadingState({
  label = 'Loading...',
  className = 'py-10 text-center',
}: {
  label?: string
  className?: string
}) {
  return (
    <div role="status" aria-live="polite" className={className}>
      <span
        aria-hidden="true"
        className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-gray-600 border-t-indigo-400 align-middle"
      />
      <span className="ml-2 text-sm text-gray-400">{label}</span>
    </div>
  )
}
