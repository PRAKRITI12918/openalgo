/**
 * Execution Pipeline Visualizer.
 * Visualizes the 4-step institutional sequencing flow:
 * Ingest -> Tier 0 Hedge Confirmation -> Tier 1 Short Credit Execution -> Greeks Rebalance.
 */

import {
  ArrowRight,
  CheckCircle2,
  Cpu,
  Layers,
  Lock,
  RotateCcw,
  Shield,
  ShieldAlert,
  Sparkles,
  Zap,
} from 'lucide-react'
import { useExecutionStore } from '@/stores/executionStore'
import { Badge } from '@/components/ui/badge'

export function ExecutionPipelineVisualizer() {
  const { circuitBreakerActive, sequences } = useExecutionStore()

  const latestSequence = sequences[0]
  const isCircuitBreaker = circuitBreakerActive || latestSequence?.circuit_breaker_triggered

  const steps = [
    {
      step: 1,
      title: 'Signal Ingestion',
      subtitle: 'Pydantic V2 Validation',
      status: 'complete',
      badge: 'HTTP 202 / WS',
      desc: 'Strategy Engine JSON validated with zero naked exposure',
    },
    {
      step: 2,
      title: 'Tier 0: Hedge Protection',
      subtitle: 'Long Wings Execution (BUY)',
      status: isCircuitBreaker ? 'error' : 'complete',
      badge: 'Margin Lock',
      desc: 'Buy wings execute and confirm before short credit orders are sent',
    },
    {
      step: 3,
      title: 'Tier 1: Short Credit Legs',
      subtitle: 'Credit Legs Execution (SELL)',
      status: isCircuitBreaker ? 'halted' : 'complete',
      badge: 'Margin Reduced',
      desc: isCircuitBreaker
        ? 'Aborted immediately by circuit-breaker to prevent naked risk'
        : 'Short options executed under hedged margin discount',
    },
    {
      step: 4,
      title: 'Greek Risk Engine',
      subtitle: 'Real-time Greeks Rebalancing',
      status: isCircuitBreaker ? 'idle' : 'active',
      badge: 'Live Δ/θ/ν',
      desc: 'Dynamic Black-Scholes Delta neutralization & trailing exits',
    },
  ]

  return (
    <div className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl p-4 shadow-lg flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-cyan-400" />
          <h3 className="font-mono font-bold text-sm text-zinc-100 uppercase tracking-wider">
            Execution Flow & Safety Sequence Visualizer
          </h3>
        </div>
        <Badge
          variant="outline"
          className={`text-[10px] font-mono px-2 ${
            isCircuitBreaker
              ? 'border-red-500/50 bg-red-500/10 text-red-400'
              : 'border-emerald-500/50 bg-emerald-500/10 text-emerald-400'
          }`}
        >
          {isCircuitBreaker ? 'CIRCUIT BREAKER ENGAGED' : 'SEQUENCING NOMINAL'}
        </Badge>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 relative">
        {steps.map((s, idx) => (
          <div
            key={s.step}
            className={`p-3 rounded-lg border flex flex-col justify-between font-mono relative transition-all ${
              s.status === 'complete'
                ? 'bg-zinc-950/80 border-emerald-500/40 text-zinc-200'
                : s.status === 'active'
                ? 'bg-zinc-950/80 border-cyan-500/50 text-cyan-300 ring-1 ring-cyan-500/30'
                : s.status === 'error'
                ? 'bg-red-950/40 border-red-500 text-red-300'
                : s.status === 'halted'
                ? 'bg-amber-950/30 border-amber-500/40 text-amber-300'
                : 'bg-zinc-950/40 border-zinc-800 text-zinc-500'
            }`}
          >
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[10px] font-bold text-zinc-400">
                  PHASE 0{s.step}
                </span>
                <Badge
                  variant="secondary"
                  className="text-[9px] px-1.5 py-0 font-mono"
                >
                  {s.badge}
                </Badge>
              </div>
              <h4 className="text-xs font-bold text-zinc-100">{s.title}</h4>
              <p className="text-[11px] text-zinc-400 mt-0.5">{s.subtitle}</p>
            </div>

            <p className="text-[10px] text-zinc-400 mt-2 pt-2 border-t border-zinc-800/80 leading-relaxed">
              {s.desc}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
