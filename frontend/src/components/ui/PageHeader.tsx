import type { ReactNode } from 'react'

/** Consistent page heading: title, optional description and actions. */
export default function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  eyebrow?: ReactNode
}) {
  return (
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 flex-1">
        {eyebrow && <div className="mb-2">{eyebrow}</div>}
        <h1 className="page-title break-words">{title}</h1>
        {description && (
          <p className="mt-1.5 max-w-2xl text-sm text-gray-400">{description}</p>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
      )}
    </div>
  )
}
