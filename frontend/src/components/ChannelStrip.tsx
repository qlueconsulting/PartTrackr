import React from 'react'
import { Download, FileCode } from 'lucide-react'
import type { StemInfo, ChannelState } from '../types'

interface ChannelStripProps {
  stem: StemInfo
  state: ChannelState
  isActiveInMeasure: boolean
  isUserPart: boolean
  onVolumeChange: (vol: number) => void
  onPanChange: (pan: number) => void
  onToggleMute: () => void
  onToggleSolo: () => void
}

const SECTION_THEMES: Record<string, { badgeBg: string; text: string; border: string }> = {
  accompaniment: { badgeBg: 'bg-amber-950/40', text: 'text-amber-400', border: 'border-amber-800/60' },
  soprano: { badgeBg: 'bg-rose-950/40', text: 'text-rose-400', border: 'border-rose-800/60' },
  alto: { badgeBg: 'bg-purple-950/40', text: 'text-purple-400', border: 'border-purple-800/60' },
  tenor: { badgeBg: 'bg-sky-950/40', text: 'text-sky-400', border: 'border-sky-800/60' },
  baritone: { badgeBg: 'bg-teal-950/40', text: 'text-teal-400', border: 'border-teal-800/60' },
  bass: { badgeBg: 'bg-emerald-950/40', text: 'text-emerald-400', border: 'border-emerald-800/60' },
}

export const ChannelStrip: React.FC<ChannelStripProps> = ({
  stem,
  state,
  isActiveInMeasure,
  isUserPart,
  onVolumeChange,
  onPanChange,
  onToggleMute,
  onToggleSolo,
}) => {
  const theme = SECTION_THEMES[stem.category] || SECTION_THEMES.accompaniment
  const volPct = Math.round(state.volume * 100)

  // Pan display: -1.0 is L100, 0 is Center, 1.0 is R100
  const panLabel =
    state.pan === 0
      ? 'C'
      : state.pan < 0
      ? `L${Math.round(Math.abs(state.pan) * 100)}`
      : `R${Math.round(state.pan * 100)}`

  return (
    <div
      className={`rounded-xl border p-3 flex flex-col justify-between transition ${
        isUserPart
          ? 'bg-slate-900 border-indigo-500/80 shadow-lg shadow-indigo-600/10 ring-1 ring-indigo-500/40'
          : 'bg-slate-900/90 border-slate-800 hover:border-slate-700'
      }`}
    >
      {/* Top Header: Stem Name & Category */}
      <div>
        <div className="flex items-center justify-between gap-1 mb-1.5">
          <span
            className={`font-mono text-sm font-extrabold tracking-tight ${theme.text}`}
          >
            {stem.name}
          </span>

          {/* Activity status dot */}
          <div className="flex items-center gap-1">
            {isActiveInMeasure ? (
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse shadow-sm shadow-emerald-400/50" title="Singing in this measure" />
            ) : (
              <span className="w-2.5 h-2.5 rounded-full bg-slate-800" title="Resting" />
            )}
          </div>
        </div>

        <p className="text-[11px] text-slate-400 truncate mb-3" title={stem.display_name}>
          {stem.display_name}
        </p>
      </div>

      {/* Solo / Mute Buttons */}
      <div className="grid grid-cols-2 gap-1.5 mb-3">
        <button
          onClick={onToggleSolo}
          className={`py-1 text-xs font-bold rounded-lg border transition ${
            state.soloed
              ? 'bg-amber-500 text-slate-950 border-amber-400 shadow-md shadow-amber-500/30'
              : 'bg-slate-800/80 text-slate-400 hover:text-slate-200 border-slate-700'
          }`}
        >
          SOLO
        </button>

        <button
          onClick={onToggleMute}
          className={`py-1 text-xs font-bold rounded-lg border transition ${
            state.muted
              ? 'bg-rose-600 text-white border-rose-500 shadow-md shadow-rose-600/30'
              : 'bg-slate-800/80 text-slate-400 hover:text-slate-200 border-slate-700'
          }`}
        >
          MUTE
        </button>
      </div>

      {/* Volume Slider & readout */}
      <div className="space-y-1 mb-3">
        <div className="flex items-center justify-between text-[11px] text-slate-400">
          <span>Vol</span>
          <span className="font-mono text-slate-200 font-semibold">{volPct}%</span>
        </div>
        <input
          type="range"
          min="0"
          max="1"
          step="0.01"
          value={state.volume}
          onChange={(e) => onVolumeChange(parseFloat(e.target.value))}
          className="w-full accent-indigo-500 h-1.5 bg-slate-800 rounded-lg cursor-pointer"
        />
      </div>

      {/* Pan Slider & readout */}
      <div className="space-y-1 mb-3">
        <div className="flex items-center justify-between text-[11px] text-slate-400">
          <span>Pan</span>
          <span className="font-mono text-slate-200 font-semibold">{panLabel}</span>
        </div>
        <input
          type="range"
          min="-1"
          max="1"
          step="0.05"
          value={state.pan}
          onChange={(e) => onPanChange(parseFloat(e.target.value))}
          className="w-full accent-violet-500 h-1.5 bg-slate-800 rounded-lg cursor-pointer"
        />
        <div className="flex justify-between text-[9px] text-slate-600 font-mono">
          <span>L</span>
          <span>C</span>
          <span>R</span>
        </div>
      </div>

      {/* Notation & MIDI Downloads */}
      <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[10px]">
        <a
          href={stem.musicxml_url}
          download={`${stem.name}.musicxml`}
          className="flex items-center gap-1 text-slate-400 hover:text-indigo-400 transition"
          title="Download MusicXML for this stem"
        >
          <FileCode className="w-3 h-3" />
          <span>XML</span>
        </a>

        <a
          href={stem.midi_url}
          download={`${stem.name}.mid`}
          className="flex items-center gap-1 text-slate-400 hover:text-indigo-400 transition"
          title="Download MIDI for this stem"
        >
          <Download className="w-3 h-3" />
          <span>MIDI</span>
        </a>
      </div>
    </div>
  )
}
