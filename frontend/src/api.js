const BASE = (import.meta.env.VITE_API_BASE ?? '') + '/api'
const DEV_BASE = import.meta.env.VITE_API_BASE ?? ''

function authHeaders(headers = {}) {
  return {
    ...(import.meta.env.VITE_API_KEY ? { 'X-API-Key': import.meta.env.VITE_API_KEY } : {}),
    ...headers,
  }
}

async function _fetch(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: authHeaders({
      'Content-Type': 'application/json',
      ...options.headers,
    }),
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

export async function saveDraft(jobId, draft, speakerResolutions = null) {
  const body = { pdd: draft.pdd, sipoc: draft.sipoc, assumptions: draft.assumptions }
  if (speakerResolutions !== null) body.speaker_resolutions = speakerResolutions
  const res = await _fetch(`/jobs/${jobId}/draft`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
  return res.json()
}

export async function listJobs() {
  const res = await _fetch('/jobs')
  return res.json()
}

export function exportUrl(jobId, fmt) {
  return `${BASE}/jobs/${jobId}/exports/${fmt}`
}

export async function uploadFile(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/upload`, {
    method: 'POST',
    body: form,
    headers: authHeaders(),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? `Upload failed: ${res.statusText}`)
  }
  return res.json()
}

function inferDownloadName(jobId, fmt, res) {
  const contentDisposition = res.headers.get('Content-Disposition') ?? ''
  const match = contentDisposition.match(/filename="?([^"]+)"?/)
  if (match?.[1]) return match[1]
  return fmt === 'markdown' ? `pdd-${jobId}.md` : `pdd-${jobId}.${fmt}`
}

export async function downloadExport(jobId, fmt) {
  const res = await _fetch(`/jobs/${jobId}/exports/${fmt}`)
  const blob = await res.blob()
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = inferDownloadName(jobId, fmt, res)
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(href), 0)
}

export async function devSimulate(jobId) {
  const res = await fetch(`${DEV_BASE}/dev/jobs/${jobId}/simulate`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('Simulate failed')
  return res.json()
}
