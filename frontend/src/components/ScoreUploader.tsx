import React, { useState, useRef } from 'react'
import { Upload, FileMusic, Sparkles, X, AlertCircle, Loader2 } from 'lucide-react'
import type { ScoreResponse } from '../types'

interface ScoreUploaderProps {
  isOpen: boolean
  onClose: () => void
  onScoreLoaded: (score: ScoreResponse) => void
  onLoadSample: (key: string) => void
  isLoading: boolean
  statusMessage?: string
}

export const ScoreUploader: React.FC<ScoreUploaderProps> = ({
  isOpen,
  onClose,
  onScoreLoaded,
  onLoadSample,
  isLoading,
  statusMessage,
}) => {
  const [dragActive, setDragActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  if (!isOpen) return null

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true)
    } else if (e.type === 'dragleave') {
      setDragActive(false)
    }
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      await uploadFile(e.dataTransfer.files[0])
    }
  }

  const handleChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      await uploadFile(e.target.files[0])
    }
  }

  const uploadFile = async (file: File) => {
    setError(null)
    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch('/api/v1/scores/upload', {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Upload failed')
      }
      const data: ScoreResponse = await res.json()
      onScoreLoaded(data)
      onClose()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Upload failed'
      setError(msg)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-2xl relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
        >
          <X className="w-5 h-5" />
        </button>

        <h3 className="text-xl font-bold text-white mb-1 flex items-center gap-2">
          <FileMusic className="w-6 h-6 text-indigo-400" />
          Upload Choral Sheet Music
        </h3>
        <p className="text-sm text-slate-400 mb-5">
          Accepts PDF (Audiveris OMR), MusicXML (.musicxml, .xml, .mxl), or MIDI (.mid).
        </p>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-sm flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Dropzone */}
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition ${
            dragActive
              ? 'border-indigo-500 bg-indigo-950/20'
              : 'border-slate-700 hover:border-slate-500 bg-slate-950/50'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.musicxml,.xml,.mxl,.mid,.midi"
            onChange={handleChange}
            className="hidden"
          />

          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-4">
              <Loader2 className="w-10 h-10 text-indigo-400 animate-spin mb-3" />
              <p className="text-sm font-semibold text-white">Processing Score...</p>
              <p className="text-xs text-indigo-300 mt-1 max-w-xs">{statusMessage || 'Extracting 11 stems & synthesizing audio'}</p>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center">
              <div className="w-12 h-12 rounded-full bg-indigo-500/10 flex items-center justify-center mb-3 text-indigo-400">
                <Upload className="w-6 h-6" />
              </div>
              <p className="text-sm font-medium text-slate-200">
                Click to browse or drag and drop your sheet music
              </p>
              <p className="text-xs text-slate-500 mt-1">
                PDF, MusicXML, MXL, XML, or MIDI up to 50MB
              </p>
            </div>
          )}
        </div>

        {/* Fast Samples */}
        <div className="mt-6 pt-5 border-t border-slate-800">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
            Or Try a Curated Sample Score
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            <button
              onClick={() => {
                onLoadSample('anthem')
                onClose()
              }}
              className="p-3 rounded-lg bg-slate-800/80 hover:bg-slate-800 border border-slate-700 text-left transition group"
            >
              <p className="text-xs font-bold text-white group-hover:text-indigo-400 transition">
                Choral Anthem of Hope
              </p>
              <p className="text-[11px] text-slate-400 mt-0.5">
                SATB + Piano intro/interlude & divisi
              </p>
            </button>

            <button
              onClick={() => {
                onLoadSample('unison')
                onClose()
              }}
              className="p-3 rounded-lg bg-slate-800/80 hover:bg-slate-800 border border-slate-700 text-left transition group"
            >
              <p className="text-xs font-bold text-white group-hover:text-indigo-400 transition">
                Unison & Divisi Study
              </p>
              <p className="text-[11px] text-slate-400 mt-0.5">
                Dynamic Men/Women unisons & 2-staff routing
              </p>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
