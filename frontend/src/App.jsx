import React, { useState } from 'react'
import CreateJob from './components/CreateJob'
import JobStatus from './components/JobStatus'
import DraftReview from './components/DraftReview'
import ExportLinks from './components/ExportLinks'

export default function App() {
  const [view, setView] = useState('create')
  const [jobId, setJobId] = useState(null)
  const [job, setJob] = useState(null)

  function onJobCreated(id) { setJobId(id); setView('status') }
  function onJobReady(jobData) { setJob(jobData); setView('review') }
  function onFinalized(jobData) { setJob(jobData); setView('exports') }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b px-6 py-3 flex items-center gap-4">
        <span className="font-semibold text-indigo-700 text-lg">PFCD</span>
        {jobId && <span className="text-xs text-gray-400 font-mono">{jobId}</span>}
        <button
          onClick={() => { setView('create'); setJobId(null); setJob(null) }}
          className="ml-auto text-sm text-indigo-600 hover:underline"
        >
          + New Job
        </button>
      </nav>
      <main className="max-w-4xl mx-auto py-8 px-4">
        {view === 'create'  && <CreateJob onCreated={onJobCreated} />}
        {view === 'status'  && <JobStatus jobId={jobId} onReady={onJobReady} />}
        {view === 'review'  && <DraftReview job={job} onFinalized={onFinalized} />}
        {view === 'exports' && <ExportLinks job={job} />}
      </main>
    </div>
  )
}
