import React from 'react'

const HEADERS = ['Supplier', 'Input', 'Process Step', 'Output', 'Customer', 'Anchor']

export default function SipocTable({ sipoc }) {
  if (!sipoc || sipoc.length === 0) {
    return <p className="text-sm text-gray-400 italic">No SIPOC data available.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm border-collapse">
        <thead>
          <tr className="bg-indigo-50">
            {HEADERS.map(h => (
              <th key={h} className="border border-indigo-100 px-3 py-2 text-left font-semibold text-indigo-700 whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sipoc.map((row, idx) => {
            const hasAnchorIssue = Boolean(row.anchor_missing_reason)
            return (
              <tr key={idx} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                <td className="border border-gray-200 px-3 py-2">{row.supplier ?? '—'}</td>
                <td className="border border-gray-200 px-3 py-2">{row.input ?? '—'}</td>
                <td className="border border-gray-200 px-3 py-2 font-medium">{row.process_step ?? '—'}</td>
                <td className="border border-gray-200 px-3 py-2">{row.output ?? '—'}</td>
                <td className="border border-gray-200 px-3 py-2">{row.customer ?? '—'}</td>
                <td className="border border-gray-200 px-3 py-2">
                  {hasAnchorIssue ? (
                    <span className="text-gray-400 italic text-xs">{row.anchor_missing_reason}</span>
                  ) : (
                    <span className="font-mono text-xs">{row.source_anchor ?? '—'}</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
