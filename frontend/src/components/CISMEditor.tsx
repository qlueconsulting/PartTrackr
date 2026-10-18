import React, { useState, useEffect } from 'react'
import { Code, Save, RefreshCw, Check } from 'lucide-react'
import type { JobData, MeasureData } from '../types'

interface CISMEditorProps {
  job: JobData
  selectedMeasureNumber: number | null
  onOverrideSaved: (updatedJob: any) => void
}

export const CISMEditor: React.FC<CISMEditorProps> = ({
  job,
  selectedMeasureNumber,
  onOverrideSaved
}) => {
  const [jsonText, setJsonText] = useState<string>('')
  const [isSaving, setIsSaving] = useState<boolean>(false)
  const [saveSuccess, setSaveSuccess] = useState<boolean>(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const routedCism = job.routed_cism
  let currentMeasure: MeasureData | null = null

  if (routedCism && selectedMeasureNumber) {
    for (const sys of routedCism.systems) {
      for (const m of sys.measures) {
        if (m.measure_number === selectedMeasureNumber) {
          currentMeasure = m
          break
        }
      }
    }
  }

  useEffect(() => {
    if (currentMeasure) {
      setJsonText(JSON.stringify(currentMeasure, null, 2))
      setErrorMsg(null)
    } else {
      setJsonText('{\n  "message": "Click any measure box in the PDF view or timeline to inspect its CISM JSON."\n}')
    }
  }, [selectedMeasureNumber, job.routed_cism])

  const handleApplyOverride = async () => {
    if (!selectedMeasureNumber) return
    setIsSaving(true)
    setErrorMsg(null)

    try {
      const parsed = JSON.parse(jsonText)
      const overrides = {
        ...(job.overrides || {}),
        [selectedMeasureNumber.toString()]: parsed,
      }

      const res = await fetch(`/api/v1/jobs/${job.job_id}/override`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ overrides }),
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to apply voice routing override')
      }

      const data = await res.json()
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2000)
      onOverrideSaved(data)
    } catch (err: any) {
      setErrorMsg(err.message || 'Invalid JSON syntax')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl flex flex-col h-full">
      <div className="bg-slate-950/80 px-4 py-2.5 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Code className="w-4 h-4 text-sky-400" />
          <span className="text-xs uppercase tracking-wider font-semibold text-sky-400">
            CISM JSON & Voice Routing Editor
          </span>
          {selectedMeasureNumber && (
            <span className="text-xs px-2 py-0.5 bg-sky-950 text-sky-300 border border-sky-800 rounded font-mono">
              Measure {selectedMeasureNumber}
            </span>
          )}
        </div>

        <button
          onClick={handleApplyOverride}
          disabled={!selectedMeasureNumber || isSaving}
          className="flex items-center gap-1.5 px-3 py-1 bg-sky-600 hover:bg-sky-500 disabled:opacity-40 text-white rounded text-xs font-semibold shadow transition-all duration-150 cursor-pointer"
        >
          {isSaving ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          ) : saveSuccess ? (
            <Check className="w-3.5 h-3.5 text-emerald-200" />
          ) : (
            <Save className="w-3.5 h-3.5" />
          )}
          {saveSuccess ? 'Applied!' : 'Apply Override & Re-Compile'}
        </button>
      </div>

      {errorMsg && (
        <div className="px-4 py-2 bg-rose-950/70 border-b border-rose-800 text-rose-300 text-xs font-mono">
          {errorMsg}
        </div>
      )}

      <div className="flex-1 p-2 bg-slate-950">
        <textarea
          value={jsonText}
          onChange={(e) => setJsonText(e.target.value)}
          spellCheck={false}
          className="w-full h-full bg-slate-900/90 text-slate-200 font-mono text-xs p-3 rounded-lg border border-slate-800 focus:outline-none focus:border-sky-500 resize-none selection:bg-sky-500/30 leading-relaxed"
        />
      </div>
    </div>
  )
}
