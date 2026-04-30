const BASE = (import.meta.env.VITE_API_BASE ?? '') + '/api'
const DEV_BASE = import.meta.env.VITE_API_BASE ?? ''

if (import.meta.env.DEV && import.meta.env.VITE_API_KEY) {
  console.warn(
    'VITE_API_KEY is embedded in the client bundle for internal/demo use only. Do not use this pattern for public deployments.'
  )
}

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

export async function confirmCost(jobId) {
  const res = await _fetch(`/jobs/${jobId}/confirm-cost`, { method: 'POST' })
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
  const body = {
    draft_version: draft.version ?? 1,
    pdd: draft.pdd,
    sipoc: draft.sipoc,
    assumptions: draft.assumptions,
  }
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


function _isSameOrigin(url) {
  try {
    return new URL(url).origin === new URL(BASE, window.location.href).origin
  } catch {
    return true // relative URL — safe to include auth header
  }
}


function _resolveUploadUrl(url) {
  if (/^https?:\/\//i.test(url)) return url
  if (url.startsWith('/')) return `${DEV_BASE}${url}`
  return url
}

function _makeClientUploadJobId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  // RFC 4122 v4 polyfill for environments without crypto.randomUUID
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

export async function uploadFile(file, sourceType = 'document') {
  const uploadJobId = _makeClientUploadJobId()
  const requestRes = await _fetch(`/jobs/${uploadJobId}/upload-url`, {
    method: 'POST',
    body: JSON.stringify({
      file_name: file.name,
      size_bytes: file.size,
      mime_type: file.type || 'application/octet-stream',
      source_type: sourceType,
      document_type: sourceType === 'document' ? 'document' : 'video',
    }),
  })
  const uploadMeta = await requestRes.json()
  const uploadUrl = _resolveUploadUrl(uploadMeta.upload.url)
  const uploadHeaders = {
    ...(uploadMeta.upload.headers ?? {}),
    ...(uploadMeta.upload.requires_api_auth && _isSameOrigin(uploadUrl) ? authHeaders() : {}),
  }
  const uploadRes = await fetch(uploadUrl, {
    method: uploadMeta.upload.method ?? 'PUT',
    body: file,
    headers: uploadHeaders,
  })
  if (!uploadRes.ok) {
    const err = await uploadRes.json().catch(() => ({}))
    throw new Error(err.detail ?? `Upload failed: ${uploadRes.statusText}`)
  }
  return {
    upload_id: uploadMeta.upload_id,
    file_name: uploadMeta.file_name,
    size_bytes: uploadMeta.size_bytes,
    mime_type: uploadMeta.mime_type,
    source_type: uploadMeta.source_type,
    storage_key: uploadMeta.storage_key,
  }
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
