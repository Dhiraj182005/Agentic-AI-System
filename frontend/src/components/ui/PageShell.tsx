import type { ReactNode } from 'react'
import AppHeader from './AppHeader'

const MAX_WIDTHS = {
  sm: 'max-w-3xl',
  md: 'max-w-5xl',
} as const

export default function PageShell({
  children,
  maxWidth = 'sm',
}: {
  children: ReactNode
  maxWidth?: keyof typeof MAX_WIDTHS
}) {
  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <AppHeader />
      <main
        className={`mx-auto w-full ${MAX_WIDTHS[maxWidth]} px-4 sm:px-6 py-8`}
      >
        {children}
      </main>
    </div>
  )
}
