import React from 'react'
import { CheckCircle2, Circle, Loader2, AlertCircle, Layers, Cpu, GitBranch, Music2, FileCheck } from 'lucide-react'
import type { PipelineStage } from '../types'

interface PipelineStepperProps {
  currentStage: PipelineStage
  stageMessage: string
  totalMeasures: number
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
  totalMeasures
}) => {
  const stageOrder: PipelineStage[] = ['pending', 'layout', 'omr', 'routing', 'decoding', 'completed']
  const currentIndex = stageOrder.indexOf(currentStage === 'failed' ? 'decoding' : currentStage)

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-lg">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wider font-semibold text-sky-400">Pipeline Stepper</span>
          <span className="text-xs text-slate-500 font-mono">Microservices Orchestrator</span>
        </div>
        {totalMeasures > 0 && (
          <span className="text-xs px-2 py-0.5 bg-emerald-950/80 text-emerald-400 border border-emerald-800 rounded-full font-mono">
            {totalMeasures} Measures Compiled
          </span>
        )}
      </div>

      <div className="grid grid-cols-5 gap-2 relative">
        {STEPS.map((step, idx) => {
          const Icon = step.icon
          const isDone = currentIndex > idx || currentStage === 'completed'
          const isCurrent = currentStage === step.key
          const isFailed = currentStage === 'failed' && currentIndex === idx

          let statusBg = 'bg-slate-950 border-slate-800 text-slate-500'
          if (isDone) statusBg = 'bg-emerald-950/40 border-emerald-700/60 text-emerald-400'
          if (isCurrent) statusBg = 'bg-sky-950/60 border-sky-500 text-sky-300 ring-2 ring-sky-500/20'
          if (isFailed) statusBg = 'bg-rose-950/60 border-rose-500 text-rose-300'

          return (
            <div
              key={step.key}
              className={`flex flex-col p-2.5 rounded-lg border transition-all duration-300 ${statusBg}`}
            >
              <div className="flex items-center justify-between mb-1.5">
                <Icon className="w-4 h-4 opacity-80" />
                {isDone && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                {isCurrent && <Loader2 className="w-4 h-4 text-sky-400 animate-spin" />}
                {isFailed && <AlertCircle className="w-4 h-4 text-rose-400" />}
                {!isDone && !isCurrent && !isFailed && <Circle className="w-3.5 h-3.5 text-slate-700" />}
              </div>
              <span className="text-xs font-semibold leading-tight">{step.label}</span>
              <div className="flex items-center justify-between mt-1 text-[10px] text-slate-400 font-mono">
                <span>{step.service}</span>
                <span className="opacity-60">:{step.port}</span>
              </div>
            </div>
          )
        })}
      </div>

      <div className="mt-2.5 text-xs text-slate-300 flex items-center gap-2 bg-slate-950/60 px-3 py-1.5 rounded-md border border-slate-800/80">
        <span className="font-semibold text-slate-400">Status:</span>
        <span className="font-mono text-sky-300 truncate">{stageMessage}</span>
      </div>
    </div>
  )
}
