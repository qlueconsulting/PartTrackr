import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  Upload,
  Play,
  Pause,
  Square,
  RotateCcw,
  Sliders,
  Music,
  Layout,
  Code,
  Terminal,
  AlertCircle,
  X,
  Volume2,
  Volume1,
  VolumeX,
  Sparkles,
} from 'lucide-react'

import { PipelineStepper } from './components/PipelineStepper'
import { VisualDiffViewer } from './components/VisualDiffViewer'
import { CISMEditor } from './components/CISMEditor'
import { ApiLogViewer } from './components/ApiLogViewer'
import { WebAudioMixer } from './components/WebAudioMixer'
import { ScoreHintsModal } from './components/ScoreHintsModal'
import { RecentScoresDropdown } from './components/RecentScoresDropdown'
import { MidiAudioEngine } from './audio/MidiAudioEngine'
import {
  CANONICAL_11_PARTS,
  PART_DISPLAY_NAMES,
  type JobData,
  type ChannelState,
  type ApiLogEntry,
  type ScoreHints,
} from './types'

export const App: React.FC = () => {
  // Mode Toggle: 'diagnostic' vs 'rehearsal'
  const [viewMode, setViewMode] = useState<'diagnostic' | 'rehearsal'>('diagnostic')

  // Bottom Pane Sub-Tab: 'cism' vs 'logs'
  const [bottomTab, setBottomTab] = useState<'cism' | 'logs'>('cism')

  // Job & Pipeline State
  const [currentJob, setCurrentJob] = useState<JobData | null>(null)
  const [recentJobs, setRecentJobs] = useState<JobData[]>([])
  const [selectedMeasureNumber, setSelectedMeasureNumber] = useState<number | null>(1)
  const [isUploading, setIsUploading] = useState<boolean>(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [isHintsModalOpen, setIsHintsModalOpen] = useState<boolean>(false)

  // API & Pipeline Telemetry Logs
  const [apiLogs, setApiLogs] = useState<ApiLogEntry[]>([])

  const addLog = useCallback(
    (level: 'info' | 'success' | 'warn' | 'error', service: string, message: string, details?: any) => {
      const entry: ApiLogEntry = {
        id: Math.random().toString(36).substring(2, 9),
        timestamp: new Date().toLocaleTimeString(),
        level,
        service,
        message,
        details,
      }
      setApiLogs((prev) => [...prev, entry])
    },
    []
  )

  const [isLoadingLogs, setIsLoadingLogs] = useState<boolean>(false)

  const fetchJobLogs = useCallback(async (jobId: string) => {
    try {
      setIsLoadingLogs(true)
      const res = await fetch(`/api/v1/jobs/${jobId}/logs`)
      if (res.ok) {
        const data = await res.json()
        const backendLogs: ApiLogEntry[] = data.logs || []
        if (backendLogs.length > 0) {
          setApiLogs((prev) => {
            const existingIds = new Set(prev.map((l) => l.id))
            const newLogs = backendLogs.filter((l) => !existingIds.has(l.id))
            if (newLogs.length === 0) return prev
            return [...prev, ...newLogs]
          })
        }
        if (data.status === 'failed') {
          const errMsg = data.error_message || data.stage_message || 'Pipeline processing failed'
          setErrorMessage(errMsg)
          setBottomTab('logs')
        }
      }
    } catch (e: any) {
      console.warn('Could not fetch backend logs:', e)
    } finally {
      setIsLoadingLogs(false)
    }
  }, [])

  // Audio Playback State
  const audioEngineRef = useRef<MidiAudioEngine | null>(null)
  const [isPlaying, setIsPlaying] = useState<boolean>(false)
  const [currentMeasure, setCurrentMeasure] = useState<number>(1)
  const [selectedSingerPart, setSelectedSingerPart] = useState<string>('soprano_1')
  const [masterVolume, setMasterVolume] = useState<number>(0.85)
  const [isMuted, setIsMuted] = useState<boolean>(false)

  const handleMasterVolumeChange = useCallback((newVol: number) => {
    setMasterVolume(newVol)
    if (newVol > 0 && isMuted) {
      setIsMuted(false)
    }
    audioEngineRef.current?.setMasterVolume(newVol)
  }, [isMuted])

  const handleToggleMute = useCallback(() => {
    if (isMuted) {
      setIsMuted(false)
      audioEngineRef.current?.setMasterVolume(masterVolume > 0 ? masterVolume : 0.85)
    } else {
      setIsMuted(true)
      audioEngineRef.current?.setMasterVolume(0)
    }
  }, [isMuted, masterVolume])

  // 11-Part Channel Mixer States
  const [channelStates, setChannelStates] = useState<Record<string, ChannelState>>(() => {
    const initial: Record<string, ChannelState> = {}
    for (const p of CANONICAL_11_PARTS) {
      initial[p] = { volume: 0.85, pan: 0.0, muted: false, soloed: false, amplified: false }
    }
    return initial
  })

  // Initialize Audio Engine & Initial Job Query
  useEffect(() => {
    const engine = new MidiAudioEngine()
    audioEngineRef.current = engine
    engine.setAllChannelStates(channelStates)

    engine.onTimeUpdate = (_time, mNum) => {
      setCurrentMeasure(mNum)
    }

    engine.onStateChange = (playing) => {
      setIsPlaying(playing)
    }

    addLog('info', 'client', 'Diagnostic Studio v2.0 initialized. Connecting to gateway-svc:8005...')
    fetchLatestJobs()

    return () => {
      engine.destroy()
    }
  }, [addLog])

  const fetchLatestJobs = async () => {
    try {
      addLog('info', 'client', 'GET /api/v1/jobs?limit=10 - Fetching last 10 submission records...')
      const res = await fetch('/api/v1/jobs?limit=10')
      if (res.ok) {
        const jobs: JobData[] = await res.json()
        setRecentJobs(jobs)
        addLog('success', 'gateway-svc', `Found ${jobs.length} existing job records in history`, jobs)
        if (jobs && jobs.length > 0) {
          const savedActiveId = localStorage.getItem('parttrackr_active_job_id')
          const targetJob = jobs.find((j) => j.job_id === savedActiveId) || jobs[0]
          loadJobDetails(targetJob.job_id)
        }
      } else {
        addLog('warn', 'gateway-svc', `Failed to fetch jobs HTTP ${res.status}`)
      }
    } catch (e: any) {
      addLog('error', 'client', `Gateway connection failed: ${e.message}`)
    }
  }

  const loadJobDetails = async (jobId: string) => {
    try {
      localStorage.setItem('parttrackr_active_job_id', jobId)
      addLog('info', 'client', `GET /api/v1/jobs/${jobId} - Querying job status...`)
      fetchJobLogs(jobId)
      const res = await fetch(`/api/v1/jobs/${jobId}`)
      if (res.ok) {
        const jobData: JobData = await res.json()
        setCurrentJob(jobData)
        setRecentJobs((prev) => {
          const idx = prev.findIndex((j) => j.job_id === jobId)
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = { ...next[idx], ...jobData }
            return next
          }
          return [jobData, ...prev.slice(0, 9)]
        })
        addLog('info', 'gateway-svc', `Job ${jobId} status: ${jobData.status.toUpperCase()} - ${jobData.stage_message}`, {
          total_measures: jobData.total_measures,
          status: jobData.status,
        })

        if (jobData.status === 'failed') {
          const failErr = jobData.error_message || jobData.stage_message || 'Pipeline processing failed'
          setErrorMessage(failErr)
          setBottomTab('logs')
          addLog('error', 'pipeline', `Job ${jobId} failed: ${failErr}`)
        } else if (jobData.status === 'completed' && jobData.decoder_result) {
          addLog('success', 'decoder-xml-svc', `MusicXML and MIDI ready. Measures: ${jobData.total_measures}`)
          const syncMapUrl = `/api/v1/jobs/${jobId}/files/compiled/sync_map.json`
          const scoreCism = jobData.routed_cism || jobData.raw_cism
          if (scoreCism) {
            audioEngineRef.current?.loadScore(
              scoreCism,
              syncMapUrl,
              jobData.total_duration_seconds || 60
            )
          } else {
            audioEngineRef.current?.loadScore(
              `/api/v1/jobs/${jobId}`,
              syncMapUrl,
              jobData.total_duration_seconds || 60
            )
          }
          if (channelStates) {
            audioEngineRef.current?.setAllChannelStates(channelStates)
          }
        } else if (jobData.status !== 'completed') {
          listenToJobEvents(jobId)
        }
      }
    } catch (e: any) {
      addLog('error', 'client', `Error loading job ${jobId}: ${e.message}`)
    }
  }

  // Active Polling & Server-Sent Events Fallback
  const listenToJobEvents = (jobId: string) => {
    addLog('info', 'client', `SSE: Connecting to /api/v1/jobs/${jobId}/events for real-time stepper updates...`)
    const evtSource = new EventSource(`/api/v1/jobs/${jobId}/events`)

    // Polling fallback every 2s in case SSE is buffered
    const pollInterval = setInterval(async () => {
      try {
        fetchJobLogs(jobId)
        const res = await fetch(`/api/v1/jobs/${jobId}`)
        if (res.ok) {
          const latest: JobData = await res.json()
          setCurrentJob(latest)
          if (latest.status === 'completed' || latest.status === 'failed') {
            clearInterval(pollInterval)
            evtSource.close()
            fetchJobLogs(jobId)
            if (latest.status === 'completed') {
              addLog('success', 'pipeline', `Job ${jobId} successfully completed!`)
            } else {
              const failMsg = latest.error_message || latest.stage_message || 'Pipeline failed'
              addLog('error', 'pipeline', `Job ${jobId} failed: ${failMsg}`)
              setErrorMessage(failMsg)
              setBottomTab('logs')
            }
          }
        }
      } catch (err) {
        // silent poll catch
      }
    }, 2000)

    evtSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.status) {
          addLog('info', 'pipeline', `[Stage Transition]: ${data.status.toUpperCase()} — ${data.stage_message}`)
          setCurrentJob((prev) =>
            prev ? { ...prev, status: data.status, stage_message: data.stage_message } : null
          )
        }
        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(pollInterval)
          evtSource.close()
          loadJobDetails(jobId)
          fetchJobLogs(jobId)
          if (data.status === 'failed') {
            const failMsg = data.error_message || data.stage_message || 'Pipeline stage failed'
            setErrorMessage(failMsg)
            setBottomTab('logs')
          }
        }
      } catch (err) {
        console.warn('SSE parse error:', err)
      }
    }

    evtSource.onerror = () => {
      addLog('warn', 'client', 'SSE connection closed or switched to fallback polling.')
      evtSource.close()
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsUploading(true)
    setErrorMessage(null)
    const fileSizeMB = (file.size / 1024 / 1024).toFixed(2)
    addLog('info', 'client', `POST /api/v1/jobs/upload - Uploading "${file.name}" (${fileSizeMB} MB)...`)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch('/api/v1/jobs/upload', {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) {
        let errDetails = ''
        try {
          const errJson = await res.json()
          errDetails = errJson.detail || JSON.stringify(errJson)
        } catch {
          errDetails = await res.text()
        }
        const failMsg = `Upload failed with HTTP ${res.status}: ${errDetails}`
        addLog('error', 'gateway-svc', failMsg)
        setErrorMessage(failMsg)
        setBottomTab('logs') // Switch to logs so user sees it
        throw new Error(failMsg)
      }

      const data = await res.json()
      addLog('success', 'gateway-svc', `Upload accepted! Job ID: ${data.job_id}`, data)
      loadJobDetails(data.job_id)
      setIsHintsModalOpen(true)
    } catch (err: any) {
      console.error('Upload error:', err)
      setErrorMessage(err.message || 'PDF upload failed')
      setBottomTab('logs')
    } finally {
      setIsUploading(false)
      // reset file input
      e.target.value = ''
    }
  }

  const handleReprocessTriggered = (jobId: string, hints: ScoreHints) => {
    addLog('info', 'client', `Score reprocessing dispatched with AI hints:`, hints)
    setErrorMessage(null)
    setBottomTab('logs')
    setCurrentJob((prev) =>
      prev
        ? {
            ...prev,
            status: 'pending',
            stage_message: 'Reprocessing score with user AI hints...',
            score_hints: hints,
            total_measures: hints.total_measures ?? prev.total_measures,
          }
        : null
    )
    listenToJobEvents(jobId)
  }

  // Transport Handlers
  const handlePlayPause = () => {
    if (isPlaying) {
      audioEngineRef.current?.pause()
    } else {
      audioEngineRef.current?.play()
    }
  }

  const handleStop = () => {
    audioEngineRef.current?.stop()
  }

  const handleRewind = () => {
    audioEngineRef.current?.seek(0)
  }

  const handleChannelChange = (partName: string, state: ChannelState) => {
    const updated = { ...channelStates, [partName]: state }
    setChannelStates(updated)
    audioEngineRef.current?.setChannelState(partName, state)
  }

  const activePartsInMeasure = React.useMemo(() => {
    if (!currentJob?.decoder_result?.measure_summary) return []
    const m = currentJob.decoder_result.measure_summary.find(
      (ms) => ms.measure_number === currentMeasure
    )
    return m?.active_parts || []
  }, [currentJob, currentMeasure])

  const errorLogCount = apiLogs.filter((l) => l.level === 'error').length

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Navbar */}
      <header className="bg-slate-900 border-b border-slate-800 px-6 py-3 flex items-center justify-between shadow-md">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400">
            <Music className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-base font-bold text-slate-100 tracking-tight flex items-center gap-2">
              PartTrackr
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-sky-950 text-sky-400 border border-sky-800 font-mono">
                Microservices v2.0
              </span>
            </h1>
            <p className="text-xs text-slate-400">
              {currentJob?.title || 'Upload PDF Choral Sheet Music'} • {currentJob?.composer || 'AI OMR & Voice Separation'}
            </p>
          </div>
        </div>

        {/* View Mode Toggle & Upload Button */}
        <div className="flex items-center gap-3">
          <div className="flex bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs font-semibold">
            <button
              onClick={() => setViewMode('diagnostic')}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-md transition-all cursor-pointer ${
                viewMode === 'diagnostic'
                  ? 'bg-sky-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Layout className="w-3.5 h-3.5" />
              <span>Diagnostic Studio</span>
            </button>
            <button
              onClick={() => setViewMode('rehearsal')}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-md transition-all cursor-pointer ${
                viewMode === 'rehearsal'
                  ? 'bg-sky-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Sliders className="w-3.5 h-3.5" />
              <span>Rehearsal Console</span>
            </button>
          </div>

          {/* 10-File Submission History Selector */}
          <RecentScoresDropdown
            jobs={recentJobs}
            activeJobId={currentJob?.job_id || null}
            onSelectJob={(jobId) => loadJobDetails(jobId)}
            onOpenAiHelpsForJob={(job) => {
              loadJobDetails(job.job_id)
              setIsHintsModalOpen(true)
            }}
            isLoading={isLoadingLogs}
            onRefresh={fetchLatestJobs}
          />

          {/* AI Helps & Reprocess Button */}
          <button
            onClick={() => setIsHintsModalOpen(true)}
            disabled={!currentJob}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-gradient-to-r from-violet-600 via-indigo-600 to-purple-600 hover:from-violet-500 hover:via-indigo-500 hover:to-purple-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg text-xs font-semibold shadow transition-all duration-150 cursor-pointer"
            title="Configure score hints, time signature, tempo, and AI helps"
          >
            <Sparkles className="w-3.5 h-3.5 text-amber-300" />
            <span>AI Helps / Reprocess</span>
          </button>

          <label className="flex items-center gap-1.5 px-3.5 py-1.5 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-xs font-semibold cursor-pointer shadow transition-all duration-150">
            <Upload className="w-3.5 h-3.5" />
            <span>{isUploading ? 'Uploading...' : 'Upload PDF'}</span>
            <input
              type="file"
              accept=".pdf"
              onChange={handleFileUpload}
              disabled={isUploading}
              className="hidden"
            />
          </label>
        </div>
      </header>

      {/* Error Alert Banner */}
      {errorMessage && (
        <div className="bg-rose-950/90 border-b border-rose-800 px-6 py-2 flex items-center justify-between text-xs text-rose-200">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400" />
            <span className="font-semibold font-mono">{errorMessage}</span>
          </div>
          <button onClick={() => setErrorMessage(null)} className="hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Main Container */}
      <main className="flex-1 p-4 flex flex-col gap-4 max-w-[1700px] w-full mx-auto">
        {/* Pipeline Stepper Component */}
        <PipelineStepper
          currentStage={currentJob?.status || 'pending'}
          stageMessage={currentJob?.stage_message || 'Awaiting PDF sheet music upload...'}
          totalMeasures={currentJob?.total_measures || 0}
        />

        {/* Mode 1: Diagnostic Studio */}
        {viewMode === 'diagnostic' && (
          <div className="flex flex-col gap-4 flex-1">
            {/* Visual Diff: PDF vs OSMD (if job loaded) */}
            {currentJob && (
              <VisualDiffViewer
                job={currentJob}
                selectedMeasureNumber={selectedMeasureNumber}
                onSelectMeasure={(mNum) => {
                  setSelectedMeasureNumber(mNum)
                  audioEngineRef.current?.seek(
                    currentJob.decoder_result?.measure_summary?.find((m) => m.measure_number === mNum)
                      ?.start_time_seconds || 0
                  )
                }}
                currentPlayingMeasure={currentMeasure}
              />
            )}

            {/* Bottom Split: [CISM Editor OR API Log Viewer] (Left) & WebAudio Mixer (Right) */}
            <div className="grid grid-cols-12 gap-4 h-[380px]">
              {/* Left Column: Tabbed Inspector */}
              <div className="col-span-6 h-full flex flex-col">
                {/* Tab Switcher */}
                <div className="flex items-center gap-1 bg-slate-900 border-t border-x border-slate-800 rounded-t-xl px-3 py-1.5 w-fit">
                  <button
                    onClick={() => setBottomTab('cism')}
                    className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold transition cursor-pointer ${
                      bottomTab === 'cism'
                        ? 'bg-slate-800 text-sky-400 shadow-sm'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Code className="w-3.5 h-3.5" />
                    <span>CISM JSON Editor</span>
                  </button>
                  <button
                    onClick={() => {
                      setBottomTab('logs')
                      if (currentJob?.job_id) {
                        fetchJobLogs(currentJob.job_id)
                      }
                    }}
                    className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold transition cursor-pointer ${
                      bottomTab === 'logs'
                        ? 'bg-slate-800 text-emerald-400 shadow-sm'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Terminal className="w-3.5 h-3.5" />
                    <span>API Telemetry Live Logs</span>
                    {errorLogCount > 0 && (
                      <span className="w-4 h-4 rounded-full bg-rose-600 text-white text-[10px] flex items-center justify-center font-bold">
                        {errorLogCount}
                      </span>
                    )}
                  </button>
                </div>

                {/* Tab Content */}
                <div className="flex-1 overflow-hidden">
                  {bottomTab === 'cism' ? (
                    currentJob ? (
                      <CISMEditor
                        job={currentJob}
                        selectedMeasureNumber={selectedMeasureNumber}
                        onOverrideSaved={(updated) => {
                          addLog('success', 'voice-router-svc', 'Measure override compiled successfully')
                          if (currentJob) {
                            const newRouted = updated.result.routed_cism
                            const newDecoder = updated.result.decoder_result
                            setCurrentJob({
                              ...currentJob,
                              routed_cism: newRouted,
                              decoder_result: newDecoder,
                            })
                            const syncMapUrl = `/api/v1/jobs/${currentJob.job_id}/files/compiled/sync_map.json`
                            audioEngineRef.current?.loadScore(
                              newRouted,
                              syncMapUrl,
                              newDecoder?.total_duration_seconds || currentJob.total_duration_seconds
                            )
                          }
                        }}
                      />
                    ) : (
                      <div className="h-full bg-slate-900 border border-slate-800 rounded-b-xl rounded-tr-xl flex items-center justify-center text-slate-500 italic text-xs">
                        Upload a score to inspect and edit CISM JSON
                      </div>
                    )
                  ) : (
                    <ApiLogViewer
                      logs={apiLogs}
                      onClearLogs={() => setApiLogs([])}
                      onRefreshLogs={() => currentJob && fetchJobLogs(currentJob.job_id)}
                      isLoading={isLoadingLogs}
                    />
                  )}
                </div>
              </div>

              {/* Right Column: WebAudio Mixer */}
              <div className="col-span-6 h-full flex flex-col justify-between">
                <WebAudioMixer
                  channelStates={channelStates}
                  onChannelChange={handleChannelChange}
                  activeParts={activePartsInMeasure}
                />
              </div>
            </div>
          </div>
        )}

        {/* Mode 2: Rehearsal Console */}
        {viewMode === 'rehearsal' && currentJob && (
          <div className="flex flex-col gap-4 flex-1">
            {/* Rehearsal Transport Bar */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center justify-between shadow-lg">
              <div className="flex items-center gap-3">
                <button
                  onClick={handleRewind}
                  className="p-2.5 bg-slate-800 hover:bg-slate-700 rounded-lg text-slate-300 cursor-pointer"
                  title="Rewind to start"
                >
                  <RotateCcw className="w-4 h-4" />
                </button>
                <button
                  onClick={handlePlayPause}
                  className="p-3 bg-sky-600 hover:bg-sky-500 rounded-xl text-white shadow-md shadow-sky-600/30 cursor-pointer"
                  title={isPlaying ? 'Pause' : 'Play'}
                >
                  {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5 ml-0.5" />}
                </button>
                <button
                  onClick={handleStop}
                  className="p-2.5 bg-slate-800 hover:bg-slate-700 rounded-lg text-slate-300 cursor-pointer"
                  title="Stop"
                >
                  <Square className="w-4 h-4" />
                </button>

                <div className="ml-4 font-mono">
                  <span className="text-xl font-bold text-sky-400">
                    Measure {currentMeasure}
                  </span>
                  <span className="text-xs text-slate-500 ml-2">
                    / {currentJob.total_measures || 1}
                  </span>
                </div>
              </div>

              {/* Master MIDI Volume Control */}
              <div className="flex items-center gap-2 bg-slate-950/80 px-3 py-1.5 rounded-lg border border-slate-800">
                <button
                  onClick={handleToggleMute}
                  className={`p-1.5 rounded transition cursor-pointer ${
                    isMuted || masterVolume === 0
                      ? 'text-rose-400 hover:text-rose-300 bg-rose-950/50'
                      : 'text-slate-300 hover:text-sky-400'
                  }`}
                  title={isMuted ? 'Unmute MIDI Volume' : 'Mute MIDI Volume'}
                >
                  {isMuted || masterVolume === 0 ? (
                    <VolumeX className="w-4 h-4" />
                  ) : masterVolume < 0.5 ? (
                    <Volume1 className="w-4 h-4" />
                  ) : (
                    <Volume2 className="w-4 h-4" />
                  )}
                </button>
                <div className="flex flex-col gap-0.5">
                  <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono gap-2">
                    <span>MIDI Volume</span>
                    <span className="font-semibold text-sky-400">
                      {isMuted ? '0%' : `${Math.round(masterVolume * 100)}%`}
                    </span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={isMuted ? 0 : Math.round(masterVolume * 100)}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10) / 100.0
                      handleMasterVolumeChange(val)
                    }}
                    className="w-24 sm:w-28 h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-sky-500"
                    title={`Turn down or adjust MIDI volume: ${Math.round(masterVolume * 100)}%`}
                  />
                </div>
              </div>

              {/* Singer Part Selector & Quick Actions */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 font-semibold uppercase tracking-wider">My Part:</span>
                <select
                  value={selectedSingerPart}
                  onChange={(e) => setSelectedSingerPart(e.target.value)}
                  className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-sky-300 font-semibold focus:outline-none cursor-pointer"
                >
                  {CANONICAL_11_PARTS.map((p) => (
                    <option key={p} value={p}>
                      {PART_DISPLAY_NAMES[p]}
                    </option>
                  ))}
                </select>

                <div className="flex items-center gap-1.5 ml-2">
                  <button
                    onClick={() => {
                      const updated: Record<string, ChannelState> = {}
                      for (const p of CANONICAL_11_PARTS) {
                        updated[p] = {
                          ...channelStates[p],
                          soloed: p === selectedSingerPart,
                          muted: false,
                        }
                      }
                      setChannelStates(updated)
                      audioEngineRef.current?.setAllChannelStates(updated)
                    }}
                    className="px-2.5 py-1 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-300 rounded text-xs font-semibold cursor-pointer transition-colors"
                    title="Solo your chosen vocal part"
                  >
                    Solo Part
                  </button>

                  <button
                    onClick={() => {
                      const updated: Record<string, ChannelState> = {}
                      for (const p of CANONICAL_11_PARTS) {
                        updated[p] = {
                          ...channelStates[p],
                          amplified: p === selectedSingerPart ? !channelStates[p].amplified : false,
                        }
                      }
                      setChannelStates(updated)
                      audioEngineRef.current?.setAllChannelStates(updated)
                    }}
                    className="px-2.5 py-1 bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/40 text-purple-300 rounded text-xs font-semibold cursor-pointer transition-colors"
                    title="Boost your chosen vocal part by +6dB"
                  >
                    Boost (+6dB)
                  </button>

                  <button
                    onClick={() => {
                      const initial: Record<string, ChannelState> = {}
                      for (const p of CANONICAL_11_PARTS) {
                        initial[p] = { volume: 0.85, pan: 0.0, muted: false, soloed: false, amplified: false }
                      }
                      setChannelStates(initial)
                      audioEngineRef.current?.setAllChannelStates(initial)
                    }}
                    className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs font-semibold cursor-pointer transition-colors"
                    title="Reset all 11 parts to standard balance"
                  >
                    Reset
                  </button>

                  <button
                    onClick={() => setIsHintsModalOpen(true)}
                    className="flex items-center gap-1 px-2.5 py-1 bg-violet-600/30 hover:bg-violet-600/40 border border-violet-500/50 text-violet-200 rounded text-xs font-semibold cursor-pointer transition-colors"
                    title="Open Score Hints & AI Helps modal"
                  >
                    <Sparkles className="w-3.5 h-3.5 text-amber-300" />
                    <span>AI Helps</span>
                  </button>
                </div>
              </div>
            </div>

            {/* 11-Channel Rehearsal Mixer */}
            <div>
              <WebAudioMixer
                channelStates={channelStates}
                onChannelChange={handleChannelChange}
                activeParts={activePartsInMeasure}
              />
            </div>

            {/* Side-by-Side Visual Diff Viewer (under 11 part controls) */}
            <VisualDiffViewer
              job={currentJob}
              selectedMeasureNumber={selectedMeasureNumber}
              onSelectMeasure={(mNum) => {
                setSelectedMeasureNumber(mNum)
                const targetSec = currentJob.decoder_result?.measure_summary?.find((m) => m.measure_number === mNum)
                  ?.start_time_seconds || 0
                audioEngineRef.current?.seek(targetSec)
              }}
              currentPlayingMeasure={currentMeasure}
            />
          </div>
        )}

        {/* Empty state when no score loaded */}
        {!currentJob && (
          <div className="flex-1 flex flex-col items-center justify-center border-2 border-dashed border-slate-800 rounded-2xl p-12 text-center bg-slate-900/30">
            <div className="w-16 h-16 rounded-2xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400 mb-4">
              <Music className="w-8 h-8" />
            </div>
            <h3 className="text-lg font-bold text-slate-200 mb-1">
              No Choral Score Loaded
            </h3>
            <p className="text-sm text-slate-400 max-w-md mb-6">
              Upload a choral sheet music PDF to rasterize layout, run hybrid OMR, route to 11 canonical rehearsal parts, and debug with the Diagnostic Studio.
            </p>
            <label className="flex items-center gap-2 px-5 py-2.5 bg-sky-600 hover:bg-sky-500 text-white rounded-xl text-sm font-semibold cursor-pointer shadow-lg shadow-sky-600/20 transition-all">
              <Upload className="w-4 h-4" />
              <span>Upload PDF Sheet Music</span>
              <input
                type="file"
                accept=".pdf"
                onChange={handleFileUpload}
                className="hidden"
              />
            </label>
          </div>
        )}

        {/* Score Hints & AI Reprocess Modal */}
        <ScoreHintsModal
          isOpen={isHintsModalOpen}
          onClose={() => setIsHintsModalOpen(false)}
          job={currentJob}
          onReprocessTriggered={handleReprocessTriggered}
        />
      </main>
    </div>
  )
}

export default App
