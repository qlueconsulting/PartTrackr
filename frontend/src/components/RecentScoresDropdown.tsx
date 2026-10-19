import React, { useState, useRef, useEffect } from 'react'
import {
  History,
  ChevronDown,
  Check,
  Sparkles,
  FileMusic,
  Clock,
  RotateCw,
  AlertCircle,
  CheckCircle2,
  Loader2,
} from 'lucide-react'
import type { JobData } from '../types'

interface RecentScoresDropdownProps {
  jobs: JobData[]
  activeJobId: string | null
  onSelectJob: (jobId: string) => void
  onOpenAiHelpsForJob: (job: JobData) => void
  isLoading?: boolean
  onRefresh?: () => void
}

export const RecentScoresDropdown: React.FC<RecentScoresDropdownProps> = ({
  jobs,
  activeJobId,
  onSelectJob,
  onOpenAiHelpsForJob,
  isLoading = false,
  onRefresh,
}) => {
  const [isOpen, setIsOpen] = useState<boolean>(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Close when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen])

  const activeJob = jobs.find((j) => j.job_id === activeJobId)

  const formatTime = (isoString?: string) => {
    if (!isoString) return ''
    try {
      const d = new Date(isoString)
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } catch {
      return ''
    }
  }

  return (
    <div className="relative inline-block text-left" ref={dropdownRef}>
      {/* Trigger Button */}
      <button
        onClick={() => setIsOpen((prev) => !prev)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all duration-150 cursor-pointer ${
          isOpen
            ? 'bg-slate-800 text-white border-slate-600 shadow'
            : 'bg-slate-950 hover:bg-slate-900 text-slate-300 border-slate-800 hover:border-slate-700'
        }`}
        title="View last 10 submitted files and their saved AI Helps"
      >
        <History className="w-3.5 h-3.5 text-sky-400 flex-shrink-0" />
        <span className="hidden sm:inline truncate max-w-[130px]">
          {activeJob?.title || 'Recent Scores'}
        </span>
        <span className="px-1.5 py-0.2 bg-slate-800 text-sky-300 border border-slate-700 rounded-full text-[10px]">
          {jobs.length}
        </span>
        <ChevronDown
          className={`w-3.5 h-3.5 text-slate-400 transition-transform duration-150 ${
            isOpen ? 'rotate-180' : ''
          }`}
        />
      </button>

      {/* Popover Menu */}
      {isOpen && (
        <div className="absolute right-0 mt-2 w-84 sm:w-96 rounded-2xl bg-slate-900 border border-slate-700/80 shadow-2xl z-50 overflow-hidden animate-in fade-in duration-150">
          {/* Header */}
          <div className="px-4 py-3 bg-slate-950/90 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <History className="w-4 h-4 text-sky-400" />
              <span className="text-xs font-bold text-white tracking-wide">
                Submission History (Last 10)
              </span>
            </div>
            {onRefresh && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onRefresh()
                }}
                disabled={isLoading}
                className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition disabled:opacity-40"
                title="Refresh score history"
              >
                <RotateCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
              </button>
            )}
          </div>

          {/* List of Previous Jobs */}
          <div className="max-h-96 overflow-y-auto divide-y divide-slate-800/60 p-1">
            {jobs.length === 0 ? (
              <div className="p-6 text-center text-xs text-slate-500">
                <FileMusic className="w-8 h-8 mx-auto mb-2 text-slate-600" />
                No submitted scores yet. Upload a PDF sheet music file above!
              </div>
            ) : (
              jobs.slice(0, 10).map((job) => {
                const isActive = job.job_id === activeJobId
                const hints = job.score_hints as any
                const hasHints = Boolean(hints && (hints.time_signature || hints.choral_voicing || hints.custom_instructions))

                return (
                  <div
                    key={job.job_id}
                    onClick={() => {
                      onSelectJob(job.job_id)
                      setIsOpen(false)
                    }}
                    className={`group p-3 rounded-xl transition-all cursor-pointer flex flex-col gap-1.5 ${
                      isActive
                        ? 'bg-sky-950/40 border border-sky-800/60 shadow-sm'
                        : 'hover:bg-slate-800/60 border border-transparent'
                    }`}
                  >
                    {/* Top Row: Title, Status & Active Checkmark */}
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <FileMusic className={`w-4 h-4 flex-shrink-0 ${isActive ? 'text-sky-400' : 'text-slate-400'}`} />
                        <span className={`text-xs font-bold truncate ${isActive ? 'text-white' : 'text-slate-200 group-hover:text-white'}`}>
                          {job.title || job.filename || `Score ${job.job_id}`}
                        </span>
                      </div>

                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        {/* Status Badge */}
                        {job.status === 'completed' && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-800/60">
                            <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                            Ready
                          </span>
                        )}
                        {job.status === 'failed' && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-950/80 text-rose-300 border border-rose-800/60">
                            <AlertCircle className="w-3 h-3 text-rose-400" />
                            Failed
                          </span>
                        )}
                        {job.status !== 'completed' && job.status !== 'failed' && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-950/80 text-amber-300 border border-amber-800/60">
                            <Loader2 className="w-3 h-3 animate-spin text-amber-400" />
                            {job.status}
                          </span>
                        )}

                        {isActive && (
                          <span className="w-4 h-4 rounded-full bg-sky-500/20 text-sky-400 flex items-center justify-center">
                            <Check className="w-3 h-3" />
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Metadata Sub-row */}
                    <div className="flex items-center justify-between text-[11px] text-slate-400">
                      <span className="truncate max-w-[190px]">
                        {job.filename ? job.filename : `ID: ${job.job_id}`}
                        {job.total_measures > 0 && ` • ${job.total_measures} bars`}
                      </span>
                      {job.created_at && (
                        <span className="flex items-center gap-1 text-[10px] text-slate-500">
                          <Clock className="w-3 h-3" />
                          {formatTime(job.created_at)}
                        </span>
                      )}
                    </div>

                    {/* Saved AI Helps Pill & Quick Reprocess Button */}
                    <div className="flex items-center justify-between pt-1 border-t border-slate-800/60 text-[10px]">
                      {hasHints ? (
                        <span className="inline-flex items-center gap-1 text-violet-300 font-mono">
                          <Sparkles className="w-3 h-3 text-amber-300 flex-shrink-0" />
                          <span className="truncate max-w-[170px]">
                            {hints.time_signature || '4/4'} • {hints.tempo_bpm ? `${Math.round(hints.tempo_bpm)} BPM` : '120 BPM'} • {hints.choral_voicing || 'SATB'}
                          </span>
                        </span>
                      ) : (
                        <span className="text-slate-500">Standard Defaults</span>
                      )}

                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          onOpenAiHelpsForJob(job)
                          setIsOpen(false)
                        }}
                        className="px-2 py-0.5 rounded bg-violet-600/20 hover:bg-violet-600/30 text-violet-300 border border-violet-500/30 font-semibold flex items-center gap-1 transition"
                        title="Open saved AI Helps and reprocess"
                      >
                        <Sparkles className="w-2.5 h-2.5 text-amber-300" />
                        <span>AI Helps</span>
                      </button>
                    </div>
                  </div>
                )
              })
            )}
          </div>

          {/* Footer */}
          <div className="px-4 py-2 bg-slate-950/80 border-t border-slate-800 text-[10px] text-slate-500 flex items-center justify-between">
            <span>Files preserved on disk — no re-upload required</span>
            <span className="text-sky-400 font-semibold">{jobs.length} / 10 loaded</span>
          </div>
        </div>
      )}
    </div>
  )
}
