import React from 'react'
import { exportUrl } from '../api'

const FORMATS = [
  { key: 'json', label: 'JSON', mime: 'application/json' },
  { key: 'markdown', label: 'Markdown', mime: 'text/markdown' },
  { key: 'pdf', label: 'PDF', mime: 'application/pdf' },
  { key: 'docx', label: 'DOCX', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' },
]

export default function ExportLinks({ job }) {
  const jobId = job?.job_id
  const draft = job?.draft ?? {}
  const summary = draft.confidence_summary ?? {}
  const generatedAt = draft.finalized_at ?? job?.updated_at

  return (
    <div className="bg-white rounded-xl shadow p-6 max-w-xl mx-auto space-y-6">
      <div>
        <h2 className="text-xl font-semibold mb-1">Job Complete</h2>
        <p className="text-xs text-gray-400 font-mono">{jobId}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm">
        {summary.overall !== undefined && (
          <div className="bg-gray-50 rounded p-3">
            <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Confidence</p>
            <p className="font-bold text-indigo-700">{Math.round(summary.overall * 100)}%</p>
          </div>
        )}
        {summary.evidence_strength && (
          <div className="bg-gray-50 rounded p-3">
            <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Evidence</p>
            <p className="font-semibold text-gray-800">{summary.evidence_strength}</p>
          </div>
        )}
        {generatedAt && (
          <div className="bg-gray-50 rounded p-3 col-span-2">
            <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Generated At</p>
            <p className="font-mono text-xs text-gray-700">{generatedAt}</p>
          </div>
        )}
      </div>

      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3">Download Exports</h3>
        <div className="flex flex-wrap gap-3">
          {FORMATS.map(({ key, label }) => (
            <a
              key={key}
              href={exportUrl(jobId, key)}
              download
              className="flex items-center gap-2 bg-indigo-50 border border-indigo-200 text-indigo-700 hover:bg-indigo-100 px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              <span>↓</span>
              <span>{label}</span>
            </a>
          ))}
        </div>
      </div>
    </div>
  )
}
