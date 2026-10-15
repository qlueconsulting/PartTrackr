import React, { useState, useEffect, useRef, useMemo } from 'react'
import { Header } from './components/Header'
import { TransportControls } from './components/TransportControls'
import { MeasureTimeline } from './components/MeasureTimeline'
import { ActivePartIndicator } from './components/ActivePartIndicator'
import { StemMixer } from './components/StemMixer'
import { ScoreUploader } from './components/ScoreUploader'
import { AuditModal } from './components/AuditModal'
import { MultiTrackPlayer } from './audio/MultiTrackPlayer'
import type { ScoreResponse, ChannelState, MeasureInfo } from './types'

export const App: React.FC = () => {
  const [score, setScore] = useState<ScoreResponse | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [statusMessage, setStatusMessage] = useState<string>('')
  
  // Audio Player State
  const playerRef = useRef<MultiTrackPlayer | null>(null)
  const [isPlaying, setIsPlaying] = useState<boolean>(false)
  const [currentTime, setCurrentTime] = useState<number>(0)
  const [masterVolume, setMasterVolume] = useState<number>(0.9)
  const [playbackRate, setPlaybackRate] = useState<number>(1.0)
  
  // A/B Looping
  const [loopA, setLoopA] = useState<number | null>(null)
  const [loopB, setLoopB] = useState<number | null>(null)
  const [isLooping, setIsLooping] = useState<boolean>(false)

  // Singer Section Selection
  const [selectedUserPart, setSelectedUserPart] = useState<string>('S1')

  // Channel Mixer States
  const [channelStates, setChannelStates] = useState<Record<string, ChannelState>>({})

  // Modals
  const [isUploadOpen, setIsUploadOpen] = useState<boolean>(false)
  const [isAuditOpen, setIsAuditOpen] = useState<boolean>(false)

  // Initialize Player
  useEffect(() => {
    const player = new MultiTrackPlayer()
    playerRef.current = player

    player.onTimeUpdate = (time) => {
      setCurrentTime(time)
    }

    player.onStateChange = (playing) => {
      setIsPlaying(playing)
    }

    // Auto-load default sample anthem on initial mount
    loadSampleScore('anthem')

    return () => {
      player.destroy()
    }
  }, [])

  const loadSampleScore = async (sampleKey: string) => {
    setIsLoading(true)
    setStatusMessage(`Synthesizing sample score (${sampleKey})...`)
    try {
      const res = await fetch(`/api/v1/scores/sample/${sampleKey}`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to load sample score')
      const data: ScoreResponse = await res.json()
      handleScoreLoaded(data)
    } catch (err) {
      console.error('Error loading sample score:', err)
    } finally {
      setIsLoading(false)
      setStatusMessage('')
    }
  }

  const handleScoreLoaded = async (data: ScoreResponse) => {
    setScore(data)
    setCurrentTime(0)
    setIsPlaying(false)
    setLoopA(null)
    setLoopB(null)
    setIsLooping(false)

    // Initialize channel states from stems
    const initialChannels: Record<string, ChannelState> = {}
    Object.entries(data.stems).forEach(([name, info]) => {
      initialChannels[name] = {
        volume: 0.85,
        pan: info.default_pan ?? 0.0,
        muted: false,
        soloed: false,
      }
    })
    setChannelStates(initialChannels)

    // Load stems into Web Audio player
    if (playerRef.current) {
      await playerRef.current.loadStems(data.stems)
      playerRef.current.setMasterVolume(masterVolume)
      playerRef.current.setPlaybackRate(playbackRate)
    }
  }

  // Active measure calculation
  const currentMeasure = useMemo<MeasureInfo | null>(() => {
    if (!score || !score.analysis || score.analysis.length === 0) return null

    for (let i = score.analysis.length - 1; i >= 0; i--) {
      const m = score.analysis[i]
      if (currentTime >= m.start_time_seconds - 0.05) {
        return m
      }
    }
    return score.analysis[0]
  }, [score, currentTime])

  // Next Entrance calculation for selectedUserPart
  const nextEntranceMeasure = useMemo<number | null>(() => {
    if (!score || !score.analysis || !currentMeasure) return null

    // Find first entrance after current measure
    for (const m of score.analysis) {
      if (m.measure_number > currentMeasure.measure_number) {
        if (m.entrances.includes(selectedUserPart) || (m.active_parts.includes(selectedUserPart) && !currentMeasure.active_parts.includes(selectedUserPart))) {
          return m.measure_number
        }
      }
    }
    return null
  }, [score, currentMeasure, selectedUserPart])

  // Transport Handlers
  const handlePlay = () => playerRef.current?.play()
  const handlePause = () => playerRef.current?.pause()
  const handleStop = () => playerRef.current?.stop()
  const handleRewind = () => playerRef.current?.seek(0)
  
  const handleSeekToTime = (time: number) => {
    playerRef.current?.seek(time)
  }

  const handleSeekToMeasure = (measureNum: number) => {
    const target = score?.analysis.find((m) => m.measure_number === measureNum)
    if (target) {
      playerRef.current?.seek(target.start_time_seconds)
    }
  }

  const handleJumpToNextEntrance = () => {
    if (nextEntranceMeasure !== null) {
      handleSeekToMeasure(nextEntranceMeasure)
    }
  }

  const handleVolumeChange = (vol: number) => {
    setMasterVolume(vol)
    playerRef.current?.setMasterVolume(vol)
  }

  const handleRateChange = (rate: number) => {
    setPlaybackRate(rate)
    playerRef.current?.setPlaybackRate(rate)
  }

  const handleChannelStateChange = (stemName: string, state: ChannelState) => {
    const updated = { ...channelStates, [stemName]: state }
    setChannelStates(updated)
    playerRef.current?.setChannelState(stemName, state)
  }

  const handleResetMix = () => {
    if (!score) return
    const reset: Record<string, ChannelState> = {}
    Object.entries(score.stems).forEach(([name, info]) => {
      reset[name] = {
        volume: 0.85,
        pan: info.default_pan ?? 0.0,
        muted: false,
        soloed: false,
      }
      playerRef.current?.setChannelState(name, reset[name])
    })
    setChannelStates(reset)
  }

  // Loop Handlers
  const handleSetLoopA = () => {
    setLoopA(currentTime)
    if (playerRef.current) {
      playerRef.current.setLoop(currentTime, loopB, isLooping)
    }
  }

  const handleSetLoopB = () => {
    if (currentTime > (loopA ?? 0)) {
      setLoopB(currentTime)
      setIsLooping(true)
      if (playerRef.current) {
        playerRef.current.setLoop(loopA, currentTime, true)
      }
    }
  }

  const handleToggleLoop = () => {
    const nextLooping = !isLooping
    setIsLooping(nextLooping)
    if (playerRef.current) {
      playerRef.current.setLoop(loopA, loopB, nextLooping)
    }
  }

  const handleClearLoop = () => {
    setLoopA(null)
    setLoopB(null)
    setIsLooping(false)
    if (playerRef.current) {
      playerRef.current.setLoop(null, null, false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
      {/* Top Header */}
      <Header
        scoreTitle={score?.title || 'Choral Anthem of Hope'}
        composer={score?.composer || 'A. Antigravity'}
        measureCount={score?.measure_count || 0}
        totalDuration={score?.total_duration_seconds || 0}
        onOpenAudit={() => setIsAuditOpen(true)}
        onOpenUpload={() => setIsUploadOpen(true)}
        onOpenSamples={() => setIsUploadOpen(true)}
      />

      {/* Transport Bar */}
      <TransportControls
        isPlaying={isPlaying}
        currentTime={currentTime}
        totalDuration={score?.total_duration_seconds || 0}
        currentMeasure={currentMeasure?.measure_number || 1}
        totalMeasures={score?.measure_count || 1}
        tempoBpm={currentMeasure?.tempo_bpm || score?.tempo_bpm || 120}
        timeSignature={currentMeasure?.time_signature || score?.time_signature || '4/4'}
        masterVolume={masterVolume}
        playbackRate={playbackRate}
        loopA={loopA}
        loopB={loopB}
        isLooping={isLooping}
        selectedPart={selectedUserPart}
        hasEntranceAhead={nextEntranceMeasure !== null}
        onPlay={handlePlay}
        onPause={handlePause}
        onStop={handleStop}
        onRewind={handleRewind}
        onVolumeChange={handleVolumeChange}
        onRateChange={handleRateChange}
        onSetLoopA={handleSetLoopA}
        onSetLoopB={handleSetLoopB}
        onToggleLoop={handleToggleLoop}
        onClearLoop={handleClearLoop}
        onJumpToNextEntrance={handleJumpToNextEntrance}
      />

      {/* Measure Timeline Bar */}
      <MeasureTimeline
        analysis={score?.analysis || []}
        currentTime={currentTime}
        totalDuration={score?.total_duration_seconds || 0}
        currentMeasureNumber={currentMeasure?.measure_number || 1}
        loopA={loopA}
        loopB={loopB}
        onSeekToTime={handleSeekToTime}
        onSeekToMeasure={handleSeekToMeasure}
      />

      {/* Active Singer Indicator & Voice Selection */}
      <ActivePartIndicator
        currentMeasure={currentMeasure}
        selectedPart={selectedUserPart}
        onSelectPart={setSelectedUserPart}
        onJumpToNextEntrance={handleJumpToNextEntrance}
        nextEntranceMeasure={nextEntranceMeasure}
      />

      {/* 11-Channel Rehearsal Console */}
      <StemMixer
        stems={score?.stems || {}}
        channelStates={channelStates}
        currentMeasure={currentMeasure}
        selectedUserPart={selectedUserPart}
        onChannelStateChange={handleChannelStateChange}
        onResetMix={handleResetMix}
      />

      {/* Modals */}
      <ScoreUploader
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onScoreLoaded={handleScoreLoaded}
        onLoadSample={loadSampleScore}
        isLoading={isLoading}
        statusMessage={statusMessage}
      />

      <AuditModal
        isOpen={isAuditOpen}
        onClose={() => setIsAuditOpen(false)}
        audit={score?.audit}
        analysis={score?.analysis || []}
        scoreTitle={score?.title || ''}
      />
    </div>
  )
}

export default App
