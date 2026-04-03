import React from 'react'

const SEVERITY_STYLES = {
  blocker: 'bg-red-50 border-red-300 text-red-800',
  warning: 'bg-amber-50 border-amber-300 text-amber-800',
  info: 'bg-blue-50 border-blue-300 text-blue-800',
}

const SEVERITY_ICON = {
  blocker: '🔴',
  warning: '⚠️',
  info: 'ℹ️',
}

const SEVERITY_ORDER = ['blocker', 'warning', 'info']

export default function FlagPanel({ flags }) {
  if (!flags || flags.length === 0) return null

  const sorted = [...flags].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity)
  )

  return (
    <div className="rounded-lg border overflow-hidden">
      <div className="bg-gray-50 border-b px-4 py-2">
        <span className="text-sm font-medium text-gray-700">Review Flags ({flags.length})</span>
      </div>
      <div className="divide-y">
        {sorted.map((flag, idx) => {
          const sev = flag.severity?.toLowerCase() ?? 'info'
          const styles = SEVERITY_STYLES[sev] ?? SEVERITY_STYLES.info
          return (
            <div key={idx} className={`px-4 py-3 border-l-4 ${styles}`}>
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 text-sm">{SEVERITY_ICON[sev] ?? 'ℹ️'}</span>
                <div className="min-w-0">
                  <span className="text-xs font-semibold uppercase tracking-wide mr-2">{sev}</span>
                  <span className="text-sm font-medium">{flag.code}</span>
                  {flag.message && (
                    <p className="text-sm mt-0.5 opacity-80">{flag.message}</p>
                  )}
                  {flag.field && (
                    <p className="text-xs mt-0.5 opacity-60 font-mono">field: {flag.field}</p>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
