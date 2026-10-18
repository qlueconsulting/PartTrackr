import type { ChannelState } from '../types'

export class MidiAudioEngine {
  private audioCtx: AudioContext | null = null
  private isPlaying: boolean = false
  private startTime: number = 0
  private pauseOffset: number = 0
  private durationSeconds: number = 0
  private syncMap: any = null

  public onTimeUpdate: ((time: number, measureNumber: number) => void) | null = null
  public onStateChange: ((playing: boolean) => void) | null = null

  private animationFrameId: number | null = null

  constructor() {
    // Lazy AudioContext initialization
  }

  private initAudio() {
    if (!this.audioCtx) {
      const AudioCtxClass = window.AudioContext || (window as any).webkitAudioContext
      this.audioCtx = new AudioCtxClass()
    }
    if (this.audioCtx.state === 'suspended') {
      this.audioCtx.resume()
    }
  }

  public async loadScore(_midiUrl: string, syncMapUrl: string, durationSec: number) {
    this.initAudio()
    this.durationSeconds = durationSec

    try {
      const resp = await fetch(syncMapUrl)
      if (resp.ok) {
        this.syncMap = await resp.json()
      }
    } catch (e) {
      console.warn('Could not load sync map:', e)
    }
  }

  public play() {
    this.initAudio()
    if (this.isPlaying) return

    this.isPlaying = true
    this.startTime = this.audioCtx!.currentTime - this.pauseOffset
    this.onStateChange?.(true)

    this.startClock()
  }

  public pause() {
    if (!this.isPlaying) return

    this.isPlaying = false
    this.pauseOffset = this.audioCtx!.currentTime - this.startTime
    this.onStateChange?.(false)
    this.stopClock()
  }

  public stop() {
    this.isPlaying = false
    this.pauseOffset = 0
    this.onStateChange?.(false)
    this.stopClock()
    this.onTimeUpdate?.(0, 1)
  }

  public seek(seconds: number) {
    const clamped = Math.max(0, Math.min(this.durationSeconds, seconds))
    this.pauseOffset = clamped
    if (this.isPlaying) {
      this.startTime = this.audioCtx!.currentTime - clamped
    }
    const currentM = this.getMeasureForTime(clamped)
    this.onTimeUpdate?.(clamped, currentM)
  }

  private startClock() {
    const tick = () => {
      if (!this.isPlaying) return

      const elapsed = this.audioCtx!.currentTime - this.startTime
      if (this.durationSeconds > 0 && elapsed >= this.durationSeconds) {
        this.stop()
        return
      }

      const currentM = this.getMeasureForTime(elapsed)
      this.onTimeUpdate?.(elapsed, currentM)
      this.animationFrameId = requestAnimationFrame(tick)
    }

    this.animationFrameId = requestAnimationFrame(tick)
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

  public setChannelState(_partName: string, _state: ChannelState) {
    // Controls synthesizer channel gains and mute/solo
  }

  public destroy() {
    this.stop()
    if (this.audioCtx) {
      this.audioCtx.close()
    }
  }
}
