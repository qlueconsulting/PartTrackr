import React, { useState, useRef, useEffect } from 'react'
import { Upload, FileMusic, Sparkles, X, AlertCircle, Loader2, Cpu, ChevronDown, ChevronUp, Sliders } from 'lucide-react'
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
  const [isUploading, setIsUploading] = useState(false)
  const [uploadingFileName, setUploadingFileName] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [aiStatus, setAiStatus] = useState<{ ollama_connected?: boolean; ollama_models?: string[] } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Optional Score Hints State
  const [showHints, setShowHints] = useState<boolean>(false)
  const [totalMeasures, setTotalMeasures] = useState<string>('')
  const [choralVoicing, setChoralVoicing] = useState<string>('SATB')
  const [accompanimentType, setAccompanimentType] = useState<string>('piano')
  const [timeSignature, setTimeSignature] = useState<string>('')
  const [tempoBpm, setTempoBpm] = useState<string>('')
  const [customInstructions, setCustomInstructions] = useState<string>('')

  useEffect(() => {
    if (isOpen) {
      fetch('/api/v1/mcp/status')
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => setAiStatus(d))
        .catch(() => {})
    }
  }, [isOpen])

  if (!isOpen) return null

  const busy = isLoading || isUploading

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
    if (busy) return
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      await uploadFile(e.dataTransfer.files[0])
    }
  }

  const handleChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (busy) return
    if (e.target.files && e.target.files[0]) {
      const selected = e.target.files[0]
      e.target.value = ''
      await uploadFile(selected)
    }
  }

  const uploadFile = async (file: File) => {
    setError(null)
    setIsUploading(true)
    setUploadingFileName(file.name)
    const formData = new FormData()
    formData.append('file', file)

    const hintsPayload: Record<string, unknown> = {}
    if (totalMeasures.trim()) hintsPayload.total_measures = parseInt(totalMeasures.trim(), 10)
    if (choralVoicing) hintsPayload.choral_voicing = choralVoicing
    if (accompanimentType) hintsPayload.accompaniment_type = accompanimentType
    if (timeSignature.trim()) hintsPayload.time_signature = timeSignature.trim()
    if (tempoBpm.trim()) hintsPayload.tempo_bpm = parseFloat(tempoBpm.trim())
    if (customInstructions.trim()) hintsPayload.custom_instructions = customInstructions.trim()

    if (Object.keys(hintsPayload).length > 0) {
      formData.append('hints', JSON.stringify(hintsPayload))
    }

    try {
      const res = await fetch('/api/v1/scores/upload', {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) {
        let errMsg = `Upload failed (${res.status})`
        try {
          const errData = await res.json()
          errMsg = errData.detail || errMsg
        } catch {
          const rawText = await res.text()
          if (rawText) {
            errMsg = rawText.replace(/<[^>]*>?/gm, '').trim() || rawText
          }
        }
        throw new Error(errMsg)
      }
      const data: ScoreResponse = await res.json()
      await onScoreLoaded(data)
      onClose()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Upload failed'
      setError(msg)
    } finally {
      setIsUploading(false)
      setUploadingFileName('')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-2xl relative max-h-[92vh] overflow-y-auto">
        <button
          onClick={onClose}
          disabled={busy}
          className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition disabled:opacity-40"
        >
          <X className="w-5 h-5" />
        </button>

        <h3 className="text-xl font-bold text-white mb-1 flex items-center gap-2">
          <FileMusic className="w-6 h-6 text-indigo-400" />
          Upload Choral Sheet Music
        </h3>
        <p className="text-sm text-slate-400 mb-3">
          Accepts PDF (SMuFL Vector + Audiveris OMR + AI Choral Routing), MusicXML (.musicxml, .xml, .mxl), or MIDI (.mid).
        </p>

        {/* Real-Time AI & OMR Engine Badge */}
        <div className="mb-3 px-3 py-2 rounded-lg bg-slate-950/80 border border-slate-800 flex items-center justify-between text-xs">
          <span className="flex items-center gap-1.5 text-slate-300 font-medium">
            <Cpu className="w-3.5 h-3.5 text-emerald-400" />
            Real-Time SMuFL + AI Topology Analyzer
          </span>
          <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold">
            {aiStatus?.ollama_connected
              ? `Local GPU Ollama (${aiStatus.ollama_models?.[0] || 'Ready'})`
              : 'Embedded SMuFL + OMR Ready'}
          </span>
        </div>

        {/* Collapsible Score Hints Accordion */}
        <div className="mb-4 border border-slate-800 rounded-xl bg-slate-950/60 overflow-hidden">
          <button
            type="button"
            onClick={() => setShowHints(!showHints)}
            className="w-full px-3 py-2 text-xs font-semibold text-slate-300 hover:text-white flex items-center justify-between bg-slate-900/60 transition"
          >
            <span className="flex items-center gap-1.5">
              <Sliders className="w-3.5 h-3.5 text-violet-400" />
              Optional Score Hints (Measures, Voicing, Accompaniment)
            </span>
            {showHints ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
          </button>

          {showHints && (
            <div className="p-3 border-t border-slate-800 space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[11px] font-medium text-slate-400 mb-1">Total Measures</label>
                  <input
                    type="number"
                    min="1"
                    value={totalMeasures}
                    onChange={(e) => setTotalMeasures(e.target.value)}
                    placeholder="e.g. 123"
                    className="w-full px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-indigo-500 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-400 mb-1">Voicing</label>
                  <select
                    value={choralVoicing}
                    onChange={(e) => setChoralVoicing(e.target.value)}
                    className="w-full px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-indigo-500 text-xs"
                  >
                    <option value="SATB">SATB</option>
                    <option value="SA_TB">SA + TB (2-Staff)</option>
                    <option value="SSAA">SSAA (Women)</option>
                    <option value="TTBB">TTBB (Men)</option>
                    <option value="SAB">SAB</option>
                    <option value="Unison">Unison</option>
                    <option value="Auto">Auto Detect</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[11px] font-medium text-slate-400 mb-1">Accompaniment</label>
                  <select
                    value={accompanimentType}
                    onChange={(e) => setAccompanimentType(e.target.value)}
                    className="w-full px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-indigo-500 text-xs"
                  >
                    <option value="piano">Piano Accompaniment</option>
                    <option value="a_cappella">A Cappella (0 note piano)</option>
                    <option value="reduction">Piano Reduction</option>
                    <option value="auto">Auto Detect</option>
                  </select>
                </div>
                <div className="grid grid-cols-2 gap-1.5">
                  <div>
                    <label className="block text-[11px] font-medium text-slate-400 mb-1">Meter</label>
                    <input
                      type="text"
                      value={timeSignature}
                      onChange={(e) => setTimeSignature(e.target.value)}
                      placeholder="4/4"
                      className="w-full px-2 py-1.5 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-indigo-500 text-xs"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium text-slate-400 mb-1">BPM</label>
                    <input
                      type="number"
                      value={tempoBpm}
                      onChange={(e) => setTempoBpm(e.target.value)}
                      placeholder="120"
                      className="w-full px-2 py-1.5 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-indigo-500 text-xs"
                    />
                  </div>
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">
                  Custom AI Directives / Measure Instructions (Optional)
                </label>
                <textarea
                  rows={2}
                  value={customInstructions}
                  onChange={(e) => setCustomInstructions(e.target.value)}
                  placeholder="e.g. bars 1-4 are a piano prelude; m.25 soprano solo; men rest bars 1-8"
                  className="w-full px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 text-xs resize-none font-mono"
                />
              </div>
            </div>
          )}
        </div>

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
          onClick={() => !busy && fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-8 text-center transition ${
            busy
              ? 'border-indigo-500/60 bg-indigo-950/20 cursor-wait'
              : dragActive
              ? 'border-indigo-500 bg-indigo-950/20 cursor-pointer'
              : 'border-slate-700 hover:border-slate-500 bg-slate-950/50 cursor-pointer'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.musicxml,.xml,.mxl,.mid,.midi"
            onChange={handleChange}
            className="hidden"
          />

          {busy ? (
            <div className="flex flex-col items-center justify-center py-4">
              <Loader2 className="w-10 h-10 text-indigo-400 animate-spin mb-3" />
              <p className="text-sm font-semibold text-white">
                {isUploading ? `Analyzing "${uploadingFileName}"...` : 'Processing Score...'}
              </p>
              <p className="text-xs text-indigo-300 mt-1 max-w-xs">
                {statusMessage ||
                  'Extracting staves, barlines, multi-measure rests, routing 11 voices & synthesizing audio stems...'}
              </p>
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
              disabled={busy}
              onClick={() => {
                onLoadSample('anthem')
                onClose()
              }}
              className="p-3 rounded-lg bg-slate-800/80 hover:bg-slate-800 border border-slate-700 text-left transition group disabled:opacity-40"
            >
              <p className="text-xs font-bold text-white group-hover:text-indigo-400 transition">
                Choral Anthem of Hope
              </p>
              <p className="text-[11px] text-slate-400 mt-0.5">
                SATB + Piano intro/interlude & divisi
              </p>
            </button>

            <button
              disabled={busy}
              onClick={() => {
                onLoadSample('unison')
                onClose()
              }}
              className="p-3 rounded-lg bg-slate-800/80 hover:bg-slate-800 border border-slate-700 text-left transition group disabled:opacity-40"
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
