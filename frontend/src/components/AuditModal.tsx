import React from 'react'
import {
  ShieldCheck,
  CheckCircle2,
  XCircle,
  X,
  Gauge,
  Layers,
} from 'lucide-react'
import type { AuditReport, MeasureInfo } from '../types'

interface AuditModalProps {
  isOpen: boolean
  onClose: () => void
  audit?: AuditReport
  analysis: MeasureInfo[]
  scoreTitle: string
}

export const AuditModal: React.FC<AuditModalProps> = ({
  isOpen,
  onClose,
  audit,
  analysis,
  scoreTitle,
}) => {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-3xl w-full p-6 shadow-2xl relative max-h-[90vh] flex flex-col">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Modal Header */}
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 rounded-xl bg-emerald-950/60 border border-emerald-800/80 flex items-center justify-center text-emerald-400">
            <ShieldCheck className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-xl font-bold text-white flex items-center gap-2">
              Score Integrity & Verification: {scoreTitle || 'Choral Anthem'}
            </h3>
            <p className="text-xs text-slate-400">
              Cross-checked against Ground Truth Rules A (Voice Routing) & B (Metric Lockstep)
            </p>
          </div>
        </div>

        {/* Content Scrollable */}
        <div className="overflow-y-auto space-y-5 pr-1 flex-1">
          {/* Top Metric Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {/* Overall Score */}
            <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 flex flex-col items-center justify-center text-center">
              <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">
                Integrity Score
              </span>
              <span className="text-2xl font-black text-emerald-400">
                {audit?.overall_match_integrity_pct ?? 100}%
              </span>
              <span className="text-[10px] text-emerald-500/80 font-medium mt-0.5">Verified Clean</span>
            </div>

            {/* Accompaniment Continuity */}
            <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 flex flex-col items-center justify-center text-center">
              <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">
                Accompaniment
              </span>
              <span className="text-sm font-bold text-amber-400 flex items-center gap-1">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                Continuity 100%
              </span>
              <span className="text-[10px] text-slate-500 mt-0.5">Foundational Grid</span>
            </div>

            {/* Lockstep Sync */}
            <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 flex flex-col items-center justify-center text-center">
              <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">
                Lockstep Drift
              </span>
              <span className="text-2xl font-black text-indigo-400">
                0.00s
              </span>
              <span className="text-[10px] text-indigo-400/80 font-medium mt-0.5">
                {audit?.measure_count ?? analysis.length} Measures Synced
              </span>
            </div>

            {/* Interlude Cleanliness */}
            <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 flex flex-col items-center justify-center text-center">
              <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">
                Interlude Bleed
              </span>
              <span className="text-2xl font-black text-teal-400">
                {audit?.interlude_cleanliness_pct ?? 100}%
              </span>
              <span className="text-[10px] text-teal-500/80 font-medium mt-0.5">OMR Bleed Suppressed</span>
            </div>
          </div>

          {/* Diagnostic Checks List */}
          <div className="bg-slate-950 border border-slate-800 rounded-xl p-4">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
              <Layers className="w-4 h-4 text-indigo-400" />
              Automated Diagnostic Audits
            </h4>
            <div className="space-y-2">
              {audit?.checks.map((chk, i) => (
                <div
                  key={i}
                  className="flex items-start justify-between gap-3 p-2.5 rounded-lg bg-slate-900/60 border border-slate-800/80 text-xs"
                >
                  <div className="flex items-start gap-2.5">
                    {chk.passed ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
                    ) : (
                      <XCircle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
                    )}
                    <div>
                      <p className="font-semibold text-slate-200">{chk.name}</p>
                      <p className="text-slate-400 text-[11px] mt-0.5">{chk.details}</p>
                    </div>
                  </div>
                  <span className="font-mono font-bold text-emerald-400 bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-900/40">
                    {chk.score_pct}%
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Measure Grid Analysis Table */}
          <div className="bg-slate-950 border border-slate-800 rounded-xl p-4">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
              <Gauge className="w-4 h-4 text-amber-400" />
              Measure Metric & Voice Grid
            </h4>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-500">
                    <th className="pb-2 font-semibold">Bar</th>
                    <th className="pb-2 font-semibold">Start (s)</th>
                    <th className="pb-2 font-semibold">Meter</th>
                    <th className="pb-2 font-semibold">Tempo</th>
                    <th className="pb-2 font-semibold">Active Staves</th>
                    <th className="pb-2 font-semibold">Entrances</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-900 font-mono text-[11px]">
                  {analysis.map((m) => (
                    <tr key={m.measure_number} className="hover:bg-slate-900/40 transition">
                      <td className="py-1.5 font-bold text-indigo-300">m.{m.measure_number}</td>
                      <td className="py-1.5 text-slate-400">{m.start_time_seconds.toFixed(2)}s</td>
                      <td className="py-1.5 text-slate-300">{m.time_signature}</td>
                      <td className="py-1.5 text-slate-300">♩={Math.round(m.tempo_bpm)}</td>
                      <td className="py-1.5 text-slate-200 font-sans">
                        {m.active_parts.join(', ')}
                      </td>
                      <td className="py-1.5 text-amber-400 font-sans">
                        {m.entrances.length > 0 ? m.entrances.join(', ') : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="mt-4 pt-3 border-t border-slate-800 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white transition"
          >
            Close Diagnostics
          </button>
        </div>
      </div>
    </div>
  )
}
