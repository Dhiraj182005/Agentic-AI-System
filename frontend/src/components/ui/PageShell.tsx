import type { ReactNode } from 'react'
import AppHeader from './AppHeader'

const MAX_WIDTHS = {
  sm: 'max-w-3xl',
  md: 'max-w-5xl',
  lg: 'max-w-6xl',
} as const

export default function PageShell({
  children,
  maxWidth = 'md',
}: {
  children: ReactNode
  maxWidth?: keyof typeof MAX_WIDTHS
}) {
  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-indigo-600 focus:px-4 focus:py-2 focus:text-sm focus:font-semibold"
      >
        Skip to content
      </a>
      <AppHeader />
      <div className="lg:pl-60">
        <main
          id="main-content"
          className={`mx-auto w-full ${MAX_WIDTHS[maxWidth]} px-4 py-8 sm:px-6 lg:py-10`}
        >
          {children}
        </main>
      </div>
    </div>
  )
}
