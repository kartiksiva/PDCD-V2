const BASE = (import.meta.env.VITE_API_BASE ?? '') + '/api'

async function _fetch(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw Object.assign(new Error(err.detail ?? res.statusText), { status: res.status, data: err })
  }
  return res
}

export async function createJob(payload) {
  const res = await _fetch('/jobs', { method: 'POST', body: JSON.stringify(payload) })
  return res.json()
}

export async function getJob(jobId) {
  const res = await _fetch(`/jobs/${jobId}`)
  return res.json()
}

export async function finalizeJob(jobId) {
  const res = await _fetch(`/jobs/${jobId}/finalize`, { method: 'POST' })
  return res.json()
}

export function exportUrl(jobId, fmt) {
  return `${BASE}/jobs/${jobId}/exports/${fmt}`
}

export async function uploadFile(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/upload`, { method: 'POST', body: form })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? `Upload failed: ${res.statusText}`)
  }
  return res.json()
}

export async function devSimulate(jobId) {
  const res = await fetch(`/dev/jobs/${jobId}/simulate`, { method: 'POST' })
  if (!res.ok) throw new Error('Simulate failed')
  return res.json()
}
