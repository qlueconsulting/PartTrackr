import React from 'react'
import type { MeasureInfo } from '../types'

interface MeasureTimelineProps {
  analysis: MeasureInfo[]
  currentTime: number
  totalDuration: number
  currentMeasureNumber: number
  loopA: number | null
  loopB: number | null
  onSeekToTime: (time: number) => void
  onSeekToMeasure: (measureNum: number) => void
}

export const MeasureTimeline: React.FC<MeasureTimelineProps> = ({
  analysis,
  currentTime,
  totalDuration,
  currentMeasureNumber,
  loopA,
  loopB,
  onSeekToTime,
  onSeekToMeasure,
}) => {
  const progressPercent = totalDuration > 0 ? (currentTime / totalDuration) * 100 : 0

  const handleTimelineClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const clickX = e.clientX - rect.left
    const ratio = Math.max(0, Math.min(1, clickX / rect.width))
    onSeekToTime(ratio * totalDuration)
  }

  return (
    <div className="bg-slate-950 px-6 py-4 border-b border-slate-800">
      <div className="max-w-7xl mx-auto space-y-2">
        {/* Continuous Scrub Bar */}
        <div
          onClick={handleTimelineClick}
          className="relative h-2.5 bg-slate-800 rounded-full cursor-pointer group overflow-hidden"
        >
          {/* Loop A-B shaded region */}
          {loopA !== null && loopB !== null && totalDuration > 0 && (
            <div
              className="absolute top-0 bottom-0 bg-indigo-500/20 border-x border-indigo-500"
              style={{
                left: `${(loopA / totalDuration) * 100}%`,
                width: `${((loopB - loopA) / totalDuration) * 100}%`,
              }}
            />
          )}

          {/* Played progress */}
          <div
            className="h-full bg-gradient-to-r from-indigo-600 to-violet-500 transition-all duration-75"
            style={{ width: `${progressPercent}%` }}
          />

          {/* Hover highlight */}
          <div className="absolute inset-0 group-hover:bg-white/5 transition pointer-events-none" />
        </div>

        {/* Measure Blocks Grid */}
        <div className="flex gap-1 overflow-x-auto pb-1 pt-1 scrollbar-thin">
          {analysis.map((m) => {
            const isCurrent = m.measure_number === currentMeasureNumber
            const hasVoices = m.active_parts.some((p) => p !== 'Piano')
            const hasPiano = m.active_parts.includes('Piano')
            const isInterlude = hasPiano && !hasVoices

            return (
              <button
                key={m.measure_number}
                onClick={() => onSeekToMeasure(m.measure_number)}
                title={`Measure ${m.measure_number} (${m.time_signature}) - Active: ${m.active_parts.join(', ')}`}
                className={`flex-1 min-w-[56px] px-2 py-1.5 rounded-lg border text-left transition flex flex-col justify-between ${
                  isCurrent
                    ? 'bg-indigo-600/30 border-indigo-500 shadow-md shadow-indigo-600/20'
                    : 'bg-slate-900/80 hover:bg-slate-800 border-slate-800/80 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span
                    className={`font-mono text-xs font-bold ${
                      isCurrent ? 'text-indigo-300' : 'text-slate-300'
                    }`}
                  >
                    m.{m.measure_number}
                  </span>
                  <span className="text-[10px] text-slate-500 font-mono">
                    {m.start_time_seconds.toFixed(1)}s
                  </span>
                </div>

                {/* Section tags */}
                <div className="flex items-center gap-1 mt-1">
                  {isInterlude ? (
                    <span className="text-[9px] uppercase tracking-wider font-semibold px-1 rounded bg-amber-950/60 text-amber-400 border border-amber-900/60">
                      Piano
                    </span>
                  ) : hasVoices ? (
                    <div className="flex gap-0.5">
                      {m.active_parts.includes('S1') && <span className="w-1.5 h-1.5 rounded-full bg-rose-400" title="Soprano" />}
                      {m.active_parts.includes('A1') && <span className="w-1.5 h-1.5 rounded-full bg-purple-400" title="Alto" />}
                      {m.active_parts.includes('T1') && <span className="w-1.5 h-1.5 rounded-full bg-sky-400" title="Tenor" />}
                      {m.active_parts.includes('B1') && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" title="Bass" />}
                    </div>
                  ) : (
                    <span className="text-[9px] text-slate-600">Rest</span>
                  )}
                </div>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
