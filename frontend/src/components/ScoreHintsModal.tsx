import React, { useState, useEffect } from 'react'
import { Sliders, X, Sparkles, CheckCircle2, AlertCircle, Loader2, Info } from 'lucide-react'
import type { ScoreResponse, ScoreHints } from '../types'

interface ScoreHintsModalProps {
  isOpen: boolean
  onClose: () => void
  score: ScoreResponse | null
  onScoreUpdated: (updatedScore: ScoreResponse) => void
}

export const ScoreHintsModal: React.FC<ScoreHintsModalProps> = ({
  isOpen,
  onClose,
  score,
  onScoreUpdated,
}) => {
  const [totalMeasures, setTotalMeasures] = useState<string>('')
  const [choralVoicing, setChoralVoicing] = useState<string>('SATB')
  const [accompanimentType, setAccompanimentType] = useState<string>('piano')
  const [timeSignature, setTimeSignature] = useState<string>('')
  const [tempoBpm, setTempoBpm] = useState<string>('')
  const [customInstructions, setCustomInstructions] = useState<string>('')

  const [isReprocessing, setIsReprocessing] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  useEffect(() => {
    if (score && isOpen) {
      const hints = score.score_hints || {}
      setTotalMeasures(
        hints.total_measures != null
          ? String(hints.total_measures)
          : score.measure_count > 0
          ? String(score.measure_count)
          : ''
      )
      setChoralVoicing(hints.choral_voicing || 'SATB')
      setAccompanimentType(hints.accompaniment_type || 'piano')
      setTimeSignature(hints.time_signature || score.time_signature || '4/4')
      setTempoBpm(
        hints.tempo_bpm != null
          ? String(hints.tempo_bpm)
          : score.tempo_bpm > 0
          ? String(Math.round(score.tempo_bpm))
          : '120'
      )
      setCustomInstructions(hints.custom_instructions || '')
      setError(null)
      setSuccessMsg(null)
    }
  }, [score, isOpen])

  if (!isOpen || !score) return null

  const handleReprocess = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMsg(null)
    setIsReprocessing(true)

    const payload: ScoreHints = {
      total_measures: totalMeasures.trim() ? parseInt(totalMeasures.trim(), 10) : null,
      choral_voicing: choralVoicing,
      accompaniment_type: accompanimentType,
      time_signature: timeSignature.trim() || null,
      tempo_bpm: tempoBpm.trim() ? parseFloat(tempoBpm.trim()) : null,
      custom_instructions: customInstructions.trim() || null,
    }

    try {
      const res = await fetch(`/api/v1/scores/${score.id}/reprocess`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        let errMsg = `Reprocessing failed (${res.status})`
        try {
          const errData = await res.json()
          errMsg = errData.detail || errMsg
        } catch {
          const rawText = await res.text()
          if (rawText) errMsg = rawText
        }
        throw new Error(errMsg)
      }

      const updated: ScoreResponse = await res.json()
      setSuccessMsg('Score reprocessed successfully!')
      onScoreUpdated(updated)
      setTimeout(() => {
        onClose()
      }, 900)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Reprocessing failed'
      setError(msg)
    } finally {
      setIsReprocessing(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-2xl relative">
        <button
          onClick={onClose}
          disabled={isReprocessing}
          className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition disabled:opacity-40"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Modal Header */}
        <div className="flex items-center gap-2 mb-1">
          <div className="w-8 h-8 rounded-lg bg-violet-500/10 border border-violet-500/20 flex items-center justify-center text-violet-400">
            <Sliders className="w-4 h-4" />
          </div>
          <h3 className="text-lg font-bold text-white">Score Hints & AI Reprocess</h3>
        </div>
        <p className="text-xs text-slate-400 mb-4">
          Guide the notation analysis and voice routing for <strong className="text-slate-200">{score.title}</strong> without waiting for OCR to re-run.
        </p>

        {/* Info Callout */}
        <div className="mb-4 p-3 rounded-lg bg-slate-950/70 border border-slate-800 flex items-start gap-2.5 text-xs text-slate-300">
          <Info className="w-4 h-4 text-indigo-400 flex-shrink-0 mt-0.5" />
          <span>
            <strong>Bypasses OCR:</strong> Edits apply directly to the parsed notation grid and isolated audio stems (~3s). Audiveris is not executed again.
          </span>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {successMsg && (
          <div className="mb-4 p-3 rounded-lg bg-emerald-950/50 border border-emerald-800 text-emerald-300 text-xs flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            <span>{successMsg}</span>
          </div>
        )}

        <form onSubmit={handleReprocess} className="space-y-4">
          {/* Parameter 1: Total Measures */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              1. Total Measures in Score
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min="1"
                max="999"
                value={totalMeasures}
                onChange={(e) => setTotalMeasures(e.target.value)}
                placeholder="e.g. 123"
                className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-indigo-500"
              />
              <span className="text-xs text-slate-400 whitespace-nowrap">
                Currently: {score.measure_count}
              </span>
            </div>
            <p className="text-[11px] text-slate-500 mt-1">
              Locks measure grid to exactly this number, trimming empty trailing bars or padding rests.
            </p>
          </div>

          {/* Parameter 2: Choral Voicing Format */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              2. Choral Voicing & Staff Layout
            </label>
            <select
              value={choralVoicing}
              onChange={(e) => setChoralVoicing(e.target.value)}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-indigo-500"
            >
              <option value="SATB">SATB (Standard 4-Part Choral / Divisi)</option>
              <option value="SA_TB">SA + TB (2-Staff Choral Score)</option>
              <option value="SSAA">SSAA (Women's Choir - Voices S1..A2)</option>
              <option value="TTBB">TTBB (Men's Choir - Voices T1..B2)</option>
              <option value="SAB">SAB (Soprano, Alto, Baritone)</option>
              <option value="Unison">Unison (Doubled across all 10 vocal stems)</option>
              <option value="Auto">Auto (Score Bracket & Clef Detection)</option>
            </select>
            <p className="text-[11px] text-slate-500 mt-1">
              Controls how vocal staves are routed into S1, S2, A1, A2, T1, T2, Bar1, Bar2, B1, B2.
            </p>
          </div>

          {/* Parameter 3: Accompaniment Type */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              3. Accompaniment Type
            </label>
            <select
              value={accompanimentType}
              onChange={(e) => setAccompanimentType(e.target.value)}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-indigo-500"
            >
              <option value="piano">Piano Accompaniment (Curved Brace / Bottom Staves)</option>
              <option value="a_cappella">A Cappella (Pure Voices - Piano Stems 100% Rest)</option>
              <option value="reduction">Piano Reduction (For Rehearsal Only)</option>
              <option value="auto">Auto Detect</option>
            </select>
            <p className="text-[11px] text-slate-500 mt-1">
              Rule A5 guarantee: Selecting A Cappella mutes Piano stem without inventing notes.
            </p>
          </div>

          {/* Parameter 4: Initial Time Signature & Tempo */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                4a. Time Signature
              </label>
              <input
                type="text"
                value={timeSignature}
                onChange={(e) => setTimeSignature(e.target.value)}
                placeholder="4/4, 3/4, 6/8..."
                className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                4b. Starting BPM
              </label>
              <input
                type="number"
                min="30"
                max="300"
                value={tempoBpm}
                onChange={(e) => setTempoBpm(e.target.value)}
                placeholder="120"
                className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          {/* Parameter 5: Custom AI Instructions & Directives */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              5. Custom AI Instructions & Measure Directives (Optional)
            </label>
            <textarea
              rows={3}
              value={customInstructions}
              onChange={(e) => setCustomInstructions(e.target.value)}
              placeholder="e.g. bars 1-4 are a piano prelude; m.25 soprano solo; men rest bars 1-8; piano tacet bars 5-8"
              className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-none font-mono"
            />
            <p className="text-[11px] text-slate-500 mt-1">
              Provides measure directives (e.g. preludes, interludes, solos, or section tacets) to guide AI topology and voice routing.
            </p>
          </div>

          {/* Reprocess Button */}
          <div className="pt-2">
            <button
              type="submit"
              disabled={isReprocessing}
              className="w-full py-2.5 px-4 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white font-bold text-sm shadow-lg shadow-indigo-600/30 flex items-center justify-center gap-2 transition disabled:opacity-50"
            >
              {isReprocessing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Reprocessing Score (~3s)...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4 text-amber-300" />
                  <span>Reprocess Score</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
