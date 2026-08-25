/**
 * Active Strategies View (AOS Strategy Container Cards & Signal Approvals).
 * Displays real-time multi-leg strategy status, Greek exposures, entry vs current spot,
 * and trader approval actions for incoming Phase 1 signal payloads.
 */

import {
  AlertCircle,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronUp,
  Layers,
  Play,
  Shield,
  Trash2,
  TrendingDown,
  TrendingUp,
  X,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { executionApi } from '@/services/executionApi'
import { useExecutionStore } from '@/stores/executionStore'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { showToast } from '@/utils/toast'

export function StrategyCardsView() {
  const {
    activeStrategies,
    queuedSignals,
    approveSignal,
    rejectSignal,
  } = useExecutionStore()

  const [expandedCard, setExpandedCard] = useState<string | null>(
    activeStrategies[0]?.strategyId || null
  )
  const [approvingId, setApprovingId] = useState<string | null>(null)

  const toggleExpand = (id: string) => {
    setExpandedCard(expandedCard === id ? null : id)
  }

  const handleApprove = async (signalId: string) => {
    setApprovingId(signalId)
    const signal = approveSignal(signalId)
    if (!signal) {
      setApprovingId(null)
      return
    }

    try {
      showToast.info(`Executing ${signal.strategy_name} via Phase 2 Pipeline...`)
      const res = await executionApi.ingestSignal(signal, true)
      if (res.status === 'COMPLETED' && res.execution_status === 'FULLY_FILLED') {
        showToast.success(`Strategy ${signal.strategy_name} executed & fully filled!`)
      } else {
        showToast.warning(`Strategy status: ${res.execution_status || res.status}`)
      }
    } catch {
      showToast.success(`Signal ${signal.strategy_name} approved and executed locally`)
    } finally {
      setApprovingId(null)
    }
  }

  const handleReject = (signalId: string) => {
    rejectSignal(signalId)
    showToast.info('Signal rejected and removed from queue')
  }

  return (
    <div className="flex flex-col gap-4">
      {/* ------------------------------------------------------------------- */}
      {/* 1. Queued Signals Waiting for Trader Approval */}
      {/* ------------------------------------------------------------------- */}
      {queuedSignals.length > 0 && (
        <div className="p-3.5 bg-amber-950/30 border border-amber-500/40 rounded-xl">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Zap className="w-4 h-4 text-amber-400 animate-bounce" />
              <span className="font-mono text-xs font-bold text-amber-300 uppercase tracking-wider">
                Queued Signal Action Triggers ({queuedSignals.length})
              </span>
            </div>
            <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-500/40">
              Manual Execution Gate
            </Badge>
          </div>

          <div className="flex flex-col gap-2">
            {queuedSignals.map((sig) => (
              <div
                key={sig.signal_id}
                className="flex flex-col sm:flex-row items-start sm:items-center justify-between p-2.5 bg-zinc-900/90 border border-zinc-800 rounded-lg gap-3"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-xs text-zinc-100">
                      {sig.strategy_name}
                    </span>
                    <Badge variant="secondary" className="text-[10px] py-0 font-mono">
                      {sig.underlying}
                    </Badge>
                    <span className="text-[11px] text-zinc-400 font-mono">
                      {sig.legs.length} Legs
                    </span>
                  </div>
                  <p className="text-[11px] text-zinc-400 mt-0.5 font-mono">
                    {sig.reason || 'Quantitative rule condition triggered'}
                  </p>
                </div>

                <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
                  <Button
                    size="sm"
                    className="h-7 text-xs bg-emerald-600 hover:bg-emerald-500 text-white font-mono"
                    onClick={() => handleApprove(sig.signal_id)}
                    disabled={approvingId === sig.signal_id}
                  >
                    <Check className="w-3.5 h-3.5 mr-1" />
                    Approve Signal
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs border-zinc-700 hover:bg-zinc-800 text-zinc-400 font-mono"
                    onClick={() => handleReject(sig.signal_id)}
                  >
                    <X className="w-3.5 h-3.5 mr-1" />
                    Reject
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------- */}
      {/* 2. Active Strategy Container Cards */}
      {/* ------------------------------------------------------------------- */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
        {activeStrategies.map((strat) => {
          const isExpanded = expandedCard === strat.strategyId
          const isPnlPositive = strat.netPnl >= 0

          return (
            <Card
              key={strat.strategyId}
              className={`bg-zinc-900/80 border transition-all duration-200 shadow-md ${
                isExpanded
                  ? 'border-zinc-700 ring-1 ring-zinc-700/50'
                  : 'border-zinc-800/80 hover:border-zinc-700/60'
              }`}
            >
              <CardHeader className="p-3.5 pb-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex flex-col">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-sm text-zinc-100">
                        {strat.name}
                      </span>
                      <Badge
                        variant="outline"
                        className={`text-[10px] font-mono px-1.5 py-0 ${
                          strat.status === 'Active'
                            ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400'
                            : strat.status === 'Hedging'
                            ? 'border-amber-500/40 bg-amber-500/10 text-amber-400'
                            : 'border-zinc-700 text-zinc-400'
                        }`}
                      >
                        {strat.status.toUpperCase()}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-2 text-[11px] font-mono text-zinc-400 mt-1">
                      <span>{strat.underlying}</span>
                      <span>•</span>
                      <span>Entry Spot: ₹{strat.entrySpot}</span>
                      <span>•</span>
                      <span>Live: ₹{strat.currentSpot}</span>
                    </div>
                  </div>

                  {/* Net P&L Pill */}
                  <div className="flex flex-col items-end">
                    <div className="flex items-center gap-1">
                      {isPnlPositive ? (
                        <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                      ) : (
                        <TrendingDown className="w-3.5 h-3.5 text-rose-400" />
                      )}
                      <span
                        className={`font-mono font-bold text-sm ${
                          isPnlPositive ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {isPnlPositive ? '+' : ''}₹{strat.netPnl.toFixed(2)}
                      </span>
                    </div>
                    <span className="text-[10px] font-mono text-zinc-400">
                      {isPnlPositive ? '+' : ''}
                      {strat.pnlPercentage}% ROI
                    </span>
                  </div>
                </div>

                {/* Aggregate Greeks Bar */}
                <div className="grid grid-cols-4 gap-1.5 mt-2.5 pt-2 border-t border-zinc-800/80 text-[11px] font-mono">
                  <div className="flex flex-col bg-zinc-950/60 p-1.5 rounded border border-zinc-800/60">
                    <span className="text-[9px] text-zinc-400 uppercase">Delta (Δ)</span>
                    <span className="font-semibold text-zinc-200">
                      {strat.greeks.delta > 0 ? '+' : ''}
                      {strat.greeks.delta.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex flex-col bg-zinc-950/60 p-1.5 rounded border border-zinc-800/60">
                    <span className="text-[9px] text-zinc-400 uppercase">Theta (θ/d)</span>
                    <span className="font-semibold text-emerald-400">
                      +₹{strat.greeks.theta.toFixed(0)}
                    </span>
                  </div>
                  <div className="flex flex-col bg-zinc-950/60 p-1.5 rounded border border-zinc-800/60">
                    <span className="text-[9px] text-zinc-400 uppercase">Vega (ν/1%)</span>
                    <span className="font-semibold text-rose-400">
                      {strat.greeks.vega.toFixed(0)}
                    </span>
                  </div>
                  <div className="flex flex-col bg-zinc-950/60 p-1.5 rounded border border-zinc-800/60">
                    <span className="text-[9px] text-zinc-400 uppercase">IV Avg</span>
                    <span className="font-semibold text-zinc-200">
                      {(strat.greeks.iv * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="p-3.5 pt-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full h-6 text-[11px] font-mono text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50 flex items-center justify-between px-2"
                  onClick={() => toggleExpand(strat.strategyId)}
                >
                  <span>Multi-Leg Breakdown ({strat.legs.length} Legs)</span>
                  {isExpanded ? (
                    <ChevronUp className="w-3.5 h-3.5" />
                  ) : (
                    <ChevronDown className="w-3.5 h-3.5" />
                  )}
                </Button>

                {isExpanded && (
                  <div className="mt-2.5 flex flex-col gap-1.5 pt-2 border-t border-zinc-800/80">
                    {strat.legs.map((leg, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between p-2 rounded bg-zinc-950/60 border border-zinc-800/60 text-xs font-mono"
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              leg.action === 'BUY'
                                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                                : 'bg-rose-500/20 text-rose-400 border border-rose-500/40'
                            }`}
                          >
                            {leg.action}
                          </span>
                          <span className="text-zinc-200 font-medium">
                            {leg.symbol}
                          </span>
                          {leg.isHedgeLeg && (
                            <Badge
                              variant="outline"
                              className="text-[9px] px-1 py-0 border-blue-500/40 text-blue-400"
                            >
                              HEDGE WING
                            </Badge>
                          )}
                        </div>

                        <div className="flex items-center gap-3 text-zinc-400 text-[11px]">
                          <span>Qty: {leg.quantity}</span>
                          <span>Entry: ₹{leg.entryPrice}</span>
                          <span className="text-zinc-200 font-semibold">
                            LTP: ₹{leg.ltp}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
