import React from 'react'
import { ChannelStrip } from './ChannelStrip'
import type { StemInfo, ChannelState, MeasureInfo } from '../types'
import { Sliders, RotateCcw } from 'lucide-react'

interface StemMixerProps {
  stems: Record<string, StemInfo>
  channelStates: Record<string, ChannelState>
  currentMeasure: MeasureInfo | null
  selectedUserPart: string
  onChannelStateChange: (stemName: string, state: ChannelState) => void
  onResetMix: () => void
}

const STEM_ORDER = [
  'Piano',
  'S1',
  'S2',
  'A1',
  'A2',
  'T1',
  'T2',
  'Bar1',
  'Bar2',
  'B1',
  'B2',
]

export const StemMixer: React.FC<StemMixerProps> = ({
  stems,
  channelStates,
  currentMeasure,
  selectedUserPart,
  onChannelStateChange,
  onResetMix,
}) => {
  const activeParts = currentMeasure?.active_parts || []

  return (
    <div className="bg-slate-950 p-6 flex-1">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Sliders className="w-5 h-5 text-indigo-400" />
            <h2 className="text-base font-bold text-white tracking-tight">
              11-Stem Rehearsal Console
            </h2>
            <span className="text-xs text-slate-500 ml-2">
              (Independent Volume, Pan, Solo, and Mute per Vocal Voice & Piano)
            </span>
          </div>

          <button
            onClick={onResetMix}
            className="flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 transition"
          >
            <RotateCcw className="w-3.5 h-3.5 text-slate-400" />
            <span>Reset Mix</span>
          </button>
        </div>

        {/* 11 Channel Strips Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-11 gap-3">
          {STEM_ORDER.map((stemName) => {
            const stem = stems[stemName]
            if (!stem) return null

            const state = channelStates[stemName] || {
              volume: 0.85,
              pan: stem.default_pan ?? 0.0,
              muted: false,
              soloed: false,
            }

            const isActiveInMeasure = activeParts.includes(stemName)
            const isUserPart = stemName === selectedUserPart

            return (
              <ChannelStrip
                key={stemName}
                stem={stem}
                state={state}
                isActiveInMeasure={isActiveInMeasure}
                isUserPart={isUserPart}
                onVolumeChange={(vol) =>
                  onChannelStateChange(stemName, { ...state, volume: vol })
                }
                onPanChange={(pan) =>
                  onChannelStateChange(stemName, { ...state, pan })
                }
                onToggleMute={() =>
                  onChannelStateChange(stemName, { ...state, muted: !state.muted })
                }
                onToggleSolo={() =>
                  onChannelStateChange(stemName, { ...state, soloed: !state.soloed })
                }
              />
            )
          })}
        </div>
      </div>
    </div>
  )
}
