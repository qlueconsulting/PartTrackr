import React, { useState } from 'react'
import {
  CheckCircle2,
  Circle,
  Loader2,
  AlertCircle,
  Layers,
  Cpu,
  GitBranch,
  Music2,
  FileCheck,
  Sparkles,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import type { PipelineStage, VerificationReport } from '../types'

interface PipelineStepperProps {
  currentStage: PipelineStage
  stageMessage: string
  totalMeasures: number
  verificationReport?: VerificationReport | null
  onOpenHintsModal?: () => void
}

interface StepConfig {
  key: PipelineStage
  label: string
  service: string
  port: string
  icon: React.ElementType
}

const STEPS: StepConfig[] = [
  { key: 'pending', label: 'File Intake', service: 'gateway-svc', port: '8005', icon: FileCheck },
  { key: 'layout', label: 'Layout & Crops', service: 'pdf-layout-svc', port: '8006', icon: Layers },
  { key: 'omr', label: 'Hybrid OMR', service: 'omr-ai-svc', port: '8007', icon: Cpu },
  { key: 'routing', label: '11-Part Voice Router', service: 'voice-router-svc', port: '8008', icon: GitBranch },
  { key: 'decoding', label: 'XML & MIDI Decoder', service: 'decoder-xml-svc', port: '8009', icon: Music2 },
]

export const PipelineStepper: React.FC<PipelineStepperProps> = ({
  currentStage,
  stageMessage,
  totalMeasures,
  verificationReport,
  onOpenHintsModal,
}) => {
  const [showVerificationDetails, setShowVerificationDetails] = useState<boolean>(false)

  const isAwaitingVerification = currentStage === 'awaiting_verification'
  const effectiveStage = isAwaitingVerification ? 'pending' : currentStage

  const stageOrder: PipelineStage[] = ['pending', 'layout', 'omr', 'routing', 'decoding', 'completed']
  const currentIndex = stageOrder.indexOf(effectiveStage === 'failed' ? 'decoding' : effectiveStage)

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-lg flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wider font-semibold text-sky-400">Pipeline Stepper</span>
          <span className="text-xs text-slate-500 font-mono">Microservices Orchestrator</span>
        </div>

        <div className="flex items-center gap-2">
          {verificationReport && (
            <button
              onClick={() => setShowVerificationDetails(!showVerificationDetails)}
              className="text-xs px-2.5 py-0.5 bg-emerald-950/90 text-emerald-300 border border-emerald-600/70 rounded-full font-mono flex items-center gap-1.5 hover:bg-emerald-900/60 transition cursor-pointer"
              title="Click to view closed-loop verification details"
            >
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>{verificationReport.match_score_pct}% Loop-Back Verified</span>
              {showVerificationDetails ? (
                <ChevronUp className="w-3 h-3 text-emerald-400" />
              ) : (
                <ChevronDown className="w-3 h-3 text-emerald-400" />
              )}
            </button>
          )}

          {totalMeasures > 0 && (
            <span className="text-xs px-2 py-0.5 bg-slate-950 text-slate-300 border border-slate-700 rounded-full font-mono">
              {totalMeasures} Measures
            </span>
          )}
        </div>
      </div>

      {/* Awaiting User Verification Action Callout */}
      {isAwaitingVerification && (
        <div className="p-3 bg-gradient-to-r from-violet-950/90 via-indigo-950/90 to-purple-950/90 border border-violet-500/60 rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-lg animate-in fade-in duration-300">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-violet-600/30 border border-violet-400/40 flex items-center justify-center text-amber-300 flex-shrink-0 animate-pulse">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h4 className="text-xs font-bold text-white flex items-center gap-1.5">
                <span>Initial Page 1 Scan Complete — Review AI Helps</span>
              </h4>
              <p className="text-[11px] text-violet-200/80">
                Default meter, tempo, and layout were analyzed. Click to verify before full score processing.
              </p>
            </div>
          </div>
          {onOpenHintsModal && (
            <button
              onClick={onOpenHintsModal}
              className="px-3.5 py-1.5 bg-gradient-to-r from-violet-500 to-indigo-600 hover:from-violet-400 hover:to-indigo-500 text-white font-bold text-xs rounded-lg shadow-md shadow-violet-600/30 flex items-center justify-center gap-1.5 cursor-pointer transition transform active:scale-95 flex-shrink-0"
            >
              <Sparkles className="w-3.5 h-3.5 text-amber-300" />
              <span>Open AI Helps & Verify</span>
            </button>
          )}
        </div>
      )}

      {/* Closed-Loop Verification Breakdown Dropdown */}
      {showVerificationDetails && verificationReport && (
        <div className="p-3 rounded-xl bg-slate-950 border border-emerald-900/60 text-xs animate-in slide-in-from-top-2 duration-200">
          <div className="flex items-center justify-between mb-2 pb-1.5 border-b border-slate-800">
            <span className="font-bold text-emerald-400 flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              Ground-Truth Loop-Back Invariant Report
            </span>
            <span className="font-mono text-[11px] text-slate-400">
              {verificationReport.passed_checks} of {verificationReport.total_checks} Checks Passed
            </span>
          </div>
          <div className="space-y-1.5">
            {verificationReport.checks.map((c, i) => (
              <div
                key={i}
                className="flex items-start justify-between gap-2 p-1.5 rounded bg-slate-900/80 border border-slate-800/80"
              >
                <div className="flex items-start gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold text-slate-200">{c.name}</span>
                    <span className="text-slate-400 text-[11px] block">{c.details}</span>
                  </div>
                </div>
                <span className="font-mono text-[10px] uppercase font-bold text-emerald-400 bg-emerald-950 px-1.5 py-0.5 rounded border border-emerald-800">
                  {c.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-5 gap-2 relative">
        {STEPS.map((step, idx) => {
          const Icon = step.icon
          const isDone = currentIndex > idx || currentStage === 'completed'
          const isCurrent = (currentStage === step.key || (isAwaitingVerification && step.key === 'pending'))
          const isFailed = currentStage === 'failed' && currentIndex === idx

          let statusBg = 'bg-slate-950 border-slate-800 text-slate-500'
          if (isDone) statusBg = 'bg-emerald-950/40 border-emerald-700/60 text-emerald-400'
          if (isCurrent && isAwaitingVerification) {
            statusBg = 'bg-violet-950/60 border-violet-500 text-violet-300 ring-2 ring-violet-500/20'
          } else if (isCurrent) {
            statusBg = 'bg-sky-950/60 border-sky-500 text-sky-300 ring-2 ring-sky-500/20'
          }
          if (isFailed) statusBg = 'bg-rose-950/60 border-rose-500 text-rose-300'

          return (
            <div
              key={step.key}
              className={`flex flex-col p-2.5 rounded-lg border transition-all duration-300 ${statusBg}`}
            >
              <div className="flex items-center justify-between mb-1.5">
                <Icon className="w-4 h-4 opacity-80" />
                {isDone && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                {isCurrent && isAwaitingVerification && (
                  <Sparkles className="w-4 h-4 text-amber-300 animate-pulse" />
                )}
                {isCurrent && !isAwaitingVerification && (
                  <Loader2 className="w-4 h-4 text-sky-400 animate-spin" />
                )}
                {isFailed && <AlertCircle className="w-4 h-4 text-rose-400" />}
                {!isDone && !isCurrent && !isFailed && <Circle className="w-3.5 h-3.5 text-slate-700" />}
              </div>
              <span className="text-xs font-semibold leading-tight">
                {isAwaitingVerification && step.key === 'pending' ? 'Verification' : step.label}
              </span>
              <div className="flex items-center justify-between mt-1 text-[10px] text-slate-400 font-mono">
                <span>{step.service}</span>
                <span className="opacity-60">:{step.port}</span>
              </div>
            </div>
          )
        })}
      </div>

      <div className="text-xs text-slate-300 flex items-center gap-2 bg-slate-950/60 px-3 py-1.5 rounded-md border border-slate-800/80">
        <span className="font-semibold text-slate-400">Status:</span>
        <span className="font-mono text-sky-300 truncate">{stageMessage}</span>
      </div>
    </div>
  )
}
