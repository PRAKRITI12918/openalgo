/**
 * Emergency Square-Off Safety Confirmation Modal.
 * High-friction two-step risk control:
 * 1. Prepare: Fetches live open positions and generates single-use confirmation token.
 * 2. Hard Confirmation: Requires trader to review positions and type 'CONFIRM'.
 * 3. Independent Execution: Displays live per-order results and final status summary.
 */

import { AlertOctagon, AlertTriangle, CheckCircle2, Loader2, RefreshCw, ShieldAlert, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useExecutionStore } from '@/stores/executionStore'
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
import { showToast } from '@/utils/toast'

interface SquareOffModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

type Stage = 'PREPARING' | 'CONFIRMING' | 'EXECUTING' | 'RESULT' | 'ERROR'

export function SquareOffModal({ open, onOpenChange }: SquareOffModalProps) {
  const { activeAccount, brokerStatus, isMockMode, prepareSquareOff, executeSquareOff, totalDayMtm } =
    useExecutionStore()

  const [stage, setStage] = useState<Stage>('PREPARING')
  const [token, setToken] = useState<string>('')
  const [openPositions, setOpenPositions] = useState<any[]>([])
  const [confirmInput, setConfirmInput] = useState<string>('')
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [executionResult, setExecutionResult] = useState<any>(null)

  const isConnected = brokerStatus === 'CONNECTED'
  const accountName = activeAccount ? activeAccount.account_label : 'Active Account'

  // On modal open, prepare square-off to get fresh live snapshot and confirmation token
  useEffect(() => {
    if (open) {
      handlePrepare()
    } else {
      // Reset state on close
      setStage('PREPARING')
      setToken('')
      setOpenPositions([])
      setConfirmInput('')
      setErrorMessage('')
      setExecutionResult(null)
    }
  }, [open])

  const handlePrepare = async () => {
    if (!isConnected) {
      setStage('ERROR')
      setErrorMessage('No active CONNECTED broker account. Please connect an account first.')
      return
    }

    setStage('PREPARING')
    setErrorMessage('')
    try {
      const prep = await prepareSquareOff()
      setToken(prep.confirmation_token)
      setOpenPositions(prep.open_positions || [])
      setStage('CONFIRMING')
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail?.message ||
        err?.response?.data?.detail ||
        err.message ||
        'Failed to prepare emergency square-off snapshot'
      setErrorMessage(msg)
      setStage('ERROR')
    }
  }

  const handleExecute = async () => {
    if (confirmInput.trim().toUpperCase() !== 'CONFIRM') return

    setStage('EXECUTING')
    try {
      const res = await executeSquareOff(token, 'CONFIRM')
      setExecutionResult(res)
      setStage('RESULT')
      if (res.status === 'success') {
        showToast.success(res.message || 'All positions successfully closed')
      } else if (res.status === 'partial_success') {
        showToast.error(`Square-off partially completed: ${res.failed_count} orders failed`)
      } else {
        showToast.error(`Square-off failed: ${res.message}`)
      }
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail?.message ||
        err?.response?.data?.detail ||
        err.message ||
        'Execution rejected by server'
      setErrorMessage(msg)
      setStage('ERROR')
      showToast.error(`Square-off error: ${msg}`)
    }
  }

  const isConfirmDisabled = confirmInput.trim().toUpperCase() !== 'CONFIRM'

  return (
    <Dialog open={open} onOpenChange={stage === 'EXECUTING' ? () => {} : onOpenChange}>
      <DialogContent className="bg-zinc-950 border-rose-600/50 text-zinc-100 max-w-lg font-mono shadow-2xl shadow-rose-950/50">
        <DialogHeader>
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-rose-950/80 border border-rose-500/50">
              <AlertOctagon className="w-5 h-5 text-rose-500 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <DialogTitle className="text-base font-bold text-rose-300">
                  Emergency Square-Off All
                </DialogTitle>
                {isMockMode && (
                  <Badge variant="outline" className="text-[9px] border-amber-500/40 text-amber-400 bg-amber-500/10">
                    MOCK
                  </Badge>
                )}
              </div>
              <DialogDescription className="text-xs text-zinc-400">
                Break-glass control: immediately liquidates all open positions for [{accountName}].
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="flex flex-col gap-3 py-2 text-xs">
          {/* Stage: PREPARING */}
          {stage === 'PREPARING' && (
            <div className="p-6 flex flex-col items-center justify-center gap-3 text-zinc-400">
              <Loader2 className="w-6 h-6 animate-spin text-rose-500" />
              <p className="text-xs">Fetching live positions & generating confirmation token...</p>
            </div>
          )}

          {/* Stage: ERROR */}
          {stage === 'ERROR' && (
            <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-500/50 text-rose-300 flex items-start gap-2.5">
              <ShieldAlert className="w-4 h-4 shrink-0 text-rose-400 mt-0.5" />
              <div className="flex-1">
                <p className="font-bold text-rose-300">Square-Off Blocked</p>
                <p className="text-[11px] text-zinc-300 mt-1 leading-relaxed">{errorMessage}</p>
              </div>
            </div>
          )}

          {/* Stage: CONFIRMING */}
          {stage === 'CONFIRMING' && (
            <>
              <div className="p-3 rounded-lg bg-rose-950/30 border border-rose-500/30 text-rose-200 leading-relaxed font-sans text-xs">
                <p className="font-bold font-mono flex items-center gap-1 mb-1.5 text-rose-400 text-xs">
                  <AlertTriangle className="w-3.5 h-3.5" /> High Risk Irreversible Market Order
                </p>
                <p className="font-semibold text-zinc-100">
                  Target Account: <span className="font-mono text-rose-300">[{accountName}]</span>.
                  Total positions to close: <span className="font-mono text-amber-400 font-bold">{openPositions.length}</span>.
                </p>
              </div>

              {/* Positions Snapshot Table */}
              {openPositions.length === 0 ? (
                <div className="p-4 rounded-lg bg-zinc-900/50 border border-zinc-800 text-center text-zinc-400 text-xs">
                  No open positions found on active account. Executing will produce a clean audit no-op.
                </div>
              ) : (
                <div className="max-h-40 overflow-y-auto border border-zinc-800 rounded-lg bg-zinc-900/40 p-2 space-y-1.5">
                  <div className="grid grid-cols-4 text-[10px] text-zinc-400 font-bold border-b border-zinc-800 pb-1 px-1">
                    <span>SYMBOL</span>
                    <span>CURRENT</span>
                    <span>EXIT ORDER</span>
                    <span className="text-right">QTY</span>
                  </div>
                  {openPositions.map((pos, idx) => (
                    <div key={idx} className="grid grid-cols-4 text-[11px] items-center px-1 text-zinc-300">
                      <span className="font-mono text-zinc-200 truncate" title={pos.symbol}>
                        {pos.symbol}
                      </span>
                      <span>
                        <Badge variant="outline" className={`text-[9px] px-1 py-0 ${pos.current_action === 'BUY' ? 'border-emerald-500/40 text-emerald-400' : 'border-rose-500/40 text-rose-400'}`}>
                          {pos.current_action}
                        </Badge>
                      </span>
                      <span className="text-rose-400 font-bold text-[10px]">
                        {pos.exit_action} MKT
                      </span>
                      <span className="text-right font-mono font-bold text-amber-300">
                        {pos.exit_quantity}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Hard Confirmation Input */}
              <div className="p-3 rounded-lg bg-zinc-900 border border-zinc-800 flex flex-col gap-2">
                <label className="text-[11px] text-zinc-300">
                  Type <strong className="text-rose-400 tracking-wider">CONFIRM</strong> below to authorize emergency exit:
                </label>
                <input
                  type="text"
                  placeholder="Type CONFIRM"
                  value={confirmInput}
                  onChange={(e) => setConfirmInput(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-700 rounded px-2.5 py-1.5 text-xs text-zinc-100 uppercase tracking-widest focus:outline-none focus:border-rose-500"
                  autoFocus
                />
              </div>

              <div className="p-2 rounded bg-zinc-900/60 border border-zinc-800/80 flex justify-between items-center text-[11px]">
                <span className="text-zinc-400">Current Day MTM:</span>
                <span className={`font-bold ${totalDayMtm >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {totalDayMtm >= 0 ? '+' : ''}₹{totalDayMtm.toFixed(2)}
                </span>
              </div>
            </>
          )}

          {/* Stage: EXECUTING */}
          {stage === 'EXECUTING' && (
            <div className="p-8 flex flex-col items-center justify-center gap-3 text-center">
              <Loader2 className="w-8 h-8 animate-spin text-rose-500" />
              <div>
                <p className="font-bold text-zinc-100 text-sm">Liquidating Positions...</p>
                <p className="text-zinc-400 text-xs mt-1">Executing reverse market exit orders per symbol independently.</p>
              </div>
            </div>
          )}

          {/* Stage: RESULT */}
          {stage === 'RESULT' && executionResult && (
            <div className="flex flex-col gap-2.5">
              <div className="p-3 rounded-lg bg-zinc-900/80 border border-zinc-800 flex items-center justify-between">
                <div>
                  <p className="font-bold text-zinc-100 text-xs">Square-Off Summary</p>
                  <p className="text-[10px] text-zinc-400">Batch ID: {executionResult.square_off_id}</p>
                </div>
                <div className="flex gap-1.5">
                  <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/40 text-[10px]">
                    {executionResult.filled_count} Filled
                  </Badge>
                  {executionResult.partial_count > 0 && (
                    <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/40 text-[10px]">
                      {executionResult.partial_count} Partial
                    </Badge>
                  )}
                  {executionResult.failed_count > 0 && (
                    <Badge className="bg-rose-500/20 text-rose-400 border-rose-500/40 text-[10px]">
                      {executionResult.failed_count} Failed
                    </Badge>
                  )}
                </div>
              </div>

              {/* Per-order breakdown table */}
              <div className="max-h-48 overflow-y-auto border border-zinc-800 rounded-lg bg-zinc-900/40 p-2 space-y-1.5 text-xs">
                {executionResult.results?.map((res: any, idx: number) => (
                  <div key={idx} className="flex justify-between items-center py-1 border-b border-zinc-800/60 last:border-none">
                    <div className="flex flex-col">
                      <span className="font-bold text-zinc-200">{res.symbol}</span>
                      <span className="text-[10px] text-zinc-400">
                        {res.action} {res.filled_quantity}/{res.requested_quantity}
                        {res.avg_price > 0 && ` @ ₹${res.avg_price}`}
                      </span>
                    </div>
                    <div>
                      {res.status === 'FILLED' && (
                        <span className="flex items-center text-emerald-400 text-[10px] font-bold gap-1">
                          <CheckCircle2 className="w-3.5 h-3.5" /> FILLED
                        </span>
                      )}
                      {res.status === 'PARTIAL' && (
                        <span className="flex items-center text-amber-400 text-[10px] font-bold gap-1">
                          <AlertTriangle className="w-3.5 h-3.5" /> PARTIAL
                        </span>
                      )}
                      {res.status === 'FAILED' && (
                        <span className="flex items-center text-rose-400 text-[10px] font-bold gap-1" title={res.error}>
                          <XCircle className="w-3.5 h-3.5" /> FAILED
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          {stage === 'ERROR' && (
            <Button
              variant="outline"
              size="sm"
              className="border-zinc-800 text-zinc-300 text-xs"
              onClick={handlePrepare}
            >
              <RefreshCw className="w-3 h-3 mr-1" /> Retry Snapshot
            </Button>
          )}

          {stage === 'CONFIRMING' && (
            <>
              <Button
                variant="outline"
                size="sm"
                className="border-zinc-800 hover:bg-zinc-900 text-zinc-300 text-xs"
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                variant="destructive"
                className="bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs shadow-lg shadow-rose-600/30"
                onClick={handleExecute}
                disabled={isConfirmDisabled}
              >
                Execute Square-Off All
              </Button>
            </>
          )}

          {stage === 'RESULT' && (
            <Button
              size="sm"
              className="bg-zinc-800 hover:bg-zinc-700 text-zinc-100 text-xs font-bold"
              onClick={() => onOpenChange(false)}
            >
              Close
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
