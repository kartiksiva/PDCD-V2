import React, { useEffect, useRef, useState } from 'react'
import { getJob, devSimulate } from '../api'

const PHASES = ['extracting', 'processing', 'reviewing']
const POLL_INTERVAL = 3000

function PhaseCircle({ state }) {
  if (state === 'done') {
    return (
      <span className="inline-block w-4 h-4 rounded-full bg-indigo-600 flex-shrink-0" />
    )
  }
  if (state === 'active') {
    return (
      <span className="inline-block w-4 h-4 rounded-full bg-amber-400 animate-pulse flex-shrink-0" />
    )
  }
  return (
    <span className="inline-block w-4 h-4 rounded-full border-2 border-gray-300 flex-shrink-0" />
  )
}

function phaseState(phase, currentPhase, status) {
  const active = currentPhase === phase
  const phaseIdx = PHASES.indexOf(phase)
  const currentIdx = PHASES.indexOf(currentPhase)
  if (phaseIdx < currentIdx) return 'done'
  if (active) return status === 'failed' ? 'done' : 'active'
  return 'pending'
}

export default function JobStatus({ jobId, onReady }) {
  const [job, setJob] = useState(null)
  const [error, setError] = useState(null)
  const intervalRef = useRef(null)

  function stopPoll() {
    if (intervalRef.current) clearInterval(intervalRef.current)
  }

  async function poll() {
    try {
      const data = await getJob(jobId)
      setJob(data)
      const { status } = data
      if (status === 'needs_review' || status === 'completed') {
        stopPoll()
        onReady(data)
      } else if (status === 'failed') {
        stopPoll()
      }
    } catch (err) {
      setError(err.message)
      stopPoll()
    }
  }

  useEffect(() => {
    poll()
    intervalRef.current = setInterval(poll, POLL_INTERVAL)
    return stopPoll
  }, [jobId])

  if (error) {
    return (
      <div className="bg-red-50 border border-red-300 text-red-700 rounded-xl p-6 max-w-xl mx-auto">
        <p className="font-medium">Error polling job</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    )
  }

  if (!job) {
    return <div className="text-center text-gray-500 py-12">Loading…</div>
  }

  return (
    <div className="bg-white rounded-xl shadow p-6 max-w-xl mx-auto space-y-6">
      <div>
        <h2 className="text-xl font-semibold mb-1">Job Progress</h2>
        <p className="text-xs text-gray-400 font-mono">{jobId}</p>
      </div>

      <div className="flex items-center gap-3">
        {PHASES.map((phase, i) => {
          const state = phaseState(phase, job.current_phase, job.status)
          return (
            <React.Fragment key={phase}>
              <div className="flex items-center gap-1.5">
                <PhaseCircle state={state} />
                <span className={`text-sm capitalize ${state === 'active' ? 'text-amber-700 font-medium' : state === 'done' ? 'text-indigo-700' : 'text-gray-400'}`}>
                  {phase}
                </span>
              </div>
              {i < PHASES.length - 1 && (
                <span className="text-gray-300 text-sm">→</span>
              )}
            </React.Fragment>
          )
        })}
      </div>

      <div className="text-sm">
        <span className="text-gray-500">Status: </span>
        <span className={`font-medium ${job.status === 'failed' ? 'text-red-600' : 'text-gray-800'}`}>
          {job.status}
        </span>
      </div>

      {job.status === 'failed' && job.error && (
        <div className="bg-red-50 border border-red-300 text-red-700 rounded p-3 text-sm">
          <p className="font-medium">Job failed</p>
          <p className="mt-1 font-mono text-xs break-all">
            {typeof job.error === 'string' ? job.error : job.error.message ?? JSON.stringify(job.error)}
          </p>
        </div>
      )}

      {!['failed', 'needs_review', 'completed'].includes(job.status) && (
        <p className="text-xs text-gray-400 animate-pulse">Polling every 3 seconds…</p>
      )}

      {!['failed', 'needs_review', 'completed'].includes(job.status) && (
        <div className="border-t pt-4">
          <p className="text-xs text-gray-400 mb-2">Dev: no workers running locally?</p>
          <button
            onClick={async () => { await devSimulate(jobId); poll() }}
            className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-600 px-3 py-1.5 rounded border"
          >
            Simulate → needs_review
          </button>
        </div>
      )}
    </div>
  )
}
