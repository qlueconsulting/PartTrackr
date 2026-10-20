import React, { useState, useEffect } from 'react'
import {
  X,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Music,
  Clock,
  Layers,
  RefreshCw,
} from 'lucide-react'
import type { JobData, ScoreHints, PreflightData } from '../types'

interface ScoreHintsModalProps {
  isOpen: boolean
  onClose: () => void
  job: JobData | null
  onReprocessTriggered?: (jobId: string, hints: ScoreHints) => void
}

const QUICK_HINT_CHIPS = [
  '🎹 Bottom 2 staves are piano only',
  '⏱️ Measure 1 is a pick-up bar',
  '🎵 6/8 meter in 2 feel',
  '👥 Divisi Soprano on chorus',
  '🔇 Men tacet measures 1-16',
  '🎺 Piano prelude bars 1-4',
  '🎼 SA + TB on 2 staves with piano accompaniment',
]

export const ScoreHintsModal: React.FC<ScoreHintsModalProps> = ({
  isOpen,
  onClose,
  job,
  onReprocessTriggered,
}) => {
  const [totalMeasures, setTotalMeasures] = useState<string>('')
  const [choralVoicing, setChoralVoicing] = useState<string>('SATB')
  const [accompanimentType, setAccompanimentType] = useState<string>('piano')
  const [timeSignature, setTimeSignature] = useState<string>('4/4')
  const [tempoBpm, setTempoBpm] = useState<string>('120')
  const [stavesPerSystem, setStavesPerSystem] = useState<string>('3')
  const [customInstructions, setCustomInstructions] = useState<string>('')
  const [saveAsTemplate, setSaveAsTemplate] = useState<boolean>(true)

  const [preflightData, setPreflightData] = useState<PreflightData | null>(null)
  const [isLoadingPreflight, setIsLoadingPreflight] = useState<boolean>(false)
  const [isReprocessing, setIsReprocessing] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  useEffect(() => {
    if (job && isOpen) {
      setError(null)
      setSuccessMsg(null)

      const hints = (job.score_hints as any) || {}
      setTimeSignature(hints.time_signature || '4/4')
      setTempoBpm(hints.tempo_bpm ? String(Math.round(hints.tempo_bpm)) : '120')
      setChoralVoicing(hints.choral_voicing || 'SATB')
      setAccompanimentType(hints.accompaniment_type || (hints.has_piano ? 'piano' : 'auto'))
      setStavesPerSystem(hints.staves_per_system ? String(hints.staves_per_system) : '3')
      setTotalMeasures(
        hints.total_measures != null
          ? String(hints.total_measures)
          : job.total_measures > 0
          ? String(job.total_measures)
          : ''
      )
      const initialInstructions = hints.custom_instructions || hints.suggested_custom_instructions || ''
      setCustomInstructions(initialInstructions)

      if (hints.part_layout_summary) {
        setPreflightData({
          title: hints.title || job.title,
          composer: hints.composer || job.composer,
          page_count: hints.page_count || job.page_count,
          time_signature: hints.time_signature || '4/4',
          tempo_bpm: hints.tempo_bpm || 120,
          choral_voicing: hints.choral_voicing || 'SATB',
          accompaniment_type: hints.accompaniment_type || 'piano',
          has_piano: Boolean(hints.has_piano),
          staves_per_system: hints.staves_per_system || 3,
          part_layout_summary: hints.part_layout_summary,
          custom_instructions: hints.custom_instructions,
          suggested_custom_instructions: hints.suggested_custom_instructions || hints.custom_instructions,
          learned_style_match: hints.learned_style_match || null,
        })
      } else {
        // Fetch fresh preflight analysis
        fetchPreflight(job.job_id)
      }
    }
  }, [job, isOpen])

  const fetchPreflight = async (jobId: string) => {
    try {
      setIsLoadingPreflight(true)
      const res = await fetch(`/api/v1/jobs/${jobId}/preflight`)
      if (res.ok) {
        const data: PreflightData = await res.json()
        setPreflightData(data)
        if (data.time_signature) setTimeSignature(data.time_signature)
        if (data.tempo_bpm) setTempoBpm(String(Math.round(data.tempo_bpm)))
        if (data.choral_voicing) setChoralVoicing(data.choral_voicing)
        if (data.accompaniment_type) setAccompanimentType(data.accompaniment_type)
        if (data.staves_per_system) setStavesPerSystem(String(data.staves_per_system))
        if (data.suggested_custom_instructions && !customInstructions) {
          setCustomInstructions(data.suggested_custom_instructions)
        }
      }
    } catch (e) {
      console.warn('Could not fetch preflight analysis:', e)
    } finally {
      setIsLoadingPreflight(false)
    }
  }

  if (!isOpen || !job) return null

  const handleChipClick = (chipText: string) => {
    // Strip emoji from the chip for clean AI prompt text
    const cleanText = chipText.replace(/^[^\w\s]+\s*/, '')
    setCustomInstructions((prev) => {
      const trimmed = prev.trim()
      if (!trimmed) return cleanText
      if (trimmed.includes(cleanText)) return prev // Already present
      return `${trimmed}; ${cleanText}`
    })
  }

  const handleReprocess = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMsg(null)
    setIsReprocessing(true)

    const payload: ScoreHints = {
      total_measures: totalMeasures.trim() ? parseInt(totalMeasures.trim(), 10) : null,
      choral_voicing: choralVoicing,
      accompaniment_type: accompanimentType,
      time_signature: timeSignature.trim() || '4/4',
      tempo_bpm: tempoBpm.trim() ? parseFloat(tempoBpm.trim()) : 120.0,
      staves_per_system: stavesPerSystem && stavesPerSystem !== 'auto' ? parseInt(stavesPerSystem, 10) : undefined,
      custom_instructions: customInstructions.trim() || null,
      save_as_template: saveAsTemplate,
    }

    try {
      const res = await fetch(`/api/v1/jobs/${job.job_id}/reprocess`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        let errMsg = `Reprocessing request failed (${res.status})`
        try {
          const errData = await res.json()
          errMsg = errData.detail || errMsg
        } catch {
          const rawText = await res.text()
          if (rawText) errMsg = rawText
        }
        throw new Error(errMsg)
      }

      setSuccessMsg('Pipeline re-execution dispatched with AI hints!')
      if (onReprocessTriggered) {
        onReprocessTriggered(job.job_id, payload)
      }
      setTimeout(() => {
        onClose()
      }, 700)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Reprocessing failed'
      setError(msg)
    } finally {
      setIsReprocessing(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-700/80 rounded-2xl max-w-xl w-full p-6 shadow-2xl relative max-h-[92vh] overflow-y-auto">
        {/* Close Button */}
        <button
          onClick={onClose}
          disabled={isReprocessing}
          className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition disabled:opacity-40"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Modal Header */}
        <div className="flex items-center gap-2.5 mb-1.5">
          <div className="w-9 h-9 rounded-xl bg-violet-500/20 border border-violet-500/30 flex items-center justify-center text-violet-400">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              Score AI Helps & Reprocess
            </h3>
            <p className="text-xs text-slate-400">
              Guide OMR topology, time signature, tempo, and voice isolation for{' '}
              <strong className="text-slate-200">{job.title || 'the current piece'}</strong>
            </p>
          </div>
        </div>

        {/* Cursory Pre-Flight Analysis Banner */}
        <div className="my-4 p-3.5 rounded-xl bg-slate-950/80 border border-violet-900/40 shadow-inner">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-violet-400 flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5" />
              Cursory Pre-Flight Detection (Page 1)
            </span>
            {isLoadingPreflight && (
              <span className="text-[11px] text-slate-400 flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                Scanning...
              </span>
            )}
          </div>

          {preflightData?.learned_style_match && (
            <div className="mb-2 p-2 rounded-lg bg-emerald-950/80 border border-emerald-500/40 text-emerald-300 text-xs flex items-center justify-between">
              <span className="flex items-center gap-1.5 font-semibold">
                <Sparkles className="w-4 h-4 text-emerald-400" />
                Learned Style Matched: {preflightData.learned_style_match.name}
              </span>
              <span className="font-mono bg-emerald-900/60 text-emerald-200 px-2 py-0.5 rounded text-[11px] font-bold">
                {Math.round(preflightData.learned_style_match.confidence * 100)}% match
              </span>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <div className="bg-slate-900/90 border border-slate-800 rounded-lg p-2 text-center">
              <span className="text-[10px] text-slate-400 block mb-0.5">Time Signature</span>
              <span className="font-mono font-bold text-amber-300 text-sm">
                {preflightData?.time_signature || timeSignature || '4/4'}
              </span>
            </div>
            <div className="bg-slate-900/90 border border-slate-800 rounded-lg p-2 text-center">
              <span className="text-[10px] text-slate-400 block mb-0.5">Starting Tempo</span>
              <span className="font-mono font-bold text-emerald-400 text-sm">
                {preflightData?.tempo_bpm ? `${Math.round(preflightData.tempo_bpm)} BPM` : `${tempoBpm} BPM`}
              </span>
            </div>
            <div className="bg-slate-900/90 border border-slate-800 rounded-lg p-2 text-center">
              <span className="text-[10px] text-slate-400 block mb-0.5">Staff Layout</span>
              <span className="font-bold text-indigo-300 text-xs truncate block">
                {preflightData?.choral_voicing || choralVoicing}
              </span>
            </div>
            <div className="bg-slate-900/90 border border-slate-800 rounded-lg p-2 text-center">
              <span className="text-[10px] text-slate-400 block mb-0.5">Accompaniment</span>
              <span className="font-bold text-sky-300 text-xs truncate block">
                {preflightData?.has_piano ? 'Piano Accompaniment' : 'A Cappella'}
              </span>
            </div>
          </div>

          {preflightData?.part_layout_summary && (
            <div className="mt-2 text-[11px] text-slate-300 border-t border-slate-800/80 pt-2 flex items-center gap-1.5">
              <span className="text-violet-400 font-semibold">Layout:</span>
              <span className="text-slate-300">{preflightData.part_layout_summary}</span>
            </div>
          )}
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-rose-950/60 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {successMsg && (
          <div className="mb-4 p-3 rounded-lg bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            <span>{successMsg}</span>
          </div>
        )}

        <form onSubmit={handleReprocess} className="space-y-4">
          {/* Parameter 1: Time Signature & Tempo */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1 flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-amber-400" />
                1. Time Signature
              </label>
              <input
                type="text"
                value={timeSignature}
                onChange={(e) => setTimeSignature(e.target.value)}
                placeholder="4/4, 6/8, 3/4, 2/4..."
                className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1 flex items-center gap-1.5">
                <Music className="w-3.5 h-3.5 text-emerald-400" />
                2. Starting BPM
              </label>
              <input
                type="number"
                min="30"
                max="300"
                value={tempoBpm}
                onChange={(e) => setTempoBpm(e.target.value)}
                placeholder="120"
                className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          {/* Parameter 2: Staves Per System & Choral Voicing */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-indigo-400" />
                3. Staves Per System
              </label>
              <select
                value={stavesPerSystem}
                onChange={(e) => setStavesPerSystem(e.target.value)}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-indigo-500 cursor-pointer"
              >
                <option value="3">3 Staves (Top: Vocal, Bottom 2: Piano)</option>
                <option value="4">4 Staves (SA + TB on 2 staves + Piano)</option>
                <option value="2">2 Staves (A Cappella SA/TB or Piano Solo)</option>
                <option value="1">1 Staff (Lead Sheet / Solo Melody)</option>
                <option value="auto">Auto (Detect from Layout)</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-indigo-400" />
                4. Choral Voicing
              </label>
              <select
                value={choralVoicing}
                onChange={(e) => setChoralVoicing(e.target.value)}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-indigo-500 cursor-pointer"
              >
                <option value="SATB">SATB (Standard 4-Part Choral / Divisi)</option>
                <option value="Tenor_Bass">Tenor & Bass / Men's Chorus (Solo Male / TB)</option>
                <option value="SA_TB">SA + TB (2-Staff Choral Score)</option>
                <option value="SSAA">SSAA (Women's Choir - Voices S1..A2)</option>
                <option value="TTBB">TTBB (Men's Choir - Voices T1..B2)</option>
                <option value="SAB">SAB (Soprano, Alto, Baritone)</option>
                <option value="Unison">Unison (Doubled across vocal stems)</option>
                <option value="Auto">Auto (Score Bracket & Clef Detection)</option>
              </select>
            </div>
          </div>

          {/* Parameter 3: Accompaniment Type */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              5. Accompaniment Type
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
              Guarantees bottom staves are cleanly separated from vocal lines.
            </p>
          </div>

          {/* Parameter 4: Optional Total Measures Clamp */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              6. Total Measures (Optional Clamp)
            </label>
            <input
              type="number"
              min="1"
              max="999"
              value={totalMeasures}
              onChange={(e) => setTotalMeasures(e.target.value)}
              placeholder="e.g. 56 (Leave blank for automatic detection)"
              className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-indigo-500"
            />
          </div>

          {/* Parameter 5: Additional Information AI Prompt & Directives */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1 flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-violet-300">
                <Sparkles className="w-3.5 h-3.5 text-amber-300" />
                7. Additional Information AI Prompt (Custom LLM Guidance)
              </span>
              <div className="flex items-center gap-2">
                {preflightData?.suggested_custom_instructions && (
                  <button
                    type="button"
                    onClick={() => setCustomInstructions(preflightData.suggested_custom_instructions || '')}
                    className="text-[11px] text-violet-400 hover:text-violet-300 underline cursor-pointer font-normal"
                    title="Reset to synthesized pre-flight directives"
                  >
                    Reset to AI Suggestions
                  </button>
                )}
                <span className="text-[10px] text-slate-500">Injected directly into Vision OMR</span>
              </div>
            </label>

            {/* Quick Hint Chips */}
            <div className="flex flex-wrap gap-1.5 mb-2">
              {QUICK_HINT_CHIPS.map((chip, idx) => (
                <button
                  type="button"
                  key={idx}
                  onClick={() => handleChipClick(chip)}
                  className="text-[11px] px-2.5 py-1 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700/80 transition flex items-center gap-1"
                >
                  {chip}
                </button>
              ))}
            </div>

            <textarea
              rows={3}
              value={customInstructions}
              onChange={(e) => setCustomInstructions(e.target.value)}
              placeholder="e.g. Bottom 2 staves are piano accompaniment; bars 1-4 are a piano prelude; measure 25 has soprano solo; tenor rests bars 1-8..."
              className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-violet-500 resize-none font-mono"
            />
            <p className="text-[11px] text-slate-500 mt-1">
              Add any piece-specific context to guide note extraction, tacet measures, or solo sections.
            </p>
          </div>

          {/* Self-Learning Blueprint Persistence */}
          <div className="flex items-start gap-2.5 p-3 rounded-xl bg-violet-950/40 border border-violet-800/50">
            <input
              type="checkbox"
              id="saveAsTemplate"
              checked={saveAsTemplate}
              onChange={(e) => setSaveAsTemplate(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-slate-700 text-violet-600 focus:ring-violet-500 bg-slate-950 cursor-pointer"
            />
            <label htmlFor="saveAsTemplate" className="text-xs text-slate-300 cursor-pointer select-none">
              <span className="font-semibold text-white flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-amber-300" />
                Save as Learned Style Template
              </span>
              <span className="text-[11px] text-slate-400 block mt-0.5">
                Enables PartTrackr to learn this composer's format permanently and auto-apply these facts to future scores with zero second-guessing.
              </span>
            </label>
          </div>

          {/* Reprocess Button */}
          <div className="pt-2">
            <button
              type="submit"
              disabled={isReprocessing}
              className="w-full py-3 px-4 rounded-xl bg-gradient-to-r from-violet-600 via-indigo-600 to-purple-600 hover:from-violet-500 hover:via-indigo-500 hover:to-purple-500 text-white font-bold text-sm shadow-lg shadow-indigo-600/30 flex items-center justify-center gap-2 transition disabled:opacity-50"
            >
              {isReprocessing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Reprocessing with AI Helps...</span>
                </>
              ) : (
                <>
                  <RefreshCw className="w-4 h-4 text-amber-300" />
                  <span>Reprocess Score with AI Helps</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
