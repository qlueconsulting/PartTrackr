import React from 'react'
import { Music2, ShieldCheck, Upload, Sparkles } from 'lucide-react'

interface HeaderProps {
  scoreTitle: string
  composer: string
  measureCount: number
  totalDuration: number
  onOpenAudit: () => void
  onOpenUpload: () => void
  onOpenSamples: () => void
}

export const Header: React.FC<HeaderProps> = ({
  scoreTitle,
  composer,
  measureCount,
  totalDuration,
  onOpenAudit,
  onOpenUpload,
  onOpenSamples,
}) => {
  const formatTime = (secs: number) => {
    const mins = Math.floor(secs / 60)
    const rem = Math.floor(secs % 60)
    return `${mins}:${rem.toString().padStart(2, '0')}`
  }

  return (
    <header className="bg-slate-900/90 backdrop-blur-md border-b border-slate-800 sticky top-0 z-40 px-6 py-3">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
        {/* Brand & Score Info */}
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center shadow-lg shadow-indigo-500/25">
            <Music2 className="w-6 h-6 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-extrabold text-xl tracking-tight text-white">Part<span className="text-indigo-400">Trackr</span></span>
              <span className="text-xs uppercase font-semibold px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                11-Stem Choral OMR
              </span>
            </div>
            <div className="text-sm text-slate-400 flex items-center gap-2 mt-0.5">
              <span className="font-medium text-slate-200">{scoreTitle || 'Untitled Score'}</span>
              {composer && <span className="text-slate-500">• {composer}</span>}
              {measureCount > 0 && (
                <span className="text-xs text-indigo-300 bg-indigo-950/60 px-2 py-0.5 rounded border border-indigo-900">
                  {measureCount} Measures ({formatTime(totalDuration)})
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-3">
          <button
            onClick={onOpenSamples}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition"
          >
            <Sparkles className="w-4 h-4 text-amber-400" />
            <span>Sample Scores</span>
          </button>

          <button
            onClick={onOpenAudit}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-950/50 hover:bg-emerald-900/50 text-emerald-300 border border-emerald-800/60 transition"
          >
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <span>Score Integrity Audit</span>
          </button>

          <button
            onClick={onOpenUpload}
            className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-600/30 transition"
          >
            <Upload className="w-4 h-4" />
            <span>Upload Score</span>
          </button>
        </div>
      </div>
    </header>
  )
}
