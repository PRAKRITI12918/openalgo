/**
 * Active Strategies View (AOS Strategy Container Cards & Signal Approvals).
 * Displays real-time multi-leg strategy status, Greek exposures, entry vs current spot,
 * and trader approval actions for incoming Phase 1 signal payloads.
 *
 * HARD CONSTRAINTS:
 * - NO fake/mock data in production mode: Uses genuine empty states when empty.
 * - Honest LTP & Greeks: Shows '—' / 'LTP unavailable' if unconfirmed.
 * - Handles real backend error responses on approval / rejection.
 */

import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronUp,
  Cpu,
  HelpCircle,
  Layers,
  Play,
  RefreshCw,
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { showToast } from '@/utils/toast'

/** Renders normalized signal status badge matching the 8 mandated enum values */
function getSignalStatusBadge(status: string) {
  const norm = status?.toUpperCase() || 'RECEIVED'
  switch (norm) {
    case 'RECEIVED':
      return (
        <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0 border-zinc-700 bg-zinc-800/40 text-zinc-300">
          RECEIVED
        </Badge>
      )
    case 'VALIDATED':
      return (
        <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0 border-cyan-500/40 bg-cyan-500/10 text-cyan-400">
          VALIDATED
        </Badge>
      )
    case 'PENDING_APPROVAL':
      return (
        <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0 border-amber-500/40 bg-amber-500/10 text-amber-400">
          PENDING_APPROVAL
        </Badge>
      )
    case 'APPROVED':
      return (
        <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0 border-emerald-500/40 bg-emerald-500/10 text-emerald-400">
          APPROVED
        </Badge>
      )
    case 'REJECTED':
      return (
        <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0 border-rose-500/40 bg-rose-500/10 text-rose-400">
          REJECTED
        </Badge>
      )
    case 'EXECUTING':
      return (
        <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0 border-blue-500/40 bg-blue-500/10 text-blue-400 animate-pulse">
          EXECUTING
        </Badge>
      )
    case 'COMPLETED':
    case 'ACTIVE':
    case 'FILLED':
      return (
        <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0 border-emerald-500/40 bg-emerald-500/10 text-emerald-400">
          COMPLETED
        </Badge>
      )
    case 'FAILED':
      return (
        <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0 border-rose-500/40 bg-rose-500/10 text-rose-400">
          FAILED
        </Badge>
      )
    default:
      return (
        <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0 border-zinc-700 text-zinc-400">
          {norm}
        </Badge>
      )
  }
}

export function StrategyCardsView() {
  const {
    activeStrategies,
    pendingSignals,
    activeAccount,
    brokerStatus,
    loadingStates,
    errorStates,
    refreshAllData,
  } = useExecutionStore()

  const [expandedCard, setExpandedCard] = useState<string | null>(null)
  const [approvingId, setApprovingId] = useState<string | null>(null)
  const [rejectingId, setRejectingId] = useState<string | null>(null)
  
  // High-friction approval confirmation dialog
  const [signalToApprove, setSignalToApprove] = useState<any | null>(null)
  // Rejection confirmation dialog with optional reason field
  const [signalToReject, setSignalToReject] = useState<any | null>(null)
  const [rejectionReason, setRejectionReason] = useState<string>('')

  // Live execution progress state
  const [executingSignalId, setExecutingSignalId] = useState<string | null>(null)
  const [executionProgress, setExecutionProgress] = useState<any | null>(null)

  const isLoading = loadingStates.signals
  const isConnected = brokerStatus === 'CONNECTED'

  const toggleExpand = (id: string) => {
    setExpandedCard(expandedCard === id ? null : id)
  }

  const handleConfirmApproval = async () => {
    if (!signalToApprove) return
    const signalId = signalToApprove.signal_id
    const strategyName = signalToApprove.strategy_name
    setApprovingId(signalId)

    try {
      showToast.info('Signal approved — execution started')
      const approveRes = await executionApi.approvePendingSignal(signalId)
      setSignalToApprove(null)
      setExecutingSignalId(signalId)

      // Initial progress fetch
      try {
        const initialProg = await executionApi.getSignalProgress(signalId)
        setExecutionProgress(initialProg)
      } catch (err) {
        // Fallback to approval response sequence
        if (approveRes?.sequence) {
          setExecutionProgress({
            signal_id: signalId,
            status: approveRes.status || 'EXECUTING',
            strategy_name: strategyName,
            legs: approveRes.sequence.leg_states || [],
          })
        }
      }

      await refreshAllData()

      // Active polling for execution progress until terminal state
      const pollTimer = setInterval(async () => {
        try {
          const prog = await executionApi.getSignalProgress(signalId)
          setExecutionProgress(prog)

          if (['APPROVED', 'COMPLETED', 'FAILED', 'REJECTED'].includes(prog.status)) {
            clearInterval(pollTimer)
            await refreshAllData()
            if (prog.status === 'APPROVED' || prog.status === 'COMPLETED') {
              showToast.success(`Signal ${strategyName} execution completed!`)
            } else if (prog.status === 'FAILED') {
              showToast.error(`Execution failed: ${prog.error_message || 'Order rejected by broker or circuit breaker'}`)
            }
          }
        } catch {
          clearInterval(pollTimer)
        }
      }, 1000)
    } catch (err: any) {
      const msg = err?.response?.data?.detail?.message || err?.response?.data?.detail || err.message || 'Approval failed'
      showToast.error(`Approval failed: ${msg}`)
    } finally {
      setApprovingId(null)
    }
  }

  const handleConfirmRejection = async () => {
    if (!signalToReject) return
    const signalId = signalToReject.signal_id
    setRejectingId(signalId)
    try {
      await executionApi.rejectPendingSignal(
        signalId,
        rejectionReason || 'Manual trader rejection from HUD'
      )
      showToast.success('Signal rejected.')
      setSignalToReject(null)
      setRejectionReason('')
      await refreshAllData()
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail?.message ||
        err?.response?.data?.detail ||
        err.message ||
        'Rejection failed'
      showToast.error(`Rejection failed: ${msg}`)
    } finally {
      setRejectingId(null)
    }
  }

  return (
    <TooltipProvider>
      <div className="flex flex-col gap-4">
        {/* ------------------------------------------------------------------- */}
        {/* 0. Live Execution Progress HUD (Shown when order execution is active) */}
        {/* ------------------------------------------------------------------- */}
        {executionProgress && (
          <div className="p-3.5 bg-blue-950/40 border border-blue-500/50 rounded-xl shadow-xl font-mono">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Play className="w-4 h-4 text-blue-400 animate-pulse" />
                <span className="text-xs font-bold text-blue-300 uppercase tracking-wider">
                  Live Execution Progress: {executionProgress.strategy_name}
                </span>
                {getSignalStatusBadge(executionProgress.status)}
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 text-[11px] text-zinc-400 hover:text-zinc-100"
                onClick={() => {
                  setExecutionProgress(null)
                  setExecutingSignalId(null)
                }}
              >
                Dismiss
              </Button>
            </div>

            {executionProgress.legs && executionProgress.legs.length > 0 && (
              <div className="overflow-x-auto mt-2">
                <table className="w-full text-[11px] text-left">
                  <thead className="bg-zinc-900/80 text-zinc-400 border-b border-zinc-800">
                    <tr>
                      <th className="p-1.5">Leg</th>
                      <th className="p-1.5">Symbol</th>
                      <th className="p-1.5">Action</th>
                      <th className="p-1.5 text-right">Qty</th>
                      <th className="p-1.5 text-right">Price</th>
                      <th className="p-1.5 text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/60">
                    {executionProgress.legs.map((leg: any, idx: number) => (
                      <tr key={leg.leg_id || idx} className="hover:bg-zinc-900/50">
                        <td className="p-1.5 text-zinc-300 font-bold">{leg.leg_id || idx + 1}</td>
                        <td className="p-1.5 text-zinc-200">{leg.symbol}</td>
                        <td className="p-1.5">
                          <Badge
                            variant="outline"
                            className={`text-[9px] px-1 py-0 ${
                              leg.action === 'BUY'
                                ? 'border-emerald-500/40 text-emerald-400 bg-emerald-950/20'
                                : 'border-rose-500/40 text-rose-400 bg-rose-950/20'
                            }`}
                          >
                            {leg.action}
                          </Badge>
                        </td>
                        <td className="p-1.5 text-right text-zinc-300">{leg.quantity}</td>
                        <td className="p-1.5 text-right text-zinc-300">
                          {leg.execution_price > 0 ? `₹${leg.execution_price.toFixed(2)}` : leg.requested_price > 0 ? `₹${leg.requested_price.toFixed(2)}` : '—'}
                        </td>
                        <td className="p-1.5 text-center">
                          <Badge
                            variant="outline"
                            className={`text-[9px] px-1.5 py-0 ${
                              leg.status === 'COMPLETE' || leg.status === 'FILLED'
                                ? 'border-emerald-500 text-emerald-400 bg-emerald-950/30'
                                : leg.status === 'FAILED' || leg.status === 'REJECTED'
                                ? 'border-rose-500 text-rose-400 bg-rose-950/30'
                                : 'border-amber-500 text-amber-400 bg-amber-950/30 animate-pulse'
                            }`}
                          >
                            {leg.status}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ------------------------------------------------------------------- */}
        {/* 1. Pending Signals Queue Waiting for Trader Authorization */}
        {/* ------------------------------------------------------------------- */}
        {pendingSignals.length > 0 && (
          <div className="p-3.5 bg-amber-950/30 border border-amber-500/40 rounded-xl shadow-lg">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Zap className="w-4 h-4 text-amber-400 animate-bounce" />
                <span className="font-mono text-xs font-bold text-amber-300 uppercase tracking-wider">
                  Pending Signal Approval Queue ({pendingSignals.length})
                </span>
              </div>
              <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-500/40 font-mono">
                Manual Execution Gate
              </Badge>
            </div>

            <div className="flex flex-col gap-2">
              {pendingSignals.map((sig) => (
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
                        {sig.legs_count || sig.legs?.length || 0} Legs
                      </span>
                      {sig.remaining_seconds !== undefined && (
                        <span className={`text-[10px] font-mono ${sig.remaining_seconds < 60 ? 'text-rose-400 font-bold animate-pulse' : 'text-zinc-500'}`}>
                          TTL: {sig.remaining_seconds}s
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-zinc-400 mt-0.5 font-mono">
                      {sig.reason || 'Quantitative rule condition triggered'}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
                    <Button
                      size="sm"
                      className="h-7 text-xs bg-emerald-600 hover:bg-emerald-500 text-white font-mono"
                      onClick={() => setSignalToApprove(sig)}
                      disabled={!isConnected || approvingId === sig.signal_id}
                      title={!isConnected ? 'Connect and activate an account before approving' : 'Review and approve signal'}
                    >
                      <Check className="w-3.5 h-3.5 mr-1" />
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs border-zinc-700 hover:bg-zinc-800 text-zinc-400 font-mono"
                      onClick={() => {
                        setSignalToReject(sig)
                        setRejectionReason('')
                      }}
                      disabled={rejectingId === sig.signal_id}
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
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
            <Skeleton className="h-44 w-full bg-zinc-900/60 rounded-xl" />
            <Skeleton className="h-44 w-full bg-zinc-900/60 rounded-xl" />
          </div>
        ) : activeStrategies.length === 0 ? (
          <div className="p-8 text-center text-xs font-mono text-zinc-400 border border-dashed border-zinc-800 rounded-xl flex flex-col items-center justify-center gap-1.5">
            <Cpu className="w-6 h-6 text-zinc-600 mb-1" />
            <p className="text-zinc-300 font-semibold text-sm">No Active Strategies</p>
            <p className="text-[11px] text-zinc-500 max-w-sm">
              {activeAccount
                ? `No live positions or strategy containers active for account '${activeAccount.account_label}'. Ingested signals and filled orders will populate here.`
                : 'Connect and activate a broker account to manage active strategies.'}
            </p>
          </div>
        ) : (
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
                          {getSignalStatusBadge(strat.status)}
                        </div>
                        <div className="flex items-center gap-2 text-[11px] font-mono text-zinc-400 mt-1">
                          <span>{strat.underlying}</span>
                          <span>•</span>
                          <span>
                            Spot/LTP: {strat.currentSpot ? `₹${strat.currentSpot.toFixed(2)}` : 'LTP unavailable'}
                          </span>
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

                    {/* Aggregate Greeks Bar (With Honest Unavailable State) */}
                    <div className="grid grid-cols-4 gap-1.5 mt-2.5 pt-2 border-t border-zinc-800/80 text-[11px] font-mono">
                      {/* Delta */}
                      <div className="flex flex-col bg-zinc-950/60 p-1.5 rounded border border-zinc-800/60">
                        <span className="text-[9px] text-zinc-400 uppercase">Delta (Δ)</span>
                        <span className="font-semibold text-zinc-200">
                          {strat.greeks ? `${strat.greeks.delta > 0 ? '+' : ''}${strat.greeks.delta.toFixed(2)}` : '—'}
                        </span>
                      </div>

                      {/* Theta */}
                      <div className="flex flex-col bg-zinc-950/60 p-1.5 rounded border border-zinc-800/60">
                        <span className="text-[9px] text-zinc-400 uppercase">Theta (θ/d)</span>
                        <span className="font-semibold text-emerald-400">
                          {strat.greeks ? `+₹${strat.greeks.theta.toFixed(0)}` : '—'}
                        </span>
                      </div>

                      {/* Vega */}
                      <div className="flex flex-col bg-zinc-950/60 p-1.5 rounded border border-zinc-800/60">
                        <span className="text-[9px] text-zinc-400 uppercase">Vega (ν/1%)</span>
                        <span className="font-semibold text-rose-400">
                          {strat.greeks ? `${strat.greeks.vega.toFixed(0)}` : '—'}
                        </span>
                      </div>

                      {/* IV / Status */}
                      <div className="flex flex-col bg-zinc-950/60 p-1.5 rounded border border-zinc-800/60">
                        <span className="text-[9px] text-zinc-400 uppercase">Greeks Calc</span>
                        <span className="text-[10px] text-zinc-400">
                          {strat.greeks ? `${(strat.greeks.iv * 100).toFixed(1)}% IV` : (
                            <Tooltip>
                              <TooltipTrigger className="cursor-help flex items-center gap-0.5 text-zinc-500">
                                <span>Uncomputed</span>
                                <HelpCircle className="w-2.5 h-2.5" />
                              </TooltipTrigger>
                              <TooltipContent className="text-xs font-mono">
                                Greeks are calculated when option chain mark prices are active.
                              </TooltipContent>
                            </Tooltip>
                          )}
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
                              <span>Entry: ₹{leg.entryPrice.toFixed(2)}</span>
                              <span className="text-zinc-200 font-semibold">
                                LTP: {leg.ltp ? `₹${leg.ltp.toFixed(2)}` : '—'}
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
        )}

        {/* ------------------------------------------------------------------- */}
        {/* 3. Signal Approval Confirmation Modal */}
        {/* ------------------------------------------------------------------- */}
        {signalToApprove && (
          <Dialog open={true} onOpenChange={() => setSignalToApprove(null)}>
            <DialogContent className="bg-zinc-950 border-emerald-500/50 text-zinc-100 max-w-md font-mono shadow-2xl shadow-emerald-950/40">
              <DialogHeader>
                <div className="flex items-center gap-2.5">
                  <div className="p-2 rounded-lg bg-emerald-950/80 border border-emerald-500/50">
                    <Check className="w-5 h-5 text-emerald-400" />
                  </div>
                  <div>
                    <DialogTitle className="text-sm font-bold text-emerald-300 uppercase tracking-wider">
                      Authorize Signal Execution
                    </DialogTitle>
                    <DialogDescription className="text-xs text-zinc-400">
                      Dispatches trade orders through the institutional execution engine.
                    </DialogDescription>
                  </div>
                </div>
              </DialogHeader>

              <div className="flex flex-col gap-3 py-2 text-xs">
                <div className="p-3 rounded-lg bg-zinc-900/90 border border-zinc-800 flex flex-col gap-1.5">
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-400">Strategy:</span>
                    <span className="font-bold text-zinc-100">{signalToApprove.strategy_name}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-400">Underlying:</span>
                    <span className="text-zinc-200">{signalToApprove.underlying}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-400">Multi-Leg Count:</span>
                    <span className="text-zinc-200">{signalToApprove.legs_count || signalToApprove.legs?.length || 0} Orders</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-400">Active Account:</span>
                    <span className="text-emerald-400 font-bold">{activeAccount?.account_label || 'Unset'}</span>
                  </div>
                </div>

                <div className="p-2.5 rounded-lg bg-emerald-950/20 border border-emerald-500/30 text-[11px] text-emerald-300">
                  <Shield className="w-3.5 h-3.5 inline mr-1 text-emerald-400" />
                  Margin-Safe Sequencing: Long protection wings (Tier 0) will execute and confirm before short credit legs (Tier 1).
                </div>
              </div>

              <DialogFooter className="gap-2 sm:gap-0">
                <Button
                  variant="outline"
                  size="sm"
                  className="border-zinc-800 hover:bg-zinc-900 text-zinc-300 text-xs"
                  onClick={() => setSignalToApprove(null)}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  className="bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs"
                  onClick={handleConfirmApproval}
                  disabled={approvingId === signalToApprove.signal_id}
                >
                  {approvingId === signalToApprove.signal_id ? 'Executing...' : 'Confirm & Execute'}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}

        {/* ------------------------------------------------------------------- */}
        {/* 4. Signal Rejection Confirmation Modal (with Optional Reason Field) */}
        {/* ------------------------------------------------------------------- */}
        {signalToReject && (
          <Dialog open={true} onOpenChange={() => setSignalToReject(null)}>
            <DialogContent className="bg-zinc-950 border-rose-500/50 text-zinc-100 max-w-md font-mono shadow-2xl shadow-rose-950/40">
              <DialogHeader>
                <div className="flex items-center gap-2.5">
                  <div className="p-2 rounded-lg bg-rose-950/80 border border-rose-500/50">
                    <X className="w-5 h-5 text-rose-400" />
                  </div>
                  <div>
                    <DialogTitle className="text-sm font-bold text-rose-300 uppercase tracking-wider">
                      Reject Trade Signal
                    </DialogTitle>
                    <DialogDescription className="text-xs text-zinc-400">
                      Discards this quantitative signal and archives it to audit history.
                    </DialogDescription>
                  </div>
                </div>
              </DialogHeader>

              <div className="flex flex-col gap-3 py-2 text-xs">
                <div className="p-3 rounded-lg bg-zinc-900/90 border border-zinc-800 flex flex-col gap-1.5">
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-400">Strategy:</span>
                    <span className="font-bold text-zinc-100">{signalToReject.strategy_name}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-400">Underlying:</span>
                    <span className="text-zinc-200">{signalToReject.underlying}</span>
                  </div>
                </div>

                <div className="flex flex-col gap-1.5">
                  <label htmlFor="rejection-reason-input" className="text-zinc-400 text-[11px]">
                    Rejection Reason (Optional):
                  </label>
                  <Input
                    id="rejection-reason-input"
                    placeholder="e.g. Market volatility high, risk ceiling reached..."
                    className="h-8 text-xs font-mono bg-zinc-900 border-zinc-800 text-zinc-100"
                    value={rejectionReason}
                    onChange={(e) => setRejectionReason(e.target.value)}
                  />
                </div>
              </div>

              <DialogFooter className="gap-2 sm:gap-0">
                <Button
                  variant="outline"
                  size="sm"
                  className="border-zinc-800 hover:bg-zinc-900 text-zinc-300 text-xs"
                  onClick={() => setSignalToReject(null)}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  className="bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs"
                  onClick={handleConfirmRejection}
                  disabled={rejectingId === signalToReject.signal_id}
                >
                  {rejectingId === signalToReject.signal_id ? 'Rejecting...' : 'Confirm Rejection'}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}
      </div>
    </TooltipProvider>
  )
}
