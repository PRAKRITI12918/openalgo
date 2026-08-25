/**
 * Emergency One-Click Square-Off Safety Confirmation Modal.
 * Prompts trader with strategy summary before executing emergency liquidation.
 */

import { AlertOctagon, AlertTriangle, ShieldCheck, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { useExecutionStore } from '@/stores/executionStore'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { showToast } from '@/utils/toast'

interface SquareOffModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SquareOffModal({ open, onOpenChange }: SquareOffModalProps) {
  const { activeStrategies, squareOffAll, totalDayMtm } = useExecutionStore()
  const [isProcessing, setIsProcessing] = useState(false)

  const activeCount = activeStrategies.filter((s) => s.status !== 'Exited').length

  const handleConfirm = () => {
    setIsProcessing(true)
    setTimeout(() => {
      squareOffAll()
      setIsProcessing(false)
      showToast.success('Emergency Square-Off Complete: All active strategy positions closed')
      onOpenChange(false)
    }, 500)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-zinc-950 border-rose-600/50 text-zinc-100 max-w-md font-mono shadow-2xl shadow-rose-950/50">
        <DialogHeader>
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-rose-950/80 border border-rose-500/50">
              <AlertOctagon className="w-5 h-5 text-rose-500 animate-pulse" />
            </div>
            <div>
              <DialogTitle className="text-base font-bold text-rose-300">
                Confirm Emergency Square-Off
              </DialogTitle>
              <DialogDescription className="text-xs text-zinc-400">
                Immediate market liquidation of all open derivatives positions.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="flex flex-col gap-3 py-2 text-xs">
          <div className="p-3 rounded-lg bg-rose-950/30 border border-rose-500/30 text-rose-200 leading-relaxed">
            <p className="font-bold flex items-center gap-1 mb-1 text-rose-400">
              <AlertTriangle className="w-3.5 h-3.5" /> High Risk Operation
            </p>
            You are about to market-exit <strong>{activeCount} active strategy portfolios</strong>.
            Short positions will be bought back first to eliminate naked risk, followed by closing protection wings.
          </div>

          <div className="p-2.5 rounded-lg bg-zinc-900/80 border border-zinc-800 flex justify-between items-center text-xs">
            <span className="text-zinc-400">Current Real-Time Day MTM:</span>
            <span
              className={`font-bold ${
                totalDayMtm >= 0 ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {totalDayMtm >= 0 ? '+' : ''}₹{totalDayMtm.toFixed(2)}
            </span>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            size="sm"
            className="border-zinc-800 hover:bg-zinc-900 text-zinc-300 text-xs"
            onClick={() => onOpenChange(false)}
            disabled={isProcessing}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            variant="destructive"
            className="bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs"
            onClick={handleConfirm}
            disabled={isProcessing || activeCount === 0}
          >
            {isProcessing ? 'Liquidating Positions...' : 'Confirm Liquidate All'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
