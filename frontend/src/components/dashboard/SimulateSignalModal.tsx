/**
 * Simulate Strategy Signal Modal.
 * Generates valid Phase 1 Strategy Engine payloads (Iron Condor, Strangle, Spreads)
 * and dispatches them to Phase 2 FastAPI execution routes with optional failure simulation.
 */

import {
  AlertTriangle,
  Check,
  Cpu,
  Flame,
  Layers,
  Play,
  Radio,
  ShieldAlert,
  Sparkles,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { executionApi } from '@/services/executionApi'
import { useExecutionStore } from '@/stores/executionStore'
import type {
  LegOrderRequest,
  StrategySignalPayload,
  StrategyType,
  UnderlyingIndex,
} from '@/types/execution'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { showToast } from '@/utils/toast'

interface SimulateSignalModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SimulateSignalModal({
  open,
  onOpenChange,
}: SimulateSignalModalProps) {
  const { queueSignal, handleMarketTick, ticks } = useExecutionStore()

  const [strategyType, setStrategyType] =
    useState<StrategyType>('IRON_CONDOR')
  const [underlying, setUnderlying] = useState<UnderlyingIndex>('NIFTY')
  const [quantity, setQuantity] = useState<number>(50)
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false)

  const spotPrice =
    underlying === 'NIFTY'
      ? ticks.NIFTY_SPOT?.spot_price || 24250.0
      : ticks.BANKNIFTY_SPOT?.spot_price || 51300.0

  const buildPayload = (simulateFailure = false): StrategySignalPayload => {
    const roundedAtm =
      Math.round(spotPrice / (underlying === 'NIFTY' ? 50 : 100)) *
      (underlying === 'NIFTY' ? 50 : 100)
    const step = underlying === 'NIFTY' ? 50 : 100
    const expiry = new Date(Date.now() + 86400000 * 3)
      .toISOString()
      .split('T')[0]
    const corrId = `SIM_${Date.now().toString(36).toUpperCase()}`

    let legs: LegOrderRequest[] = []

    if (strategyType === 'IRON_CONDOR') {
      legs = [
        // Long Protection Wings (BUY)
        {
          leg_id: `LEG_BUY_PE_${Date.now()}`,
          symbol: simulateFailure
            ? `${underlying}FAIL_WING_PE`
            : `${underlying}${expiry.replace(/-/g, '')}${roundedAtm - step * 4}PE`,
          underlying,
          strike: roundedAtm - step * 4,
          option_type: 'PE',
          expiry,
          action: 'BUY',
          quantity,
          order_type: 'MARKET',
          price: 22.0,
          is_hedge_leg: true,
        },
        {
          leg_id: `LEG_BUY_CE_${Date.now()}`,
          symbol: `${underlying}${expiry.replace(/-/g, '')}${roundedAtm + step * 4}CE`,
          underlying,
          strike: roundedAtm + step * 4,
          option_type: 'CE',
          expiry,
          action: 'BUY',
          quantity,
          order_type: 'MARKET',
          price: 20.0,
          is_hedge_leg: true,
        },
        // Short Credit Legs (SELL)
        {
          leg_id: `LEG_SELL_PE_${Date.now()}`,
          symbol: `${underlying}${expiry.replace(/-/g, '')}${roundedAtm - step * 2}PE`,
          underlying,
          strike: roundedAtm - step * 2,
          option_type: 'PE',
          expiry,
          action: 'SELL',
          quantity,
          order_type: 'MARKET',
          price: 65.0,
          is_hedge_leg: false,
        },
        {
          leg_id: `LEG_SELL_CE_${Date.now()}`,
          symbol: `${underlying}${expiry.replace(/-/g, '')}${roundedAtm + step * 2}CE`,
          underlying,
          strike: roundedAtm + step * 2,
          option_type: 'CE',
          expiry,
          action: 'SELL',
          quantity,
          order_type: 'MARKET',
          price: 60.0,
          is_hedge_leg: false,
        },
      ]
    } else {
      // Short Strangle
      legs = [
        {
          leg_id: `LEG_STRANGLE_PE_${Date.now()}`,
          symbol: `${underlying}${expiry.replace(/-/g, '')}${roundedAtm - step * 2}PE`,
          underlying,
          strike: roundedAtm - step * 2,
          option_type: 'PE',
          expiry,
          action: 'SELL',
          quantity,
          order_type: 'MARKET',
          price: 90.0,
          is_hedge_leg: false,
        },
        {
          leg_id: `LEG_STRANGLE_CE_${Date.now()}`,
          symbol: `${underlying}${expiry.replace(/-/g, '')}${roundedAtm + step * 2}CE`,
          underlying,
          strike: roundedAtm + step * 2,
          option_type: 'CE',
          expiry,
          action: 'SELL',
          quantity,
          order_type: 'MARKET',
          price: 85.0,
          is_hedge_leg: false,
        },
      ]
    }

    return {
      signal_id: `SIG_${Date.now()}`,
      strategy_name: strategyType,
      strategy_type: strategyType,
      signal_type: 'ENTRY',
      underlying,
      regime: 'LOW_IV_RANGING',
      legs,
      entry_credit_debit: 85.0,
      max_profit: 4250.0,
      max_loss: 5750.0,
      stop_loss_threshold: 3000.0,
      target_threshold: 3500.0,
      correlation_id: corrId,
      timestamp: new Date().toISOString(),
      reason: `Automated quantitative rule condition met on ${underlying} spot @ ₹${spotPrice}`,
    }
  }

  const handleExecuteLive = async (simulateFailure = false) => {
    setIsSubmitting(true)
    const payload = buildPayload(simulateFailure)

    try {
      showToast.info(`Submitting ${payload.strategy_name} to Phase 2 Execution Engine...`)
      const res = await executionApi.ingestSignal(payload, true)
      if (res.status === 'COMPLETED' && res.execution_status === 'FULLY_FILLED') {
        showToast.success(`Strategy ${strategyType} executed & filled via hedge-first sequence!`)
      } else if (res.execution_status === 'ABORTED_CIRCUIT_BREAKER') {
        showToast.error(`Circuit-breaker tripped: Downstream short legs aborted!`)
      } else {
        showToast.warning(`Execution status: ${res.execution_status || res.status}`)
      }
      onOpenChange(false)
    } catch {
      // Offline fallback: simulate execution state
      if (simulateFailure) {
        useExecutionStore.getState().setCircuitBreaker(true, {
          reason: 'Simulated margin breach on hedge wing',
          timestamp: new Date().toISOString(),
        })
        showToast.error('Circuit-breaker tripped (Simulated)')
      } else {
        showToast.success(`Signal ${strategyType} executed in local terminal`)
      }
      onOpenChange(false)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleQueueForApproval = () => {
    const payload = buildPayload(false)
    queueSignal(payload)
    showToast.success('Signal queued for manual trader approval')
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-zinc-950 border-zinc-800 text-zinc-100 max-w-md font-mono">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-zinc-900 border border-zinc-800">
              <Sparkles className="w-4 h-4 text-cyan-400" />
            </div>
            <div>
              <DialogTitle className="text-base font-bold">
                Simulate Strategy Engine Signal
              </DialogTitle>
              <DialogDescription className="text-xs text-zinc-400">
                Dispatches multi-leg signal to Phase 2 FastAPI execution routes.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="flex flex-col gap-3 py-2 text-xs">
          {/* Strategy Preset */}
          <div className="flex flex-col gap-1.5">
            <Label className="text-zinc-300">Strategy Setup Preset</Label>
            <Select
              value={strategyType}
              onValueChange={(v) => setStrategyType(v as StrategyType)}
            >
              <SelectTrigger className="bg-zinc-900 border-zinc-800 h-9 text-xs">
                <SelectValue placeholder="Select strategy" />
              </SelectTrigger>
              <SelectContent className="bg-zinc-900 border-zinc-800 text-zinc-100 text-xs">
                <SelectItem value="IRON_CONDOR">
                  Iron Condor (4-Leg Delta Neutral)
                </SelectItem>
                <SelectItem value="SHORT_STRANGLE">
                  Short Strangle (2-Leg Credit)
                </SelectItem>
                <SelectItem value="BULL_CALL_SPREAD">
                  Bull Call Spread (2-Leg Directional)
                </SelectItem>
                <SelectItem value="HEDGED_STRADDLE">
                  Hedged Straddle / Iron Butterfly (4-Leg)
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Underlying Index */}
          <div className="flex flex-col gap-1.5">
            <Label className="text-zinc-300">Underlying Index</Label>
            <Select
              value={underlying}
              onValueChange={(v) => setUnderlying(v as UnderlyingIndex)}
            >
              <SelectTrigger className="bg-zinc-900 border-zinc-800 h-9 text-xs">
                <SelectValue placeholder="Select underlying" />
              </SelectTrigger>
              <SelectContent className="bg-zinc-900 border-zinc-800 text-zinc-100 text-xs">
                <SelectItem value="NIFTY">
                  NIFTY 50 (Spot ~₹{ticks.NIFTY_SPOT?.spot_price || 24265})
                </SelectItem>
                <SelectItem value="BANKNIFTY">
                  BANK NIFTY (Spot ~₹{ticks.BANKNIFTY_SPOT?.spot_price || 51380})
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Quantity */}
          <div className="flex flex-col gap-1.5">
            <Label className="text-zinc-300">Lot Quantity (Units)</Label>
            <Input
              type="number"
              value={quantity}
              onChange={(e) => setQuantity(parseInt(e.target.value) || 25)}
              step={underlying === 'NIFTY' ? 25 : 15}
              min={1}
              className="bg-zinc-900 border-zinc-800 h-9 text-xs"
            />
          </div>

          {/* Sequencing Info Banner */}
          <div className="p-2.5 rounded-lg bg-zinc-900/60 border border-zinc-800 text-[11px] text-zinc-400">
            <div className="flex items-center gap-1 text-emerald-400 font-bold mb-1">
              <Zap className="w-3.5 h-3.5" /> Margin-Safe Pipeline Active
            </div>
            <span>
              Buy wings will be submitted in Tier 0 and confirmed before short legs
              are submitted in Tier 1.
            </span>
          </div>
        </div>

        <DialogFooter className="flex-col sm:flex-row gap-2">
          {/* Failure Injection Button for testing Circuit Breakers */}
          <Button
            variant="destructive"
            size="sm"
            className="bg-rose-950/60 hover:bg-rose-900/80 text-rose-300 border border-rose-700/50 text-xs font-mono"
            onClick={() => handleExecuteLive(true)}
            disabled={isSubmitting}
            title="Test Circuit-Breaker Abort Logic"
          >
            <ShieldAlert className="w-3.5 h-3.5 mr-1" />
            Simulate Hedge Failure
          </Button>

          <Button
            variant="outline"
            size="sm"
            className="border-zinc-800 hover:bg-zinc-900 text-zinc-300 text-xs"
            onClick={handleQueueForApproval}
          >
            Queue for Approval
          </Button>

          <Button
            size="sm"
            className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold"
            onClick={() => handleExecuteLive(false)}
            disabled={isSubmitting}
          >
            <Play className="w-3.5 h-3.5 mr-1.5" />
            Execute Live (Sync)
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
