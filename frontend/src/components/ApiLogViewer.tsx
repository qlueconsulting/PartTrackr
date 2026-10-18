import React, { useState, useRef, useEffect, useMemo } from 'react'
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
  RefreshCw,
  Search,
  Maximize2,
  Minimize2,
} from 'lucide-react'
import type { ApiLogEntry } from '../types'

interface ApiLogViewerProps {
  logs: ApiLogEntry[]
  onClearLogs: () => void
  onRefreshLogs?: () => void
  isLoading?: boolean
}

export const ApiLogViewer: React.FC<ApiLogViewerProps> = ({
  logs,
  onClearLogs,
  onRefreshLogs,
  isLoading = false,
}) => {
  const [filterLevel, setFilterLevel] = useState<string>('all')
  const [filterService, setFilterService] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [copied, setCopied] = useState<boolean>(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [autoScroll, setAutoScroll] = useState<boolean>(true)
  const [expandedLogIds, setExpandedLogIds] = useState<Set<string>>(new Set())
  const logEndRef = useRef<HTMLDivElement | null>(null)

  // Auto-expand any error logs as they arrive
  useEffect(() => {
    const errorIds = logs.filter((l) => l.level === 'error').map((l) => l.id)
    if (errorIds.length > 0) {
      setExpandedLogIds((prev) => {
        const next = new Set(prev)
        let changed = false
        for (const id of errorIds) {
          if (!next.has(id)) {
            next.add(id)
            changed = true
          }
        }
        return changed ? next : prev
      })
    }
  }, [logs])

  // Auto-scroll to bottom when new logs appear
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

  const expandAll = () => {
    setExpandedLogIds(new Set(logs.map((l) => l.id)))
  }

  const collapseAll = () => {
    setExpandedLogIds(new Set())
  }

  const handleCopyLogs = () => {
    const text = logs
      .map(
        (l) =>
          `[${l.timestamp}] [${l.level.toUpperCase()}] [${l.service}] ${l.message}${
            l.details ? '\n' + (typeof l.details === 'object' ? JSON.stringify(l.details, null, 2) : l.details) : ''
          }`
      )
      .join('\n')
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleCopySingle = (entry: ApiLogEntry) => {
    const text = `[${entry.timestamp}] [${entry.level.toUpperCase()}] [${entry.service}] ${entry.message}${
      entry.details ? '\n' + (typeof entry.details === 'object' ? JSON.stringify(entry.details, null, 2) : entry.details) : ''
    }`
    navigator.clipboard.writeText(text)
    setCopiedId(entry.id)
    setTimeout(() => setCopiedId(null), 1500)
  }

  // Extract unique services from logs for the dropdown
  const availableServices = useMemo(() => {
    const set = new Set<string>()
    logs.forEach((l) => {
      if (l.service) set.add(l.service)
    })
    return Array.from(set).sort()
  }, [logs])

  // Filter logs by level, service, and search query
  const filteredLogs = useMemo(() => {
    return logs.filter((l) => {
      if (filterLevel !== 'all' && l.level !== filterLevel) return false
      if (filterService !== 'all' && l.service !== filterService) return false
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const matchMsg = l.message.toLowerCase().includes(q)
        const matchSvc = l.service.toLowerCase().includes(q)
        const matchDetails = l.details ? JSON.stringify(l.details).toLowerCase().includes(q) : false
        if (!matchMsg && !matchSvc && !matchDetails) return false
      }
      return true
    })
  }, [logs, filterLevel, filterService, searchQuery])

  const errorCount = useMemo(() => logs.filter((l) => l.level === 'error').length, [logs])
  const warnCount = useMemo(() => logs.filter((l) => l.level === 'warn').length, [logs])

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

  const getServiceColor = (service: string) => {
    switch (service) {
      case 'gateway-svc':
        return 'bg-blue-950 text-blue-300 border-blue-800'
      case 'pdf-layout-svc':
        return 'bg-indigo-950 text-indigo-300 border-indigo-800'
      case 'omr-ai-svc':
        return 'bg-purple-950 text-purple-300 border-purple-800'
      case 'voice-router-svc':
        return 'bg-teal-950 text-teal-300 border-teal-800'
      case 'decoder-xml-svc':
        return 'bg-cyan-950 text-cyan-300 border-cyan-800'
      case 'client':
        return 'bg-slate-800 text-slate-300 border-slate-700'
      default:
        return 'bg-slate-800 text-slate-300 border-slate-700'
    }
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl flex flex-col h-full font-mono text-xs">
      {/* Top Console Bar */}
      <div className="bg-slate-950/90 px-3 py-2 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-emerald-400" />
          <span className="text-xs uppercase tracking-wider font-semibold text-slate-200">
            API & Microservices Telemetry
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-mono">
            {filteredLogs.length} / {logs.length}
          </span>
          {errorCount > 0 && (
            <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-rose-950 text-rose-300 border border-rose-800 font-bold animate-pulse">
              <AlertCircle className="w-3 h-3 text-rose-400" />
              {errorCount} error{errorCount > 1 ? 's' : ''}
            </span>
          )}
          {warnCount > 0 && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-950 text-amber-300 border border-amber-800 font-semibold">
              {warnCount} warn
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Search Box */}
          <div className="flex items-center gap-1 bg-slate-900 px-2 py-1 rounded border border-slate-800 text-[10px]">
            <Search className="w-3 h-3 text-slate-400" />
            <input
              type="text"
              placeholder="Search logs..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="bg-transparent text-slate-200 placeholder-slate-500 focus:outline-none w-24 sm:w-32"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="text-slate-400 hover:text-slate-200 text-xs px-0.5"
              >
                ×
              </button>
            )}
          </div>

          {/* Microservice Filter */}
          <div className="flex items-center gap-1 bg-slate-900 px-2 py-1 rounded border border-slate-800 text-[10px]">
            <span className="text-slate-400">Svc:</span>
            <select
              value={filterService}
              onChange={(e) => setFilterService(e.target.value)}
              className="bg-transparent text-slate-300 focus:outline-none cursor-pointer"
            >
              <option value="all">All Services</option>
              {availableServices.map((svc) => (
                <option key={svc} value={svc}>
                  {svc}
                </option>
              ))}
            </select>
          </div>

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

          {/* Expand/Collapse All */}
          <button
            onClick={expandedLogIds.size > 0 ? collapseAll : expandAll}
            className="p-1.5 hover:bg-slate-800 text-slate-300 rounded border border-slate-800 transition"
            title={expandedLogIds.size > 0 ? 'Collapse All' : 'Expand All'}
          >
            {expandedLogIds.size > 0 ? <Minimize2 className="w-3 h-3" /> : <Maximize2 className="w-3 h-3" />}
          </button>

          {/* Auto-scroll toggle */}
          <button
            onClick={() => setAutoScroll((a) => !a)}
            className={`p-1.5 rounded text-[10px] flex items-center gap-1 border transition ${
              autoScroll
                ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800'
                : 'bg-slate-800 text-slate-400 border-slate-700'
            }`}
            title="Toggle Auto-Scroll"
          >
            <ArrowDown className="w-3 h-3" />
            <span className="hidden sm:inline">Auto</span>
          </button>

          {/* Refresh backend logs */}
          {onRefreshLogs && (
            <button
              onClick={onRefreshLogs}
              disabled={isLoading}
              className={`p-1.5 hover:bg-slate-800 text-slate-300 rounded border border-slate-800 transition ${
                isLoading ? 'opacity-50 animate-spin text-sky-400' : ''
              }`}
              title="Refresh Logs from Gateway"
            >
              <RefreshCw className="w-3 h-3" />
            </button>
          )}

          {/* Copy All Logs */}
          <button
            onClick={handleCopyLogs}
            className="p-1.5 hover:bg-slate-800 text-slate-300 rounded border border-slate-800 transition"
            title="Copy All Logs"
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
          <div className="h-full flex flex-col items-center justify-center text-slate-500 italic p-6 gap-2">
            <Terminal className="w-8 h-8 text-slate-700 mb-1" />
            <span>No telemetry events matching the current filter.</span>
            {logs.length > 0 && (
              <button
                onClick={() => {
                  setFilterLevel('all')
                  setFilterService('all')
                  setSearchQuery('')
                }}
                className="text-xs text-sky-400 hover:underline not-italic mt-1"
              >
                Reset filters
              </button>
            )}
          </div>
        ) : (
          filteredLogs.map((entry) => {
            const isExpanded = expandedLogIds.has(entry.id)
            const hasDetails = entry.details !== undefined && entry.details !== null
            const isError = entry.level === 'error'

            return (
              <div
                key={entry.id}
                className={`p-2.5 rounded transition ${
                  isError
                    ? 'bg-rose-950/30 border border-rose-800/80 shadow-sm'
                    : 'bg-slate-900/60 border border-slate-800/70 hover:border-slate-700'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 flex-wrap flex-1">
                    <span className="text-[10px] text-slate-500 font-mono select-none">{entry.timestamp}</span>
                    {getLevelBadge(entry.level)}
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded border font-mono ${getServiceColor(
                        entry.service
                      )}`}
                    >
                      {entry.service}
                    </span>
                    <span
                      className={`text-xs font-sans break-all ${
                        isError ? 'text-rose-200 font-medium' : 'text-slate-200'
                      }`}
                    >
                      {entry.message}
                    </span>
                  </div>

                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => handleCopySingle(entry)}
                      className="text-slate-500 hover:text-slate-300 p-1 rounded hover:bg-slate-800/60 transition"
                      title="Copy Entry"
                    >
                      {copiedId === entry.id ? (
                        <Check className="w-3 h-3 text-emerald-400" />
                      ) : (
                        <Copy className="w-3 h-3" />
                      )}
                    </button>
                    {hasDetails && (
                      <button
                        onClick={() => toggleExpand(entry.id)}
                        className="text-slate-400 hover:text-sky-400 p-1 rounded hover:bg-slate-800/60 transition"
                        title={isExpanded ? 'Collapse' : 'Expand'}
                      >
                        {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                      </button>
                    )}
                  </div>
                </div>

                {hasDetails && isExpanded && (
                  <div
                    className={`mt-2 p-2.5 rounded border overflow-x-auto text-[11px] leading-relaxed font-mono ${
                      isError
                        ? 'bg-black/80 border-rose-900/80 text-rose-300'
                        : 'bg-slate-950 border-slate-850 text-slate-300'
                    }`}
                  >
                    <pre className="whitespace-pre-wrap break-all">
                      {typeof entry.details === 'object'
                        ? JSON.stringify(entry.details, null, 2)
                        : entry.details}
                    </pre>
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
