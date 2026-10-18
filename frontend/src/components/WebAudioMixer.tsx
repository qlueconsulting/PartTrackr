import React from 'react'
import { Sparkles, SlidersHorizontal } from 'lucide-react'
import { CANONICAL_11_PARTS, PART_DISPLAY_NAMES, type ChannelState } from '../types'

interface WebAudioMixerProps {
  channelStates: Record<string, ChannelState>
  onChannelChange: (partName: string, state: ChannelState) => void
  activeParts?: string[]
}

export const WebAudioMixer: React.FC<WebAudioMixerProps> = ({
  channelStates,
  onChannelChange,
  activeParts = []
}) => {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-xl">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="w-4 h-4 text-sky-400" />
          <span className="text-xs uppercase tracking-wider font-semibold text-sky-400">
            11-Part Interactive WebAudio Mixer
          </span>
          <span className="text-xs text-slate-500 font-mono">11 Discrete MIDI Channels</span>
        </div>
      </div>

      <div className="grid grid-cols-11 gap-2">
        {CANONICAL_11_PARTS.map((pName) => {
          const state = channelStates[pName] || {
            volume: 0.85,
            pan: 0.0,
            muted: false,
            soloed: false,
            amplified: false,
          }
          const isActive = activeParts.includes(pName)

          const toggleMute = () => onChannelChange(pName, { ...state, muted: !state.muted })
          const toggleSolo = () => onChannelChange(pName, { ...state, soloed: !state.soloed })
          const toggleAmplify = () => onChannelChange(pName, { ...state, amplified: !state.amplified })

          return (
            <div
              key={pName}
              className={`flex flex-col items-center p-2 rounded-lg border border-slate-800 bg-slate-950/80 transition-all duration-200 ${
                state.soloed ? 'ring-2 ring-amber-400' : ''
              } ${state.muted ? 'opacity-40' : 'opacity-100'}`}
            >
              {/* Part Name & Active indicator */}
              <div className="flex items-center gap-1 mb-1.5">
                <div
                  className={`w-2 h-2 rounded-full transition-all duration-150 ${
                    isActive ? 'bg-emerald-400 ring-2 ring-emerald-400/50 shadow-sm' : 'bg-slate-700'
                  }`}
                />
                <span className="text-[11px] font-bold text-slate-200 truncate max-w-[70px]">
                  {PART_DISPLAY_NAMES[pName]}
                </span>
              </div>

              {/* Solo & Mute Buttons */}
              <div className="flex gap-1 w-full mb-2">
                <button
                  onClick={toggleSolo}
                  className={`flex-1 py-0.5 rounded text-[10px] font-bold uppercase transition-colors cursor-pointer ${
                    state.soloed ? 'bg-amber-400 text-slate-950' : 'bg-slate-800 text-slate-400 hover:text-amber-300'
                  }`}
                >
                  S
                </button>
                <button
                  onClick={toggleMute}
                  className={`flex-1 py-0.5 rounded text-[10px] font-bold uppercase transition-colors cursor-pointer ${
                    state.muted ? 'bg-rose-500 text-white' : 'bg-slate-800 text-slate-400 hover:text-rose-300'
                  }`}
                >
                  M
                </button>
              </div>

              {/* Amplify (+6dB) Toggle */}
              <button
                onClick={toggleAmplify}
                className={`w-full py-0.5 mb-2 rounded text-[9px] font-bold flex items-center justify-center gap-0.5 transition-colors cursor-pointer ${
                  state.amplified
                    ? 'bg-purple-600 text-white ring-1 ring-purple-400'
                    : 'bg-slate-800/80 text-slate-400 hover:text-purple-300'
                }`}
              >
                <Sparkles className="w-2.5 h-2.5" />
                <span>+dB</span>
              </button>

              {/* Vertical Fader */}
              <div className="h-28 flex items-center justify-center my-1">
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={state.volume}
                  onChange={(e) =>
                    onChannelChange(pName, { ...state, volume: parseFloat(e.target.value) })
                  }
                  className="w-24 -rotate-90 appearance-none bg-slate-800 h-1.5 rounded-full cursor-pointer accent-sky-400"
                />
              </div>

              {/* Pan Slider */}
              <div className="w-full mt-2">
                <div className="flex justify-between text-[8px] text-slate-500 font-mono mb-0.5">
                  <span>L</span>
                  <span>C</span>
                  <span>R</span>
                </div>
                <input
                  type="range"
                  min="-1"
                  max="1"
                  step="0.1"
                  value={state.pan}
                  onChange={(e) =>
                    onChannelChange(pName, { ...state, pan: parseFloat(e.target.value) })
                  }
                  className="w-full appearance-none bg-slate-800 h-1 rounded-full cursor-pointer accent-slate-400"
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
