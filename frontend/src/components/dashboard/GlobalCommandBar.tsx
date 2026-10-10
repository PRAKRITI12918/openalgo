/**
 * Top Navigation & Global Command Bar for Institutional Trader HUD.
 * Multi-Account Broker Connectivity Bar, Mock Execution Banner,
 * Emergency Square-Off button, Circuit Breaker status badge & reset,
 * and dynamic account MTM ticker.
 */

import {
  AlertOctagon,
  AlertTriangle,
  ArrowRightLeft,
  CheckCircle2,
  Cpu,
  Flame,
  KeyRound,
  Radio,
  RefreshCw,
  RotateCcw,
  Settings,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Wallet,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { executionApi } from '@/services/executionApi'
import { useExecutionStore } from '@/stores/executionStore'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { showToast } from '@/utils/toast'

interface GlobalCommandBarProps {
  onOpenSquareOff: () => void
  onOpenSimulateSignal: () => void
  onOpenBrokerSettings: () => void
  onOpenAccountSwitcher: () => void
}

export function GlobalCommandBar({
  onOpenSquareOff,
  onOpenSimulateSignal,
  onOpenBrokerSettings,
  onOpenAccountSwitcher,
}: GlobalCommandBarProps) {
  const {
    activeAccount,
    brokerStatus,
    isMockMode,
    wsMarketConnected,
    wsExecutionsConnected,
    circuitBreakerActive,
    circuitBreakerDetails,
    availableFunds,
    utilizedMargin,
    totalFunds,
    totalDayMtm,
    isSquareOffInFlight,
    resetCircuitBreakerState,
    refreshAllData,
  } = useExecutionStore()

  const [isResettingCb, setIsResettingCb] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const isConnected = brokerStatus === 'CONNECTED'
  const isExpired = brokerStatus === 'TOKEN_EXPIRED'
  const isFailed = brokerStatus === 'AUTHENTICATION_FAILED'
  const isPnlPositive = totalDayMtm >= 0

  const handleResetCircuitBreaker = async () => {
    setIsResettingCb(true)
    try {
      await executionApi.resetCircuitBreaker()
      resetCircuitBreakerState()
      showToast.success('Circuit breaker and broker error state reset successfully')
    } catch {
      resetCircuitBreakerState()
      showToast.success('Circuit breaker reset locally')
    } finally {
      setIsResettingCb(false)
    }
  }

  const handleRefresh = async () => {
    setIsRefreshing(true)
    try {
      await refreshAllData()
      showToast.info('Dashboard refreshed with active account data')
    } finally {
      setIsRefreshing(false)
    }
  }

  return (
    <header className="w-full bg-zinc-950/95 border-b border-zinc-800/80 backdrop-blur-md sticky top-0 z-40">
      {/* 1. Non-Dismissible Mock Execution Mode Banner */}
      {isMockMode && (
        <div className="w-full bg-amber-500/10 border-b border-amber-500/30 px-4 py-1 text-center font-mono text-[11px] text-amber-300 flex items-center justify-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <span>
            <strong>MOCK EXECUTION MODE</strong> — Simulated order routing active. Real capital is not deployed.
          </span>
        </div>
      )}

      {/* 2. Main Navigation Bar */}
      <div className="px-4 py-2.5 flex flex-col lg:flex-row items-center justify-between gap-3">
        {/* Left: Brand, Active Broker Account Pill & Circuit Breaker */}
        <div className="flex flex-wrap items-center gap-3 w-full lg:w-auto justify-between lg:justify-start">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-cyan-600 flex items-center justify-center shadow-lg shadow-emerald-500/20">
              <Cpu className="w-4 h-4 text-zinc-950 font-bold" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold tracking-wider text-sm text-zinc-100 uppercase">
                  OpenAlgo Terminal
                </span>
                <Badge
                  variant="outline"
                  className="text-[10px] px-1.5 py-0 border-emerald-500/40 bg-emerald-500/10 text-emerald-400 font-mono"
                >
                  PHASE 3 HUD
                </Badge>
              </div>
              <p className="text-[11px] text-zinc-400 font-mono hidden sm:block">
                Multi-Account Quantitative Execution Terminal
              </p>
            </div>
          </div>

          <div className="h-5 w-px bg-zinc-800 hidden sm:block" />

          {/* Active Broker & Account Switcher Pill */}
          <div className="flex items-center gap-2 px-2.5 py-1 rounded-md bg-zinc-900 border border-zinc-800 text-xs">
            <div
              className={`w-2 h-2 rounded-full ${
                isConnected
                  ? 'bg-emerald-400 animate-pulse'
                  : isExpired
                  ? 'bg-amber-400 animate-ping'
                  : isFailed
                  ? 'bg-rose-500'
                  : 'bg-zinc-600'
              }`}
            />
            <div className="flex flex-col text-left">
              <div className="flex items-center gap-1.5">
                <span className="font-mono font-bold text-zinc-200 text-[11px]">
                  {activeAccount ? activeAccount.account_label : 'No Active Account'}
                </span>
                {activeAccount && (
                  <span className="text-[10px] text-zinc-400 font-mono">
                    ({activeAccount.broker_display_name})
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1 text-[9px] font-mono">
                <span className={isConnected ? 'text-emerald-400' : isExpired ? 'text-amber-400' : 'text-zinc-500'}>
                  {brokerStatus}
                </span>
                {activeAccount?.masked_external_id && (
                  <>
                    <span>•</span>
                    <span className="text-zinc-500">{activeAccount.masked_external_id}</span>
                  </>
                )}
              </div>
            </div>

            {/* Switch Account Button */}
            <Button
              size="sm"
              variant="ghost"
              className="h-6 px-1.5 ml-1 text-[10px] font-mono text-zinc-300 hover:text-emerald-400 hover:bg-zinc-800 border border-zinc-700/50"
              onClick={onOpenAccountSwitcher}
              title="Switch Active Broker Account"
            >
              <ArrowRightLeft className="w-3 h-3 mr-1 text-emerald-400" />
              Switch
            </Button>

            {/* Reconnect Action if Expired */}
            {(isExpired || isFailed) && (
              <Button
                size="sm"
                className="h-6 px-2 text-[10px] font-mono bg-amber-600 hover:bg-amber-500 text-black font-bold"
                onClick={onOpenBrokerSettings}
              >
                Reconnect
              </Button>
            )}
          </div>

          {/* Circuit Breaker Status */}
          {circuitBreakerActive ? (
            <div className="flex items-center gap-2 px-2.5 py-1 rounded-md bg-red-950/60 border border-red-500/50 text-xs animate-pulse">
              <ShieldAlert className="w-3.5 h-3.5 text-red-400" />
              <div className="flex flex-col">
                <span className="font-mono font-bold text-red-300 text-[11px]">
                  CIRCUIT BREAKER TRIPPED
                </span>
                {circuitBreakerDetails?.reason && (
                  <span className="text-[9px] text-red-400/90 truncate max-w-[160px]">
                    {circuitBreakerDetails.reason}
                  </span>
                )}
              </div>
              <Button
                variant="destructive"
                size="sm"
                className="h-6 px-2 text-[10px] font-mono ml-1 bg-red-600 hover:bg-red-500 text-white"
                onClick={handleResetCircuitBreaker}
                disabled={isResettingCb}
              >
                <RotateCcw className={`w-3 h-3 mr-1 ${isResettingCb ? 'animate-spin' : ''}`} />
                Reset
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-zinc-900/80 border border-zinc-800/80 text-[11px] font-mono text-zinc-400">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>CIRCUIT BREAKER: ARMED</span>
            </div>
          )}
        </div>

        {/* Middle Section: Capital & Real-Time Day MTM */}
        <div className="flex items-center gap-4 bg-zinc-900/90 border border-zinc-800 px-3.5 py-1.5 rounded-lg shadow-inner w-full lg:w-auto justify-between lg:justify-start">
          <div className="flex flex-col">
            <span className="text-[10px] uppercase font-mono tracking-wider text-zinc-400">
              Avail Margin
            </span>
            <span className="font-mono font-semibold text-xs text-zinc-200">
              ₹{availableFunds.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </span>
          </div>

          <div className="h-6 w-px bg-zinc-800" />

          <div className="flex flex-col">
            <span className="text-[10px] uppercase font-mono tracking-wider text-zinc-400">
              Used Margin
            </span>
            <span className="font-mono font-semibold text-xs text-zinc-200">
              ₹{utilizedMargin.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </span>
          </div>

          <div className="h-6 w-px bg-zinc-800" />

          <div className="flex flex-col items-end">
            <span className="text-[10px] uppercase font-mono tracking-wider text-zinc-400 flex items-center gap-1">
              <Flame className="w-3 h-3 text-amber-400" /> Day Total MTM
            </span>
            <div className="flex items-center gap-1.5">
              {isPnlPositive ? (
                <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
              ) : (
                <TrendingDown className="w-3.5 h-3.5 text-rose-400" />
              )}
              <span
                className={`font-mono font-bold text-sm tracking-wide ${
                  isPnlPositive ? 'text-emerald-400' : 'text-rose-400'
                }`}
              >
                {isPnlPositive ? '+' : ''}₹
                {totalDayMtm.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>
          </div>
        </div>

        {/* Right Section: Action Controls */}
        <div className="flex items-center gap-2 w-full lg:w-auto justify-end">
          <Button
            variant="ghost"
            size="sm"
            className="h-8 border border-zinc-800 bg-zinc-900/60 hover:bg-zinc-800 text-zinc-300 font-mono text-xs px-2"
            onClick={handleRefresh}
            disabled={isRefreshing}
            title="Refresh All Account Data"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-emerald-400' : 'text-zinc-400'}`} />
          </Button>

          <Button
            variant="outline"
            size="sm"
            className="h-8 border-cyan-500/40 bg-cyan-950/30 hover:bg-cyan-900/50 text-cyan-300 font-mono text-xs"
            onClick={onOpenSimulateSignal}
          >
            <Sparkles className="w-3.5 h-3.5 mr-1.5 text-cyan-400" />
            Simulate Signal
          </Button>

          <Button
            variant="ghost"
            size="sm"
            className="h-8 border border-zinc-800 bg-zinc-900/60 hover:bg-zinc-800 text-zinc-300 font-mono text-xs px-2.5"
            onClick={onOpenBrokerSettings}
            title="Broker Connections & Credentials"
          >
            <Settings className="w-3.5 h-3.5 mr-1 text-zinc-400" />
            <span className="hidden sm:inline">Brokers</span>
          </Button>

          {/* Emergency Panic Square-Off Button */}
          <Button
            variant="destructive"
            size="sm"
            className="h-8 bg-rose-600 hover:bg-rose-500 text-white font-mono text-xs font-bold px-3 shadow-lg shadow-rose-600/30 transition-all active:scale-95 disabled:opacity-60 disabled:cursor-not-allowed"
            onClick={onOpenSquareOff}
            disabled={isSquareOffInFlight}
          >
            <AlertOctagon className="w-3.5 h-3.5 mr-1.5" />
            {isSquareOffInFlight ? 'Liquidating...' : 'Square-Off All'}
          </Button>
        </div>
      </div>
    </header>
  )
}
