import React, { useRef, useState } from 'react'
import { createJob, uploadFile } from '../api'

const SOURCE_TYPES = ['video', 'audio', 'transcript', 'document']

const MIME_TO_SOURCE = {
  'video/mp4': 'video', 'video/quicktime': 'video', 'video/x-msvideo': 'video', 'video/webm': 'video',
  'audio/mpeg': 'audio', 'audio/mp4': 'audio', 'audio/wav': 'audio', 'audio/ogg': 'audio',
  'text/plain': 'transcript', 'text/vtt': 'transcript',
  'application/pdf': 'document', 'application/msword': 'document',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'document',
}

function guessSourceType(file) {
  return MIME_TO_SOURCE[file.type] ?? (
    file.name.match(/\.(mp4|mov|avi|webm|mkv)$/i) ? 'video' :
    file.name.match(/\.(mp3|wav|ogg|m4a)$/i) ? 'audio' :
    file.name.match(/\.(vtt|srt|txt)$/i) ? 'transcript' : 'document'
  )
}


export default function CreateJob({ onCreated }) {
  const [rows, setRows] = useState([])          // { file, sourceType, uploading, error, result }
  const [profile, setProfile] = useState('balanced')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const inputRef = useRef()

  function onFilesPicked(e) {
    const picked = Array.from(e.target.files)
    setRows(prev => [
      ...prev,
      ...picked.map(f => ({
        file: f,
        sourceType: guessSourceType(f),
        uploading: false,
        error: null,
        result: null,
      })),
    ])
    e.target.value = ''
  }

  function removeRow(idx) {
    setRows(prev => prev.filter((_, i) => i !== idx))
  }

  function setSourceType(idx, val) {
    setRows(prev => prev.map((r, i) => i === idx ? { ...r, sourceType: val } : r))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (rows.length === 0) return
    setSubmitError(null)
    setSubmitting(true)

    try {
      // Upload all files that haven't been uploaded yet
      const uploaded = await Promise.all(
        rows.map(async (row, idx) => {
          if (row.result) return row.result
          setRows(prev => prev.map((r, i) => i === idx ? { ...r, uploading: true, error: null } : r))
          try {
            const result = await uploadFile(row.file, row.sourceType)
            setRows(prev => prev.map((r, i) => i === idx ? { ...r, uploading: false, result, sourceType: result.source_type } : r))
            return { ...result, source_type: row.sourceType }
          } catch (err) {
            setRows(prev => prev.map((r, i) => i === idx ? { ...r, uploading: false, error: err.message } : r))
            throw err
          }
        })
      )

      const data = await createJob({
        profile,
        input_files: uploaded.map((u, idx) => ({
          source_type: rows[idx].sourceType,
          file_name: u.file_name,
          size_bytes: u.size_bytes,
          mime_type: u.mime_type,
          upload_id: u.upload_id,
        })),
      })
      onCreated(data.job_id)
    } catch (err) {
      if (!rows.some(r => r.error)) {
        const detail = err.data?.detail
        setSubmitError(typeof detail === 'string' ? detail : detail?.message ?? err.message)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const anyUploading = rows.some(r => r.uploading)
  const anyError = rows.some(r => r.error)

  return (
    <div className="bg-white rounded-xl shadow p-6 max-w-xl mx-auto">
      <h2 className="text-xl font-semibold mb-4">Create New Job</h2>
      <form onSubmit={handleSubmit} className="space-y-5">

        {/* Drop zone / file picker */}
        <div>
          <label className="text-sm font-medium text-gray-700 block mb-2">Input Files</label>
          <div
            onClick={() => inputRef.current.click()}
            onDragOver={e => e.preventDefault()}
            onDrop={e => {
              e.preventDefault()
              const picked = Array.from(e.dataTransfer.files)
              setRows(prev => [
                ...prev,
                ...picked.map(f => ({ file: f, sourceType: guessSourceType(f), uploading: false, error: null, result: null })),
              ])
            }}
            className="border-2 border-dashed border-gray-300 rounded-lg px-4 py-6 text-center cursor-pointer hover:border-indigo-400 hover:bg-indigo-50 transition-colors"
          >
            <p className="text-sm text-gray-500">Click or drag & drop files here</p>
            <p className="text-xs text-gray-400 mt-1">Video, audio, transcript, or document</p>
          </div>
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
            accept="video/*,audio/*,text/*,.vtt,.srt,.pdf,.doc,.docx,.ppt,.pptx"
            onChange={onFilesPicked}
          />
        </div>

        {/* File rows */}
        {rows.length > 0 && (
          <div className="space-y-2">
            {rows.map((row, idx) => (
              <div key={idx} className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{row.file.name}</p>
                  <p className="text-xs text-gray-400">{(row.file.size / 1024).toFixed(1)} KB</p>
                </div>
                <select
                  value={row.sourceType}
                  onChange={e => setSourceType(idx, e.target.value)}
                  className="border rounded px-2 py-1 text-xs flex-shrink-0"
                >
                  {SOURCE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
                {row.uploading && <span className="text-xs text-indigo-500 animate-pulse">uploading…</span>}
                {row.result && !row.uploading && <span className="text-xs text-green-600">✓</span>}
                {row.error && <span className="text-xs text-red-500 truncate max-w-[100px]" title={row.error}>✗ failed</span>}
                <button
                  type="button"
                  onClick={() => removeRow(idx)}
                  className="text-gray-300 hover:text-red-400 text-lg leading-none flex-shrink-0"
                >
                  &times;
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Profile */}
        <div>
          <label className="text-sm font-medium text-gray-700 block mb-2">Profile</label>
          <div className="flex gap-4">
            {['balanced', 'quality'].map(p => (
              <label key={p} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="profile"
                  value={p}
                  checked={profile === p}
                  onChange={() => setProfile(p)}
                  className="accent-indigo-600"
                />
                <span className="text-sm capitalize">{p}</span>
                <span className="text-xs text-gray-400">
                  {p === 'balanced' ? '(GPT-4o-mini, $4 cap)' : '(GPT-4o, $8 cap)'}
                </span>
              </label>
            ))}
          </div>
        </div>

        {submitError && (
          <div className="bg-red-50 border border-red-300 text-red-700 text-sm rounded px-3 py-2">
            {submitError}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting || anyUploading || rows.length === 0}
          className="w-full bg-indigo-600 text-white py-2 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {anyUploading ? 'Uploading files…' : submitting ? 'Submitting…' : 'Submit Job'}
        </button>
      </form>
    </div>
  )
}
