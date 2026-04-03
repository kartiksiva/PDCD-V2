import React, { useState } from 'react'
import { finalizeJob } from '../api'
import FlagPanel from './FlagPanel'
import SipocTable from './SipocTable'

function ConfidenceSummary({ summary }) {
  if (!summary) return null
  const overall = summary.overall ?? 0
  const pct = Math.round(overall * 100)
  return (
    <div className="bg-gray-50 rounded-lg p-4 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">Confidence</span>
        <span className="text-sm font-bold text-indigo-700">{pct}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className="bg-indigo-500 h-2 rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex gap-4 text-xs text-gray-500">
        {summary.evidence_strength && (
          <span>Evidence: <strong className="text-gray-700">{summary.evidence_strength}</strong></span>
        )}
        {summary.source_quality && (
          <span>Quality: <strong className="text-gray-700">{summary.source_quality}</strong></span>
        )}
      </div>
    </div>
  )
}

function MismatchBanner({ consistency }) {
  if (!consistency || consistency.verdict !== 'suspected_mismatch') return null
  return (
    <div className="bg-amber-50 border border-amber-300 text-amber-800 rounded-lg px-4 py-3 text-sm flex items-start gap-2">
      <span>⚠️</span>
      <div>
        <strong>Transcript/media mismatch suspected.</strong>
        {consistency.detail && <span className="ml-1">{consistency.detail}</span>}
      </div>
    </div>
  )
}

function PddSection({ pdd }) {
  if (!pdd) return null
  const steps = pdd.steps ?? []
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        {[['Purpose', pdd.purpose], ['Scope', pdd.scope], ['Roles', Array.isArray(pdd.roles) ? pdd.roles.join(', ') : pdd.roles], ['Systems', Array.isArray(pdd.systems) ? pdd.systems.join(', ') : pdd.systems]].map(([label, val]) => val ? (
          <div key={label} className="bg-gray-50 rounded p-3">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">{label}</p>
            <p className="text-sm text-gray-800">{val}</p>
          </div>
        ) : null)}
      </div>
      {steps.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-gray-700 mb-2">Process Steps</h4>
          <ol className="space-y-2">
            {steps.map((step, idx) => (
              <li key={idx} className="bg-gray-50 rounded p-3 text-sm">
                <div className="flex items-start gap-2">
                  <span className="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 text-xs font-bold flex items-center justify-center">
                    {idx + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-gray-800">{step.summary ?? step.id}</p>
                    <div className="flex flex-wrap gap-3 mt-1 text-xs text-gray-500">
                      {step.actor && <span>Actor: <strong>{step.actor}</strong></span>}
                      {step.system && <span>System: <strong>{step.system}</strong></span>}
                      {step.input && <span>In: <strong>{step.input}</strong></span>}
                      {step.output && <span>Out: <strong>{step.output}</strong></span>}
                      {step.source_anchor && <span className="font-mono">@ {step.source_anchor}</span>}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

export default function DraftReview({ job, onFinalized }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const draft = job?.draft ?? {}
  const pdd = draft.pdd ?? {}
  const sipoc = draft.sipoc ?? []
  const reviewNotes = job?.review_notes ?? {}
  const flags = reviewNotes.flags ?? []
  const blockers = flags.filter(f => f.severity?.toLowerCase() === 'blocker')
  const consistency = draft.transcript_media_consistency ?? draft.confidence_summary?.transcript_media_consistency
  const confidenceSummary = draft.confidence_summary

  async function handleFinalize() {
    setError(null)
    setLoading(true)
    try {
      const data = await finalizeJob(job.job_id)
      onFinalized(data)
    } catch (err) {
      const detail = err.data?.detail
      setError(typeof detail === 'string' ? detail : detail?.message ?? err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6 pb-24">
      <div className="bg-white rounded-xl shadow p-6 space-y-5">
        <h2 className="text-xl font-semibold">Draft Review</h2>

        <ConfidenceSummary summary={confidenceSummary} />
        <MismatchBanner consistency={consistency} />
        <FlagPanel flags={flags} />

        <div>
          <h3 className="text-base font-semibold text-gray-800 mb-3">Process Definition Document</h3>
          <PddSection pdd={pdd} />
        </div>

        <div>
          <h3 className="text-base font-semibold text-gray-800 mb-3">SIPOC</h3>
          <SipocTable sipoc={sipoc} />
        </div>
      </div>

      <div className="fixed bottom-0 left-0 right-0 bg-white border-t px-6 py-3 flex items-center gap-4 z-10">
        {error && (
          <span className="text-sm text-red-600 flex-1">{error}</span>
        )}
        {blockers.length > 0 && !error && (
          <span className="text-sm text-red-600 flex-1">
            {blockers.length} blocker flag{blockers.length > 1 ? 's' : ''} must be resolved before finalizing.
          </span>
        )}
        <div className="ml-auto">
          <button
            onClick={handleFinalize}
            disabled={loading || blockers.length > 0}
            title={blockers.length > 0 ? 'Resolve blocker flags first' : undefined}
            className="bg-indigo-600 text-white px-6 py-2 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Finalizing…' : 'Finalize'}
          </button>
        </div>
      </div>
    </div>
  )
}
