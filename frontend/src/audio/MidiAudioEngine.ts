import type { ChannelState, ScoreCISM } from '../types'
import { CANONICAL_11_PARTS } from '../types'

interface ScheduledNote {
  part: string
  startTime: number
  duration: number
  midiPitch: number
  freq: number
  isPiano: boolean
}

interface ActiveVoice {
  osc1: OscillatorNode
  osc2?: OscillatorNode
  gain: GainNode
  stopTime: number
}

export class MidiAudioEngine {
  private audioCtx: AudioContext | null = null
  private masterGain: GainNode | null = null
  private channelGains: Map<string, GainNode> = new Map()
  private channelPanners: Map<string, StereoPannerNode> = new Map()
  private channelStates: Map<string, ChannelState> = new Map()

  private isPlaying: boolean = false
  private startTime: number = 0
  private pauseOffset: number = 0
  private durationSeconds: number = 0
  private syncMap: any = null

  private allNotes: ScheduledNote[] = []
  private nextNoteIndex: number = 0
  private activeVoices: ActiveVoice[] = []

  public onTimeUpdate: ((time: number, measureNumber: number) => void) | null = null
  public onStateChange: ((playing: boolean) => void) | null = null

  private animationFrameId: number | null = null
  private schedulerTimerId: any = null

  constructor() {
    for (const p of CANONICAL_11_PARTS) {
      this.channelStates.set(p, {
        volume: 0.85,
        pan: 0.0,
        muted: false,
        soloed: false,
        amplified: false,
      })
    }
  }

  public initAudio() {
    if (!this.audioCtx) {
      const AudioCtxClass = window.AudioContext || (window as any).webkitAudioContext
      this.audioCtx = new AudioCtxClass()

      this.masterGain = this.audioCtx.createGain()
      this.masterGain.gain.value = 0.95
      this.masterGain.connect(this.audioCtx.destination)

      // Initialize 11 channel strip routing nodes
      for (const p of CANONICAL_11_PARTS) {
        const gain = this.audioCtx.createGain()
        const panner = this.audioCtx.createStereoPanner()

        gain.gain.value = 0.85
        panner.pan.value = 0.0

        gain.connect(panner)
        panner.connect(this.masterGain)

        this.channelGains.set(p, gain)
        this.channelPanners.set(p, panner)
      }

      this.updateChannelGains()
    }

    if (this.audioCtx.state === 'suspended') {
      this.audioCtx.resume().catch((err) => console.warn('AudioContext resume error:', err))
    }
  }

  public async loadScore(
    cismOrUrl: ScoreCISM | string,
    syncMapUrl: string,
    durationSec: number
  ) {
    this.initAudio()
    this.durationSeconds = durationSec || 60
    this.allNotes = []
    this.nextNoteIndex = 0

    // 1. Fetch Sync Map if provided
    if (syncMapUrl) {
      try {
        const resp = await fetch(syncMapUrl)
        if (resp.ok) {
          this.syncMap = await resp.json()
        }
      } catch (e) {
        console.warn('Could not load sync map:', e)
      }
    }

    // 2. Resolve CISM data
    let cismData: ScoreCISM | null = null

    if (typeof cismOrUrl === 'object' && cismOrUrl && 'systems' in cismOrUrl) {
      cismData = cismOrUrl
    } else if (typeof cismOrUrl === 'string') {
      try {
        const resp = await fetch(cismOrUrl)
        if (resp.ok) {
          const json = await resp.json()
          cismData = json.routed_cism || json.raw_cism || json
        }
      } catch (e) {
        console.warn('Could not fetch CISM from URL:', cismOrUrl, e)
      }
    }

    if (cismData && cismData.systems) {
      this.extractNotesFromCISM(cismData)
    }

    // Build fallback sync map if missing
    if (!this.syncMap && cismData) {
      this.buildFallbackSyncMap(cismData)
    }
  }

  private buildFallbackSyncMap(cism: ScoreCISM) {
    const measures: { measure_number: number; start_time_ms: number; duration_ms: number }[] = []
    let cumulativeMs = 0

    for (const sys of cism.systems || []) {
      for (const m of sys.measures || []) {
        const bpm = m.tempo_bpm || 120.0
        const ql = m.quarter_length || 4.0
        const durMs = (ql * (60.0 / bpm)) * 1000.0

        measures.push({
          measure_number: m.measure_number,
          start_time_ms: Math.round(cumulativeMs),
          duration_ms: Math.round(durMs),
        })
        cumulativeMs += durMs
      }
    }

    this.syncMap = { measures }
  }

  public extractNotesFromCISM(cism: ScoreCISM) {
    this.allNotes = []
    let cumulativeSeconds = 0.0

    for (const sys of cism.systems || []) {
      for (const m of sys.measures || []) {
        const bpm = m.tempo_bpm || 120.0
        const barQl = m.quarter_length || 4.0
        const secPerBeat = 60.0 / bpm
        const measureDuration = barQl * secPerBeat

        // Tracks can be in m.tracks (routed) or m.raw_staves (unrouted fallback)
        const trackSource = (m.tracks && Object.keys(m.tracks).length > 0) ? m.tracks : m.raw_staves

        if (trackSource) {
          for (const [partName, trackData] of Object.entries(trackSource)) {
            if (!CANONICAL_11_PARTS.includes(partName as any)) continue
            const isPiano = partName === 'piano'

            for (const el of trackData.elements || []) {
              if (el.is_rest) continue

              const pitchList: string[] = []
              if (el.is_chord && el.chord_pitches && el.chord_pitches.length > 0) {
                pitchList.push(...el.chord_pitches)
              } else if (el.pitch) {
                pitchList.push(el.pitch)
              }

              for (const pStr of pitchList) {
                const midi = (pitchList.length === 1 && el.midi_pitch) ? el.midi_pitch : this.pitchToMidi(pStr)
                if (midi < 20 || midi > 108) continue

                const freq = 440.0 * Math.pow(2.0, (midi - 69) / 12.0)
                const noteStart = cumulativeSeconds + (el.offset_quarters || 0.0) * secPerBeat
                const rawDur = (el.duration_quarters || 1.0) * secPerBeat
                const noteDur = Math.max(0.08, rawDur * 0.95)

                this.allNotes.push({
                  part: partName,
                  startTime: noteStart,
                  duration: noteDur,
                  midiPitch: midi,
                  freq,
                  isPiano,
                })
              }
            }
          }
        }

        cumulativeSeconds += measureDuration
      }
    }

    if (cumulativeSeconds > this.durationSeconds) {
      this.durationSeconds = cumulativeSeconds
    }

    // Sort chronologically for lookahead scheduling
    this.allNotes.sort((a, b) => a.startTime - b.startTime)
  }

  public async play() {
    this.initAudio()
    if (!this.audioCtx) return

    if (this.audioCtx.state === 'suspended') {
      await this.audioCtx.resume()
    }

    if (this.isPlaying) return

    if (this.pauseOffset >= this.durationSeconds && this.durationSeconds > 0) {
      this.pauseOffset = 0
    }

    this.isPlaying = true
    this.startTime = this.audioCtx.currentTime - this.pauseOffset

    // Locate next note to schedule based on pauseOffset
    this.nextNoteIndex = this.findNoteIndexAtTime(this.pauseOffset)

    this.onStateChange?.(true)

    // Start scheduling lookahead loop
    this.scheduleLookahead()
    this.startSchedulerLoop()
    this.startClock()
  }

  public pause() {
    if (!this.isPlaying) return

    this.isPlaying = false
    this.pauseOffset = this.getCurrentTime()
    this.stopActiveVoices()
    this.stopSchedulerLoop()
    this.stopClock()
    this.onStateChange?.(false)
  }

  public stop() {
    this.isPlaying = false
    this.pauseOffset = 0
    this.nextNoteIndex = 0
    this.stopActiveVoices()
    this.stopSchedulerLoop()
    this.stopClock()
    this.onStateChange?.(false)
    this.onTimeUpdate?.(0, 1)
  }

  public seek(seconds: number) {
    const clamped = Math.max(0, Math.min(this.durationSeconds, seconds))
    const wasPlaying = this.isPlaying

    if (wasPlaying) {
      this.stopActiveVoices()
      this.pauseOffset = clamped
      if (this.audioCtx) {
        this.startTime = this.audioCtx.currentTime - clamped
      }
      this.nextNoteIndex = this.findNoteIndexAtTime(clamped)
      this.scheduleLookahead()
      const currentM = this.getMeasureForTime(clamped)
      this.onTimeUpdate?.(clamped, currentM)
    } else {
      this.pauseOffset = clamped
      const currentM = this.getMeasureForTime(clamped)
      this.onTimeUpdate?.(clamped, currentM)
    }
  }

  private findNoteIndexAtTime(timeSec: number): number {
    let low = 0
    let high = this.allNotes.length - 1
    let best = this.allNotes.length

    while (low <= high) {
      const mid = Math.floor((low + high) / 2)
      if (this.allNotes[mid].startTime >= timeSec - 0.05) {
        best = mid
        high = mid - 1
      } else {
        low = mid + 1
      }
    }
    return best
  }

  private startSchedulerLoop() {
    this.stopSchedulerLoop()
    this.schedulerTimerId = setInterval(() => {
      if (this.isPlaying) {
        this.scheduleLookahead()
        this.cleanupVoices()
      }
    }, 40)
  }

  private stopSchedulerLoop() {
    if (this.schedulerTimerId !== null) {
      clearInterval(this.schedulerTimerId)
      this.schedulerTimerId = null
    }
  }

  private scheduleLookahead() {
    if (!this.audioCtx || !this.isPlaying) return

    const lookaheadSec = 1.2
    const currentScoreTime = this.getCurrentTime()
    const scheduleWindowEnd = currentScoreTime + lookaheadSec
    const ctxNow = this.audioCtx.currentTime

    while (
      this.nextNoteIndex < this.allNotes.length &&
      this.allNotes[this.nextNoteIndex].startTime <= scheduleWindowEnd
    ) {
      const note = this.allNotes[this.nextNoteIndex]
      this.nextNoteIndex++

      // Note start relative to AudioContext
      const when = ctxNow + Math.max(0, note.startTime - currentScoreTime)
      const dur = note.duration

      const channelGain = this.channelGains.get(note.part)
      if (channelGain) {
        this.synthesizeNote(note, when, dur, channelGain)
      }
    }
  }

  private synthesizeNote(
    note: ScheduledNote,
    when: number,
    duration: number,
    destNode: AudioNode
  ) {
    if (!this.audioCtx) return

    try {
      const osc1 = this.audioCtx.createOscillator()
      const env = this.audioCtx.createGain()

      // Calculate safe, non-inverted ADSR parameters
      const attack = Math.min(0.04, duration * 0.2)
      const release = Math.min(0.05, duration * 0.2)
      const t0 = when
      const tAttack = t0 + attack
      const tSustainEnd = Math.max(tAttack, t0 + duration - release)
      const tEnd = t0 + duration

      if (note.isPiano) {
        // Piano-like struck harmonic tone (triangle + sub-octave)
        osc1.type = 'triangle'
        osc1.frequency.setValueAtTime(note.freq, t0)

        // Envelope: percussive attack, rapid initial decay to warm sustain
        env.gain.setValueAtTime(0.0001, t0)
        env.gain.linearRampToValueAtTime(0.7, tAttack)
        env.gain.exponentialRampToValueAtTime(0.25, Math.min(tSustainEnd, t0 + 0.15))
        env.gain.exponentialRampToValueAtTime(0.0001, tEnd)

        osc1.connect(env)
        env.connect(destNode)

        osc1.start(t0)
        osc1.stop(tEnd + 0.05)

        this.activeVoices.push({
          osc1,
          gain: env,
          stopTime: tEnd + 0.05,
        })
      } else {
        // Choral Vocal Formant Synth (sawtooth + subtle warm sine octave)
        osc1.type = 'sawtooth'
        osc1.frequency.setValueAtTime(note.freq, t0)

        // Optional second oscillator for vocal richness
        const osc2 = this.audioCtx.createOscillator()
        osc2.type = 'sine'
        osc2.frequency.setValueAtTime(note.freq * 0.5, t0) // undertone warmth

        // Lowpass filter to simulate vocal tract formant resonance
        const filter = this.audioCtx.createBiquadFilter()
        filter.type = 'lowpass'
        filter.frequency.setValueAtTime(Math.min(2400, note.freq * 3.5), t0)
        filter.Q.setValueAtTime(2.0, t0)

        // Vocal ADSR envelope
        env.gain.setValueAtTime(0.0001, t0)
        env.gain.linearRampToValueAtTime(0.45, tAttack) // gentle vocal onset
        env.gain.setValueAtTime(0.38, tSustainEnd)
        env.gain.linearRampToValueAtTime(0.0001, tEnd)

        osc1.connect(filter)
        osc2.connect(filter)
        filter.connect(env)
        env.connect(destNode)

        osc1.start(t0)
        osc2.start(t0)
        osc1.stop(tEnd + 0.05)
        osc2.stop(tEnd + 0.05)

        this.activeVoices.push({
          osc1,
          osc2,
          gain: env,
          stopTime: tEnd + 0.05,
        })
      }
    } catch (err) {
      // Prevent individual note error from interrupting playback
      console.warn('Note synthesis error:', err)
    }
  }

  private cleanupVoices() {
    if (!this.audioCtx) return
    const now = this.audioCtx.currentTime
    this.activeVoices = this.activeVoices.filter((v) => {
      if (v.stopTime <= now) {
        try {
          v.osc1.disconnect()
          v.osc2?.disconnect()
          v.gain.disconnect()
        } catch {
          // ignore
        }
        return false
      }
      return true
    })
  }

  private stopActiveVoices() {
    for (const v of this.activeVoices) {
      try {
        v.gain.gain.setValueAtTime(0, this.audioCtx?.currentTime || 0)
        v.osc1.stop()
        v.osc2?.stop()
        v.osc1.disconnect()
        v.osc2?.disconnect()
        v.gain.disconnect()
      } catch {
        // ignore
      }
    }
    this.activeVoices = []
  }

  public setChannelState(partName: string, state: ChannelState) {
    this.channelStates.set(partName, state)
    this.updateChannelGains()
  }

  public setAllChannelStates(states: Record<string, ChannelState>) {
    for (const [p, st] of Object.entries(states)) {
      this.channelStates.set(p, st)
    }
    this.updateChannelGains()
  }

  public updateChannelGains() {
    if (!this.audioCtx) return

    let hasSolo = false
    this.channelStates.forEach((st) => {
      if (st.soloed) hasSolo = true
    })

    const ctxTime = this.audioCtx.currentTime

    this.channelStates.forEach((state, partName) => {
      const gainNode = this.channelGains.get(partName)
      const pannerNode = this.channelPanners.get(partName)

      if (gainNode) {
        let vol = state.volume
        if (state.amplified) {
          vol *= 1.8 // +5.1 dB boost
        }

        let targetGain = 0
        if (hasSolo) {
          targetGain = (state.soloed && !state.muted) ? vol : 0
        } else {
          targetGain = state.muted ? 0 : vol
        }

        gainNode.gain.cancelScheduledValues(ctxTime)
        gainNode.gain.setValueAtTime(Math.max(0, targetGain), ctxTime)
      }

      if (pannerNode) {
        pannerNode.pan.cancelScheduledValues(ctxTime)
        pannerNode.pan.setValueAtTime(state.pan, ctxTime)
      }
    })
  }

  public setMasterVolume(val: number) {
    if (this.masterGain && this.audioCtx) {
      const clamped = Math.max(0.0, Math.min(1.5, val))
      this.masterGain.gain.cancelScheduledValues(this.audioCtx.currentTime)
      this.masterGain.gain.setValueAtTime(clamped, this.audioCtx.currentTime)
    }
  }

  public getMasterVolume(): number {
    return this.masterGain ? this.masterGain.gain.value : 0.85
  }

  public getCurrentTime(): number {
    if (!this.isPlaying || !this.audioCtx) {
      return this.pauseOffset
    }
    return Math.max(0, this.audioCtx.currentTime - this.startTime)
  }

  private startClock() {
    this.stopClock()
    const loop = () => {
      if (!this.isPlaying) return

      const current = this.getCurrentTime()
      if (this.durationSeconds > 0 && current >= this.durationSeconds) {
        this.stop()
        return
      }

      const currentM = this.getMeasureForTime(current)
      this.onTimeUpdate?.(current, currentM)
      this.animationFrameId = requestAnimationFrame(loop)
    }

    this.animationFrameId = requestAnimationFrame(loop)
  }

  private stopClock() {
    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId)
      this.animationFrameId = null
    }
  }

  public getMeasureForTime(seconds: number): number {
    if (!this.syncMap || !this.syncMap.measures || this.syncMap.measures.length === 0) {
      return 1
    }

    const timeMs = seconds * 1000.0
    for (let i = this.syncMap.measures.length - 1; i >= 0; i--) {
      const m = this.syncMap.measures[i]
      if (timeMs >= m.start_time_ms - 20.0) {
        return m.measure_number
      }
    }
    return 1
  }

  private pitchToMidi(pitchStr: string): number {
    const clean = pitchStr.trim()
    const m = clean.match(/^([A-Ga-g])([#b]?)(-?\d+)$/)
    if (!m) return 60

    const step = m[1].toUpperCase()
    const acc = m[2]
    const oct = parseInt(m[3], 10)
    const noteMap: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }
    let val = noteMap[step] ?? 0
    if (acc === '#') val += 1
    else if (acc === 'b') val -= 1
    return (oct + 1) * 12 + val
  }

  public destroy() {
    this.stop()
    if (this.audioCtx && this.audioCtx.state !== 'closed') {
      this.audioCtx.close().catch(() => {})
    }
  }
}
