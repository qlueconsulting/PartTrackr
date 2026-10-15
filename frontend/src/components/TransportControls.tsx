import React from 'react'
import {
  Play,
  Pause,
  Square,
  RotateCcw,
  Volume2,
  VolumeX,
  Gauge,
  Repeat,
  Compass,
} from 'lucide-react'

interface TransportControlsProps {
  isPlaying: boolean
  currentTime: number
  totalDuration: number
  currentMeasure: number
  totalMeasures: number
  tempoBpm: number
  timeSignature: string
  masterVolume: number
  playbackRate: number
  loopA: number | null
  loopB: number | null
  isLooping: boolean
  selectedPart: string
  hasEntranceAhead: boolean
  onPlay: () => void
  onPause: () => void
  onStop: () => void
  onRewind: () => void
  onVolumeChange: (vol: number) => void
  onRateChange: (rate: number) => void
  onSetLoopA: () => void
  onSetLoopB: () => void
  onToggleLoop: () => void
  onClearLoop: () => void
  onJumpToNextEntrance: () => void
}

export const TransportControls: React.FC<TransportControlsProps> = ({
  isPlaying,
  currentTime,
  totalDuration,
  currentMeasure,
  totalMeasures,
  tempoBpm,
  timeSignature,
  masterVolume,
  playbackRate,
  loopA,
  loopB,
  isLooping,
  selectedPart,
  hasEntranceAhead,
  onPlay,
  onPause,
  onStop,
  onRewind,
  onVolumeChange,
  onRateChange,
  onSetLoopA,
  onSetLoopB,
  onToggleLoop,
  onClearLoop,
  onJumpToNextEntrance,
}) => {
  const formatTime = (secs: number) => {
    const mins = Math.floor(secs / 60)
    const rem = Math.floor(secs % 60)
    const tenths = Math.floor((secs % 1) * 10)
    return `${mins}:${rem.toString().padStart(2, '0')}.${tenths}`
  }

  return (
    <div className="bg-slate-900 border-y border-slate-800 px-6 py-3.5 shadow-xl">
      <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
        {/* Playback Transport Buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={onRewind}
            title="Rewind to start"
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
          >
            <RotateCcw className="w-4 h-4" />
          </button>

          <button
            onClick={isPlaying ? onPause : onPlay}
            title={isPlaying ? 'Pause' : 'Play'}
            className="p-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/30 transition transform active:scale-95"
          >
            {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5 ml-0.5" />}
          </button>

          <button
            onClick={onStop}
            title="Stop"
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
          >
            <Square className="w-4 h-4" />
          </button>

          {/* Time & Measure readout */}
          <div className="ml-3 pl-3 border-l border-slate-800 flex items-center gap-3">
            <div className="font-mono text-sm tracking-tight">
              <span className="text-white font-bold">{formatTime(currentTime)}</span>
              <span className="text-slate-500"> / {formatTime(totalDuration)}</span>
            </div>

            <div className="flex items-center gap-2 text-xs">
              <span className="bg-slate-800 text-indigo-400 font-semibold px-2 py-0.5 rounded border border-slate-700">
                Bar {currentMeasure || 1} / {totalMeasures || 1}
              </span>
              <span className="bg-slate-800/60 text-slate-400 px-1.5 py-0.5 rounded">
                {timeSignature || '4/4'}
              </span>
              <span className="bg-slate-800/60 text-slate-400 px-1.5 py-0.5 rounded">
                ♩={Math.round(tempoBpm) || 120}
              </span>
            </div>
          </div>
        </div>

        {/* Jump to Next Entrance Button */}
        <div className="flex items-center gap-2">
          <button
            onClick={onJumpToNextEntrance}
            disabled={!hasEntranceAhead}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
              hasEntranceAhead
                ? 'bg-amber-950/40 hover:bg-amber-900/40 text-amber-300 border-amber-800/70 shadow-sm'
                : 'bg-slate-900 text-slate-600 border-slate-800 cursor-not-allowed'
            }`}
          >
            <Compass className="w-4 h-4 text-amber-400" />
            <span>Jump to Next Entrance ({selectedPart})</span>
          </button>
        </div>

        {/* A/B Loop Controls */}
        <div className="flex items-center gap-1.5 bg-slate-950/60 px-2.5 py-1.5 rounded-xl border border-slate-800 text-xs">
          <Repeat className={`w-3.5 h-3.5 ${isLooping ? 'text-indigo-400' : 'text-slate-500'}`} />
          <button
            onClick={onSetLoopA}
            className={`px-2 py-0.5 rounded font-mono font-medium transition ${
              loopA !== null ? 'bg-indigo-600/30 text-indigo-300 border border-indigo-500/40' : 'text-slate-400 hover:text-white'
            }`}
          >
            A: {loopA !== null ? `${loopA.toFixed(1)}s` : '--'}
          </button>
          <span className="text-slate-600">→</span>
          <button
            onClick={onSetLoopB}
            className={`px-2 py-0.5 rounded font-mono font-medium transition ${
              loopB !== null ? 'bg-indigo-600/30 text-indigo-300 border border-indigo-500/40' : 'text-slate-400 hover:text-white'
            }`}
          >
            B: {loopB !== null ? `${loopB.toFixed(1)}s` : '--'}
          </button>

          {(loopA !== null || loopB !== null) && (
            <>
              <button
                onClick={onToggleLoop}
                className={`px-2 py-0.5 rounded font-semibold transition ${
                  isLooping ? 'bg-indigo-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                }`}
              >
                {isLooping ? 'Loop ON' : 'Loop OFF'}
              </button>
              <button
                onClick={onClearLoop}
                className="text-[11px] text-slate-500 hover:text-slate-300 ml-1 px-1"
              >
                Clear
              </button>
            </>
          )}
        </div>

        {/* Master Speed & Volume Controls */}
        <div className="flex items-center gap-4">
          {/* Playback Speed */}
          <div className="flex items-center gap-1.5">
            <Gauge className="w-4 h-4 text-slate-400" />
            <select
              value={playbackRate}
              onChange={(e) => onRateChange(parseFloat(e.target.value))}
              className="bg-slate-800 text-slate-200 text-xs rounded-lg px-2 py-1 border border-slate-700 focus:outline-none focus:border-indigo-500"
            >
              <option value="0.5">0.5×</option>
              <option value="0.75">0.75×</option>
              <option value="1.0">1.0× (Normal)</option>
              <option value="1.25">1.25×</option>
              <option value="1.5">1.5×</option>
            </select>
          </div>

          {/* Master Volume */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => onVolumeChange(masterVolume > 0 ? 0 : 0.85)}
              className="text-slate-400 hover:text-white"
            >
              {masterVolume === 0 ? <VolumeX className="w-4 h-4 text-rose-400" /> : <Volume2 className="w-4 h-4" />}
            </button>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={masterVolume}
              onChange={(e) => onVolumeChange(parseFloat(e.target.value))}
              className="w-20 accent-indigo-500 h-1.5 bg-slate-800 rounded-lg cursor-pointer"
            />
            <span className="font-mono text-xs text-slate-400 w-8">
              {Math.round(masterVolume * 100)}%
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
