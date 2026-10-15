import React from 'react'
import { Mic, Compass } from 'lucide-react'
import type { MeasureInfo } from '../types'

interface ActivePartIndicatorProps {
  currentMeasure: MeasureInfo | null
  selectedPart: string
  onSelectPart: (part: string) => void
  onJumpToNextEntrance: () => void
  nextEntranceMeasure: number | null
}

const PART_OPTIONS = [
  { key: 'S1', label: 'S1 (Soprano I)', color: 'text-rose-400' },
  { key: 'S2', label: 'S2 (Soprano II)', color: 'text-rose-400' },
  { key: 'A1', label: 'A1 (Alto I)', color: 'text-purple-400' },
  { key: 'A2', label: 'A2 (Alto II)', color: 'text-purple-400' },
  { key: 'T1', label: 'T1 (Tenor I)', color: 'text-sky-400' },
  { key: 'T2', label: 'T2 (Tenor II)', color: 'text-sky-400' },
  { key: 'Bar1', label: 'Bar1 (Baritone I)', color: 'text-teal-400' },
  { key: 'Bar2', label: 'Bar2 (Baritone II)', color: 'text-teal-400' },
  { key: 'B1', label: 'B1 (Bass I)', color: 'text-emerald-400' },
  { key: 'B2', label: 'B2 (Bass II)', color: 'text-emerald-400' },
]

export const ActivePartIndicator: React.FC<ActivePartIndicatorProps> = ({
  currentMeasure,
  selectedPart,
  onSelectPart,
  onJumpToNextEntrance,
  nextEntranceMeasure,
}) => {
  const activeParts = currentMeasure?.active_parts || []
  const isUserPartActive = activeParts.includes(selectedPart)

  return (
    <div className="bg-slate-900/60 border-b border-slate-800 px-6 py-2.5">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-3 text-xs">
        {/* User Singer Selector */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 text-slate-400 font-medium">
            <Mic className="w-3.5 h-3.5 text-indigo-400" />
            <span>My Part:</span>
          </div>
          <select
            value={selectedPart}
            onChange={(e) => onSelectPart(e.target.value)}
            className="bg-slate-800 text-slate-200 text-xs font-semibold rounded-lg px-2.5 py-1 border border-slate-700 focus:outline-none focus:border-indigo-500"
          >
            {PART_OPTIONS.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>

          {/* Current Part Status */}
          {isUserPartActive ? (
            <span className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-emerald-950/60 text-emerald-300 border border-emerald-800 font-semibold animate-pulse">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              Singing in Measure {currentMeasure?.measure_number}
            </span>
          ) : (
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700 font-medium">
                Resting in Measure {currentMeasure?.measure_number}
              </span>
              {nextEntranceMeasure !== null && (
                <button
                  onClick={onJumpToNextEntrance}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-indigo-950/60 hover:bg-indigo-900/60 text-indigo-300 border border-indigo-800 font-semibold transition"
                >
                  <Compass className="w-3.5 h-3.5 text-indigo-400" />
                  <span>Next Entrance: Bar {nextEntranceMeasure}</span>
                </button>
              )}
            </div>
          )}
        </div>

        {/* Global Measure Singing Matrix */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-slate-500 font-medium mr-1">Active Staves:</span>
          {['Piano', 'S1', 'S2', 'A1', 'A2', 'T1', 'T2', 'Bar1', 'Bar2', 'B1', 'B2'].map((key) => {
            const isActive = activeParts.includes(key)
            const isUser = key === selectedPart

            return (
              <span
                key={key}
                className={`px-2 py-0.5 rounded font-mono font-bold text-[11px] transition ${
                  isActive
                    ? isUser
                      ? 'bg-indigo-600 text-white shadow-sm ring-1 ring-indigo-400'
                      : 'bg-slate-700 text-slate-200'
                    : 'bg-slate-900/40 text-slate-600'
                }`}
              >
                {key}
              </span>
            )
          })}
        </div>
      </div>
    </div>
  )
}
