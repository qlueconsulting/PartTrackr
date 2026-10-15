import type { ChannelState } from '../types'

export interface TrackNodeGroup {
  source: AudioBufferSourceNode | null
  gain: GainNode
  panner: StereoPannerNode
  buffer: AudioBuffer | null
}

export type TimeUpdateCallback = (currentTime: number, progressRatio: number) => void
export type StateChangeCallback = (isPlaying: boolean) => void
export type LoadingProgressCallback = (loaded: number, total: number) => void

export class MultiTrackPlayer {
  private ctx: AudioContext | null = null
  private tracks: Map<string, TrackNodeGroup> = new Map()
  private channelStates: Map<string, ChannelState> = new Map()
  
  private masterGain: GainNode | null = null
  private isPlaying: boolean = false
  private startTime: number = 0
  private pauseOffset: number = 0
  private duration: number = 0
  private playbackRate: number = 1.0
  private masterVolume: number = 1.0

  // A/B Looping
  public loopA: number | null = null
  public loopB: number | null = null
  public isLooping: boolean = false

  // Callbacks
  public onTimeUpdate: TimeUpdateCallback | null = null
  public onStateChange: StateChangeCallback | null = null
  public onLoadingProgress: LoadingProgressCallback | null = null

  private animationFrameId: number | null = null

  constructor() {
    // AudioContext is initialized on first user gesture
  }

  private initContext() {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      this.ctx = new AudioCtx()
      this.masterGain = this.ctx.createGain()
      this.masterGain.gain.value = this.masterVolume
      this.masterGain.connect(this.ctx.destination)
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume()
    }
  }

  public async loadStems(stems: Record<string, { audio_url: string; default_pan?: number }>): Promise<void> {
    this.stop()
    this.initContext()
    if (!this.ctx || !this.masterGain) return

    this.tracks.clear()
    const stemEntries = Object.entries(stems)
    const total = stemEntries.length
    let loadedCount = 0

    const loadPromises = stemEntries.map(async ([stemName, info]) => {
      try {
        const res = await fetch(info.audio_url)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const arrayBuffer = await res.arrayBuffer()
        const audioBuffer = await this.ctx!.decodeAudioData(arrayBuffer)

        // Create routing nodes: Gain -> Panner -> MasterGain
        const gain = this.ctx!.createGain()
        const panner = this.ctx!.createStereoPanner()
        const defaultPan = info.default_pan ?? 0.0

        panner.pan.value = defaultPan
        gain.connect(panner)
        panner.connect(this.masterGain!)

        this.tracks.set(stemName, {
          source: null,
          gain,
          panner,
          buffer: audioBuffer,
        })

        if (audioBuffer.duration > this.duration) {
          this.duration = audioBuffer.duration
        }

        // Initialize state if not present
        if (!this.channelStates.has(stemName)) {
          this.channelStates.set(stemName, {
            volume: 0.85,
            pan: defaultPan,
            muted: false,
            soloed: false,
          })
        }
      } catch (err) {
        console.warn(`Could not load stem audio for ${stemName}:`, err)
      } finally {
        loadedCount++
        this.onLoadingProgress?.(loadedCount, total)
      }
    })

    await Promise.all(loadPromises)
    this.updateGains()
  }

  public play() {
    this.initContext()
    if (this.isPlaying || !this.ctx || this.tracks.size === 0) return

    // Clamp pauseOffset
    if (this.pauseOffset >= this.duration) {
      this.pauseOffset = 0
    }

    // Check loop boundaries
    if (this.isLooping && this.loopA !== null && this.loopB !== null) {
      if (this.pauseOffset < this.loopA || this.pauseOffset >= this.loopB) {
        this.pauseOffset = this.loopA
      }
    }

    this.startTime = this.ctx.currentTime - (this.pauseOffset / this.playbackRate)

    // Create and start a source node for every stem
    this.tracks.forEach((trackNode) => {
      if (!trackNode.buffer) return

      const source = this.ctx!.createBufferSource()
      source.buffer = trackNode.buffer
      source.playbackRate.value = this.playbackRate
      source.connect(trackNode.gain)

      source.start(0, this.pauseOffset)
      trackNode.source = source
    })

    this.isPlaying = true
    this.onStateChange?.(true)
    this.startClock()
  }

  public pause() {
    if (!this.isPlaying || !this.ctx) return

    this.pauseOffset = this.getCurrentTime()
    this.stopSources()
    this.isPlaying = false
    this.onStateChange?.(false)
    this.stopClock()
  }

  public stop() {
    this.stopSources()
    this.pauseOffset = 0
    this.isPlaying = false
    this.onStateChange?.(false)
    this.stopClock()
    this.onTimeUpdate?.(0, 0)
  }

  public seek(targetSeconds: number) {
    const clamped = Math.max(0, Math.min(targetSeconds, this.duration))
    const wasPlaying = this.isPlaying

    if (wasPlaying) {
      this.stopSources()
      this.pauseOffset = clamped
      this.play()
    } else {
      this.pauseOffset = clamped
      const ratio = this.duration > 0 ? clamped / this.duration : 0
      this.onTimeUpdate?.(clamped, ratio)
    }
  }

  public setPlaybackRate(rate: number) {
    this.playbackRate = Math.max(0.5, Math.min(rate, 2.0))
    if (this.isPlaying && this.ctx) {
      const current = this.getCurrentTime()
      this.startTime = this.ctx.currentTime - (current / this.playbackRate)
      this.tracks.forEach((track) => {
        if (track.source) {
          track.source.playbackRate.value = this.playbackRate
        }
      })
    }
  }

  public setMasterVolume(vol: number) {
    this.masterVolume = Math.max(0, Math.min(vol, 1.0))
    if (this.masterGain && this.ctx) {
      this.masterGain.gain.setValueAtTime(this.masterVolume, this.ctx.currentTime)
    }
  }

  public setChannelState(stemName: string, state: ChannelState) {
    this.channelStates.set(stemName, state)
    const track = this.tracks.get(stemName)
    if (track && this.ctx) {
      track.panner.pan.setValueAtTime(state.pan, this.ctx.currentTime)
    }
    this.updateGains()
  }

  private updateGains() {
    if (!this.ctx) return

    // Check if any stem is currently soloed
    let hasSolo = false
    this.channelStates.forEach((st) => {
      if (st.soloed) hasSolo = true
    })

    this.tracks.forEach((trackNode, name) => {
      const st = this.channelStates.get(name) || { volume: 0.85, pan: 0, muted: false, soloed: false }
      let targetGain = 0

      if (hasSolo) {
        targetGain = st.soloed && !st.muted ? st.volume : 0
      } else {
        targetGain = st.muted ? 0 : st.volume
      }

      trackNode.gain.gain.setValueAtTime(targetGain, this.ctx!.currentTime)
    })
  }

  public setLoop(a: number | null, b: number | null, enabled: boolean) {
    this.loopA = a
    this.loopB = b
    this.isLooping = enabled
  }

  public getCurrentTime(): number {
    if (!this.isPlaying || !this.ctx) {
      return this.pauseOffset
    }
    return (this.ctx.currentTime - this.startTime) * this.playbackRate
  }

  public getDuration(): number {
    return this.duration
  }

  private stopSources() {
    this.tracks.forEach((track) => {
      if (track.source) {
        try {
          track.source.stop()
          track.source.disconnect()
        } catch {
          // ignore already stopped sources
        }
        track.source = null
      }
    })
  }

  private startClock() {
    this.stopClock()
    const loop = () => {
      if (!this.isPlaying) return

      const current = this.getCurrentTime()

      // Handle A/B loop jump
      if (this.isLooping && this.loopA !== null && this.loopB !== null && this.loopB > this.loopA) {
        if (current >= this.loopB) {
          this.seek(this.loopA)
          return
        }
      }

      // Handle end of playback
      if (current >= this.duration && this.duration > 0) {
        this.stop()
        return
      }

      const ratio = this.duration > 0 ? Math.min(current / this.duration, 1.0) : 0
      this.onTimeUpdate?.(current, ratio)
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

  public destroy() {
    this.stop()
    if (this.ctx && this.ctx.state !== 'closed') {
      this.ctx.close()
    }
  }
}
