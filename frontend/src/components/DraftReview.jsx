import React, { useEffect, useRef, useState } from 'react'
import { finalizeJob, saveDraft } from '../api'
import FlagPanel from './FlagPanel'

const PDD_STRING_KEYS = [
  'purpose',
  'scope',
  'triggers',
  'preconditions',
  'business_rules',
  'exceptions',
  'outputs',
  'metrics',
  'risks',
]
const PDD_LIST_KEYS = ['roles', 'systems']
const UNKNOWN_PATTERN = /unknown/i

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

function EditablePddSection({ pdd, onChange }) {
  const pddObj = pdd ?? {}
  const steps = pddObj.steps ?? []

  return (
    <div className="space-y-3">
      {PDD_STRING_KEYS.map(key => (
        <div key={key}>
          <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
            {key.replace(/_/g, ' ')}
          </label>
          <textarea
            className="w-full border rounded p-2 text-sm resize-y min-h-[48px] focus:ring-1 focus:ring-indigo-400 outline-none"
            value={typeof pddObj[key] === 'string' ? pddObj[key] : (pddObj[key] ?? '')}
            onChange={event => onChange(key, event.target.value)}
            placeholder={`Enter ${key.replace(/_/g, ' ')}…`}
          />
        </div>
      ))}
      {PDD_LIST_KEYS.map(key => (
        <div key={key}>
          <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
            {key.replace(/_/g, ' ')} (comma-separated)
          </label>
          <input
            type="text"
            className="w-full border rounded p-2 text-sm focus:ring-1 focus:ring-indigo-400 outline-none"
            value={Array.isArray(pddObj[key]) ? pddObj[key].join(', ') : (pddObj[key] ?? '')}
            onChange={event => onChange(key, event.target.value.split(',').map(item => item.trim()).filter(Boolean))}
            placeholder="e.g. Analyst, Manager"
          />
        </div>
      ))}
      {steps.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-gray-700 mb-2">Process Steps (read-only)</h4>
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

function EditableSipocTable({ sipoc, onRowChange }) {
  if (!sipoc || sipoc.length === 0) {
    return <p className="text-sm text-gray-400 italic">No SIPOC rows.</p>
  }

  const editableFields = ['supplier', 'input', 'process_step', 'output', 'customer', 'source_anchor']

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm border-collapse">
        <thead>
          <tr className="bg-indigo-50">
            {[...editableFields, 'step_anchor', 'anchor_missing_reason'].map(header => (
              <th
                key={header}
                className="border border-indigo-100 px-2 py-1 text-left text-xs font-semibold text-indigo-700 whitespace-nowrap"
              >
                {header.replace(/_/g, ' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sipoc.map((row, idx) => (
            <tr key={idx} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
              {editableFields.map(field => (
                <td key={field} className="border border-gray-200 px-1 py-1">
                  <input
                    type="text"
                    className="w-full bg-transparent text-sm outline-none focus:ring-1 focus:ring-indigo-300 rounded px-1"
                    value={row[field] ?? ''}
                    onChange={event => onRowChange(idx, field, event.target.value)}
                  />
                </td>
              ))}
              <td className="border border-gray-200 px-1 py-1">
                <input
                  type="text"
                  className="w-full bg-transparent text-sm outline-none focus:ring-1 focus:ring-indigo-300 rounded px-1 font-mono"
                  value={Array.isArray(row.step_anchor) ? row.step_anchor.join(', ') : (row.step_anchor ?? '')}
                  onChange={event => onRowChange(idx, 'step_anchor', event.target.value.split(',').map(item => item.trim()).filter(Boolean))}
                  placeholder="step-01, step-02"
                />
              </td>
              <td className="border border-gray-200 px-1 py-1">
                <input
                  type="text"
                  className="w-full bg-transparent text-sm outline-none focus:ring-1 focus:ring-indigo-300 rounded px-1 italic text-gray-400"
                  value={row.anchor_missing_reason ?? ''}
                  onChange={event => onRowChange(idx, 'anchor_missing_reason', event.target.value)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SpeakerResolutionPanel({ speakers, resolutions, onChange }) {
  const unknown = (speakers ?? []).filter(speaker => UNKNOWN_PATTERN.test(speaker))
  if (unknown.length === 0) return null

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 space-y-3">
      <p className="text-sm font-medium text-amber-800">
        {unknown.length} unknown speaker{unknown.length > 1 ? 's' : ''} — assign roles before finalizing.
      </p>
      {unknown.map(speaker => (
        <div key={speaker} className="flex items-center gap-3">
          <span
            className="text-sm text-amber-700 font-mono flex-shrink-0 w-32 truncate"
            title={speaker}
          >
            {speaker}
          </span>
          <input
            type="text"
            placeholder="e.g. Process Analyst, Manager"
            value={resolutions?.[speaker] ?? ''}
            onChange={event => onChange({ ...(resolutions ?? {}), [speaker]: event.target.value })}
            className="flex-1 border rounded px-2 py-1 text-sm focus:ring-1 focus:ring-indigo-400 outline-none"
          />
        </div>
      ))}
    </div>
  )
}

export default function DraftReview({ job, onFinalized }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [editedDraft, setEditedDraft] = useState(() => job?.draft ?? {})
  const [liveFlags, setLiveFlags] = useState(() => job?.review_notes?.flags ?? [])
  const [speakerResolutions, setSpeakerResolutions] = useState(() => job?.speaker_resolutions ?? {})
  const [saveState, setSaveState] = useState('idle')
  const saveTimer = useRef(null)
  const inFlightSaveRef = useRef(Promise.resolve())

  useEffect(() => {
    setEditedDraft(job?.draft ?? {})
    setLiveFlags(job?.review_notes?.flags ?? [])
    setSpeakerResolutions(job?.speaker_resolutions ?? {})
    setSaveState('idle')
    setError(null)
  }, [job?.job_id])

  useEffect(() => () => clearTimeout(saveTimer.current), [])

  async function persistDraft(nextDraft, nextResolutions) {
    const result = await saveDraft(job.job_id, nextDraft, nextResolutions ?? speakerResolutions)
    setEditedDraft(result.draft ?? nextDraft)
    setLiveFlags(result.review_notes?.flags ?? [])
    setSpeakerResolutions(result.speaker_resolutions ?? (nextResolutions ?? speakerResolutions))
    setSaveState('saved')
    return result
  }

  function queueSave(nextDraft, nextResolutions) {
    const chained = inFlightSaveRef.current
      .catch(() => {})
      .then(() => persistDraft(nextDraft, nextResolutions))
    inFlightSaveRef.current = chained
    return chained
  }

  function scheduleSave(nextDraft, nextResolutions) {
    clearTimeout(saveTimer.current)
    setSaveState('saving')
    saveTimer.current = setTimeout(() => {
      queueSave(nextDraft, nextResolutions).catch(() => {
        setSaveState('error')
      })
    }, 1500)
  }

  function setPddField(key, value) {
    const nextDraft = { ...editedDraft, pdd: { ...(editedDraft.pdd ?? {}), [key]: value } }
    setEditedDraft(nextDraft)
    scheduleSave(nextDraft)
  }

  function setSipocRow(idx, field, value) {
    const rows = [...(editedDraft.sipoc ?? [])]
    rows[idx] = { ...rows[idx], [field]: value }
    const nextDraft = { ...editedDraft, sipoc: rows }
    setEditedDraft(nextDraft)
    scheduleSave(nextDraft)
  }

  const blockers = liveFlags.filter(flag => flag.severity?.toLowerCase() === 'blocker')
  const detectedSpeakers = job?.extracted_evidence?.speakers_detected ?? job?.agent_signals?.speakers_detected ?? []
  const consistency = editedDraft.transcript_media_consistency ?? editedDraft.confidence_summary?.transcript_media_consistency
  const confidenceSummary = editedDraft.confidence_summary

  async function handleFinalize() {
    clearTimeout(saveTimer.current)
    setError(null)
    setLoading(true)
    try {
      await inFlightSaveRef.current.catch(() => {})
      setSaveState('saving')
      const saved = await queueSave(editedDraft, speakerResolutions)
      setEditedDraft(saved.draft ?? editedDraft)
      setLiveFlags(saved.review_notes?.flags ?? [])
      setSpeakerResolutions(saved.speaker_resolutions ?? speakerResolutions)
      setSaveState('saved')
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
        <FlagPanel flags={liveFlags} />
        <SpeakerResolutionPanel
          speakers={detectedSpeakers}
          resolutions={speakerResolutions}
          onChange={resolutions => {
            setSpeakerResolutions(resolutions)
            scheduleSave(editedDraft, resolutions)
          }}
        />
        {saveState === 'saving' && <p className="text-xs text-gray-400 animate-pulse">Saving…</p>}
        {saveState === 'saved' && <p className="text-xs text-green-600">Draft saved.</p>}
        {saveState === 'error' && <p className="text-xs text-red-500">Save failed — changes not persisted.</p>}

        <div>
          <h3 className="text-base font-semibold text-gray-800 mb-3">Process Definition Document</h3>
          <EditablePddSection pdd={editedDraft.pdd} onChange={setPddField} />
        </div>

        <div>
          <h3 className="text-base font-semibold text-gray-800 mb-3">SIPOC</h3>
          <EditableSipocTable sipoc={editedDraft.sipoc} onRowChange={setSipocRow} />
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
