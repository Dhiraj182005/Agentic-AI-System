/** MAVES logo: a simple "two voices" mark plus the wordmark. */
export default function BrandMark({ size = 'md' }: { size?: 'md' | 'lg' }) {
  const box = size === 'lg' ? 'h-11 w-11' : 'h-9 w-9'
  return (
    <span className="flex items-center gap-2.5">
      <span
        aria-hidden="true"
        className={`flex ${box} items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-900/40`}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth={1.8} className="h-5 w-5">
          <path d="M4 6h9a2 2 0 012 2v4a2 2 0 01-2 2H8l-4 3V6z" strokeLinejoin="round" />
          <path d="M15 10h3a2 2 0 012 2v7l-3-2.5h-4a2 2 0 01-2-2" strokeLinejoin="round" />
        </svg>
      </span>
      <span className="leading-tight">
        <span className={`block font-bold tracking-wide text-white ${size === 'lg' ? 'text-xl' : 'text-base'}`}>
          MAVES
        </span>
        <span className="block text-[11px] text-gray-400">AI Debate Arena</span>
      </span>
    </span>
  )
}
