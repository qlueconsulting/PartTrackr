import React, { useState, useRef, useEffect } from 'react'
import {
  Terminal,
  Trash2,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Filter,
  ArrowDown,
  AlertCircle,
  CheckCircle2,
  Info,
  AlertTriangle,
} from 'lucide-react'
import type { ApiLogEntry } from '../types'

interface ApiLogViewerProps {
  logs: ApiLogEntry[]
  onClearLogs: () => void
}

export const ApiLogViewer: React.FC<ApiLogViewerProps> = ({ logs, onClearLogs }) => {
  const [filterLevel, setFilterLevel] = useState<string>('all')
  const [copied, setCopied] = useState<boolean>(false)
  const [autoScroll, setAutoScroll] = useState<boolean>(true)
  const [expandedLogIds, setExpandedLogIds] = useState<Set<string>>(new Set())
  const logEndRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (autoScroll && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, autoScroll])

  const toggleExpand = (id: string) => {
    setExpandedLogIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleCopyLogs = () => {
    const text = logs
      .map(
        (l) =>
          `[${l.timestamp}] [${l.level.toUpperCase()}] [${l.service}] ${l.message}${
            l.details ? '\n' + JSON.stringify(l.details, null, 2) : ''
          }`
      )
      .join('\n')
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const filteredLogs = logs.filter((l) => {
    if (filterLevel === 'all') return true
    return l.level === filterLevel
  })

  const getLevelBadge = (level: string) => {
    switch (level) {
      case 'error':
        return (
          <span className="flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded bg-rose-950 text-rose-400 border border-rose-800">
            <AlertCircle className="w-3 h-3" /> ERROR
          </span>
        )
      case 'warn':
        return (
          <span className="flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-950 text-amber-400 border border-amber-800">
            <AlertTriangle className="w-3 h-3" /> WARN
          </span>
        )
      case 'success':
        return (
          <span className="flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">
            <CheckCircle2 className="w-3 h-3" /> SUCCESS
          </span>
        )
      default:
        return (
          <span className="flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded bg-sky-950 text-sky-400 border border-sky-800">
            <Info className="w-3 h-3" /> INFO
          </span>
        )
    }
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl flex flex-col h-full font-mono text-xs">
      {/* Top Console Bar */}
      <div className="bg-slate-950/80 px-4 py-2 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-emerald-400" />
          <span className="text-xs uppercase tracking-wider font-semibold text-slate-200">
            API & Pipeline Telemetry Live Logs
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-mono">
            {logs.length} events
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Level Filter */}
          <div className="flex items-center gap-1 bg-slate-900 px-2 py-1 rounded border border-slate-800 text-[10px]">
            <Filter className="w-3 h-3 text-slate-400" />
            <select
              value={filterLevel}
              onChange={(e) => setFilterLevel(e.target.value)}
              className="bg-transparent text-slate-300 focus:outline-none cursor-pointer"
            >
              <option value="all">All Levels</option>
              <option value="info">Info</option>
              <option value="success">Success</option>
              <option value="warn">Warnings</option>
              <option value="error">Errors</option>
            </select>
          </div>

          {/* Auto-scroll toggle */}
          <button
            onClick={() => setAutoScroll((a) => !a)}
            className={`p-1 rounded text-[10px] flex items-center gap-1 border ${
              autoScroll
                ? 'bg-emerald-950/50 text-emerald-400 border-emerald-800'
                : 'bg-slate-800 text-slate-400 border-slate-700'
            }`}
            title="Toggle Auto-Scroll"
          >
            <ArrowDown className="w-3 h-3" />
            <span>Auto</span>
          </button>

          {/* Copy Logs */}
          <button
            onClick={handleCopyLogs}
            className="p-1.5 hover:bg-slate-800 text-slate-300 rounded border border-slate-800 transition"
            title="Copy Logs"
          >
            {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
          </button>

          {/* Clear Logs */}
          <button
            onClick={onClearLogs}
            className="p-1.5 hover:bg-slate-800 text-slate-300 hover:text-rose-400 rounded border border-slate-800 transition"
            title="Clear Logs"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Log Feed */}
      <div className="flex-1 p-3 overflow-auto bg-slate-950 space-y-2 select-text">
        {filteredLogs.length === 0 ? (
          <div className="h-full flex items-center justify-center text-slate-600 italic">
            No telemetry events recorded yet. Upload a PDF or trigger a pipeline action.
          </div>
        ) : (
          filteredLogs.map((entry) => {
            const isExpanded = expandedLogIds.has(entry.id)
            const hasDetails = entry.details !== undefined && entry.details !== null

            return (
              <div
                key={entry.id}
                className="p-2 rounded bg-slate-900/60 border border-slate-850 hover:border-slate-700 transition"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[10px] text-slate-500 font-mono">{entry.timestamp}</span>
                    {getLevelBadge(entry.level)}
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                      {entry.service}
                    </span>
                    <span className="text-slate-200 text-xs font-sans break-all">{entry.message}</span>
                  </div>

                  {hasDetails && (
                    <button
                      onClick={() => toggleExpand(entry.id)}
                      className="text-slate-400 hover:text-sky-400 p-0.5"
                    >
                      {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                    </button>
                  )}
                </div>

                {hasDetails && isExpanded && (
                  <div className="mt-2 p-2 bg-slate-950 rounded border border-slate-800 overflow-x-auto text-[11px] text-slate-300 leading-relaxed font-mono">
                    <pre>{typeof entry.details === 'object' ? JSON.stringify(entry.details, null, 2) : entry.details}</pre>
                  </div>
                )}
              </div>
            )
          })
        )}
        <div ref={logEndRef} />
      </div>
    </div>
  )
}
