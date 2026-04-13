import React, { useEffect, useState } from 'react'
import { getJob, listJobs } from '../api'

const STATUS_STYLES = {
  completed: 'bg-green-100 text-green-800',
  needs_review: 'bg-amber-100 text-amber-800',
  failed: 'bg-red-100 text-red-800',
  processing: 'bg-indigo-100 text-indigo-700',
  queued: 'bg-gray-100 text-gray-600',
}

export default function JobList({ onSelectJob, onNewJob }) {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selecting, setSelecting] = useState(null)

  useEffect(() => {
    listJobs()
      .then(data => setJobs(data.jobs ?? data))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  async function handleSelect(jobId) {
    setError(null)
    setSelecting(jobId)
    try {
      const fullJob = await getJob(jobId)
      onSelectJob(fullJob)
    } catch (err) {
      setError(err.message)
    } finally {
      setSelecting(null)
    }
  }

  if (loading) {
    return <div className="py-12 text-center text-gray-500">Loading jobs…</div>
  }

  return (
    <div className="space-y-4 rounded-xl bg-white p-6 shadow">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Recent Jobs</h2>
        <button
          onClick={onNewJob}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          + New Job
        </button>
      </div>

      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {jobs.length === 0 && !error && (
        <div className="py-12 text-center text-gray-400">
          <p className="text-sm">No jobs yet.</p>
          <button onClick={onNewJob} className="mt-3 text-sm text-indigo-600 hover:underline">
            Create your first job
          </button>
        </div>
      )}

      {jobs.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase tracking-wide text-gray-500">
                <th className="pb-2 pr-4">Job ID</th>
                <th className="pb-2 pr-4">Status</th>
                <th className="pb-2 pr-4">Sources</th>
                <th className="pb-2 pr-4">Profile</th>
                <th className="pb-2">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {jobs.map(job => (
                <tr
                  key={job.job_id}
                  onClick={() => handleSelect(job.job_id)}
                  className="cursor-pointer transition-colors hover:bg-gray-50"
                >
                  <td className="py-2 pr-4 font-mono text-xs text-gray-600">
                    {selecting === job.job_id ? (
                      <span className="animate-pulse text-indigo-500">Loading…</span>
                    ) : (
                      `${job.job_id.slice(0, 8)}…`
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[job.status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {job.status}
                    </span>
                  </td>
                  <td className="py-2 pr-4">
                    <div className="flex gap-1">
                      {job.has_video && <span className="rounded bg-purple-100 px-1.5 py-0.5 text-xs text-purple-700">video</span>}
                      {job.has_audio && <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-700">audio</span>}
                      {job.has_transcript && <span className="rounded bg-teal-100 px-1.5 py-0.5 text-xs text-teal-700">transcript</span>}
                    </div>
                  </td>
                  <td className="py-2 pr-4 capitalize text-gray-600">{job.profile_requested ?? '—'}</td>
                  <td className="py-2 font-mono text-xs text-gray-500">
                    {job.created_at ? new Date(job.created_at).toLocaleString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
