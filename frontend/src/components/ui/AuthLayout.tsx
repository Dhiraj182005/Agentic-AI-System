import type { ReactNode } from 'react'
import BrandMark from './BrandMark'

/** Centered card used by the sign-in and registration pages. */
export default function AuthLayout({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: ReactNode
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-950 px-4 py-10 text-white">
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-x-0 top-0 h-72 bg-gradient-to-b from-indigo-600/15 to-transparent"
      />
      <main className="relative w-full max-w-md">
        <div className="mb-8 flex justify-center">
          <BrandMark size="lg" />
        </div>
        <div className="rounded-2xl border border-gray-800 bg-gray-900/90 p-8 shadow-2xl shadow-black/40">
          <h1 className="text-xl font-semibold text-white">{title}</h1>
          <p className="mb-6 mt-1 text-sm text-gray-400">{subtitle}</p>
          {children}
        </div>
      </main>
    </div>
  )
}
