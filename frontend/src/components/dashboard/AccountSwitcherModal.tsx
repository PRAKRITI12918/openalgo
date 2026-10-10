/**
 * Account Switcher Modal for Multi-Account Broker Management.
 * Renders all connected broker accounts, current active account highlight,
 * and high-friction confirmation modal when switching accounts with open positions.
 */

import {
  AlertCircle,
  AlertTriangle,
  ArrowRightLeft,
  CheckCircle2,
  ExternalLink,
  Layers,
  LogOut,
  Plus,
  RefreshCw,
  Shield,
  ShieldAlert,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { useExecutionStore } from '@/stores/executionStore'
import type { BrokerAccountDisplay } from '@/types/execution'
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
import { executionApi } from '@/services/executionApi'
import { showToast } from '@/utils/toast'

interface AccountSwitcherModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onConnectNewAccount?: () => void
}

export function AccountSwitcherModal({
  open,
  onOpenChange,
  onConnectNewAccount,
}: AccountSwitcherModalProps) {
  const {
    activeAccount,
    connectedAccounts,
    switchAccount,
    isSwitchingAccount,
    refreshAllData,
  } = useExecutionStore()

  // State for open positions confirmation gate
  const [confirmationPending, setConfirmationPending] = useState<{
    targetAccountId: string
    openPositionsCount: number
    message: string
  } | null>(null)

  const [disconnectingId, setDisconnectingId] = useState<string | null>(null)

  const handleActivate = async (account: BrokerAccountDisplay, forceConfirm = false) => {
    if (account.status !== 'CONNECTED') {
      showToast.error(`Cannot activate account in status '${account.status}'. Reconnect required.`)
      return
    }

    const res = await switchAccount(account.account_id, forceConfirm)
    if (res.requires_confirmation) {
      setConfirmationPending({
        targetAccountId: account.account_id,
        openPositionsCount: res.open_positions_count || 1,
        message: res.message || 'Currently active account has open positions.',
      })
      return
    }

    if (res.success) {
      showToast.success(res.message || `Switched active account to ${account.account_label}`)
      setConfirmationPending(null)
      onOpenChange(false)
    } else {
      showToast.error(res.message || 'Failed to switch active account')
    }
  }

  const handleConfirmSwitchWithPositions = async () => {
    if (!confirmationPending) return
    const targetId = confirmationPending.targetAccountId
    const res = await switchAccount(targetId, true)
    if (res.success) {
      showToast.success(res.message || 'Switched active account successfully')
      setConfirmationPending(null)
      onOpenChange(false)
    } else {
      showToast.error(res.message || 'Failed to switch account')
    }
  }

  const handleDisconnect = async (accountId: string) => {
    setDisconnectingId(accountId)
    try {
      const res = await executionApi.disconnectAccount(accountId)
      showToast.info(res.message || 'Account disconnected')
      await refreshAllData()
    } catch (err: any) {
      showToast.error(err?.response?.data?.detail || 'Failed to disconnect account')
    } finally {
      setDisconnectingId(null)
    }
  }

  return (
    <>
      <Dialog open={open && !confirmationPending} onOpenChange={onOpenChange}>
        <DialogContent className="bg-zinc-950 border-zinc-800 text-zinc-100 max-w-lg font-mono shadow-2xl">
          <DialogHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-emerald-950/80 border border-emerald-500/40">
                  <ArrowRightLeft className="w-4 h-4 text-emerald-400" />
                </div>
                <div>
                  <DialogTitle className="text-sm font-bold text-zinc-100 uppercase tracking-wider">
                    Broker Accounts & Switching
                  </DialogTitle>
                  <DialogDescription className="text-xs text-zinc-400">
                    Exactly one account is active for order execution and positions.
                  </DialogDescription>
                </div>
              </div>
              <Badge variant="outline" className="text-[10px] font-mono border-zinc-700 text-zinc-400">
                {connectedAccounts.length} Connected
              </Badge>
            </div>
          </DialogHeader>

          {/* Account Cards List */}
          <div className="flex flex-col gap-2.5 py-2 max-h-[380px] overflow-y-auto pr-1">
            {connectedAccounts.length === 0 ? (
              <div className="p-6 text-center text-xs text-zinc-400 border border-dashed border-zinc-800 rounded-xl">
                <p>No broker accounts connected yet.</p>
                <p className="text-[11px] text-zinc-500 mt-1">Connect Dhan, Zerodha, or Mock accounts to route orders.</p>
              </div>
            ) : (
              connectedAccounts.map((acc) => {
                const isActive = activeAccount?.account_id === acc.account_id
                const isConnected = acc.status === 'CONNECTED'
                const isExpired = acc.status === 'TOKEN_EXPIRED'
                const isFailed = acc.status === 'AUTHENTICATION_FAILED'

                return (
                  <div
                    key={acc.account_id}
                    className={`p-3 rounded-xl border transition-all flex flex-col gap-2 ${
                      isActive
                        ? 'bg-emerald-950/20 border-emerald-500/50 shadow-md shadow-emerald-950/30'
                        : 'bg-zinc-900/60 border-zinc-800/80 hover:border-zinc-700'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex flex-col">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-xs text-zinc-100">
                            {acc.account_label}
                          </span>
                          {isActive && (
                            <Badge className="bg-emerald-500/20 text-emerald-400 border border-emerald-500/50 text-[10px] px-1.5 py-0">
                              ACTIVE
                            </Badge>
                          )}
                        </div>
                        <div className="flex items-center gap-2 text-[11px] text-zinc-400 mt-0.5">
                          <span className="uppercase text-zinc-300 font-semibold">{acc.broker_display_name}</span>
                          <span>•</span>
                          <span>Client: {acc.masked_external_id}</span>
                        </div>
                      </div>

                      {/* Status Badge */}
                      <Badge
                        variant="outline"
                        className={`text-[10px] font-mono px-2 py-0.5 ${
                          isConnected
                            ? 'border-emerald-500/40 text-emerald-400 bg-emerald-500/10'
                            : isExpired
                            ? 'border-amber-500/50 text-amber-400 bg-amber-500/10 animate-pulse'
                            : isFailed
                            ? 'border-rose-500/50 text-rose-400 bg-rose-500/10'
                            : 'border-zinc-700 text-zinc-400 bg-zinc-800/50'
                        }`}
                      >
                        {acc.status}
                      </Badge>
                    </div>

                    {/* Action Row */}
                    <div className="flex items-center justify-between pt-1 border-t border-zinc-800/60 text-xs">
                      <span className="text-[10px] text-zinc-500">
                        {acc.connected_at ? `Connected: ${new Date(acc.connected_at).toLocaleDateString()}` : ''}
                      </span>

                      <div className="flex items-center gap-2">
                        {isExpired && (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-6 text-[10px] border-amber-500/40 text-amber-300 hover:bg-amber-950/40"
                            onClick={() => {
                              showToast.info(`Please re-authenticate ${acc.broker_display_name} via Broker Setup.`)
                            }}
                          >
                            Reconnect
                          </Button>
                        )}

                        {!isActive ? (
                          <Button
                            size="sm"
                            className="h-6 text-[10px] bg-emerald-600 hover:bg-emerald-500 text-white font-mono"
                            disabled={!isConnected || isSwitchingAccount}
                            onClick={() => handleActivate(acc)}
                          >
                            {isSwitchingAccount ? 'Activating...' : 'Set Active'}
                          </Button>
                        ) : (
                          <span className="text-[11px] text-emerald-400 font-semibold flex items-center gap-1">
                            <CheckCircle2 className="w-3 h-3" /> Routing Active
                          </span>
                        )}

                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 text-[10px] text-zinc-400 hover:text-rose-400 hover:bg-rose-950/30 px-2"
                          disabled={disconnectingId === acc.account_id}
                          onClick={() => handleDisconnect(acc.account_id)}
                          title="Disconnect Account"
                        >
                          <LogOut className="w-3 h-3" />
                        </Button>
                      </div>
                    </div>
                  </div>
                )
              })
            )}
          </div>

          <DialogFooter className="pt-2 border-t border-zinc-800 flex items-center justify-between sm:justify-between w-full">
            <Button
              variant="outline"
              size="sm"
              className="text-xs border-zinc-700 text-zinc-300 hover:bg-zinc-900 font-mono"
              onClick={() => {
                onOpenChange(false)
                if (onConnectNewAccount) onConnectNewAccount()
              }}
            >
              <Plus className="w-3.5 h-3.5 mr-1 text-emerald-400" />
              Connect Another Account
            </Button>

            <Button
              size="sm"
              variant="ghost"
              className="text-xs text-zinc-400 hover:text-zinc-200 font-mono"
              onClick={() => onOpenChange(false)}
            >
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* High-Friction Open Positions Confirmation Gate Modal */}
      {confirmationPending && (
        <Dialog open={true} onOpenChange={() => setConfirmationPending(null)}>
          <DialogContent className="bg-zinc-950 border-amber-500/50 text-zinc-100 max-w-md font-mono shadow-2xl shadow-amber-950/40">
            <DialogHeader>
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-lg bg-amber-950/80 border border-amber-500/50">
                  <AlertTriangle className="w-5 h-5 text-amber-400 animate-pulse" />
                </div>
                <div>
                  <DialogTitle className="text-sm font-bold text-amber-300 uppercase tracking-wider">
                    Open Positions Confirmation Required
                  </DialogTitle>
                  <DialogDescription className="text-xs text-zinc-400">
                    Active account has open risk exposure.
                  </DialogDescription>
                </div>
              </div>
            </DialogHeader>

            <div className="flex flex-col gap-3 py-2 text-xs">
              <div className="p-3 rounded-lg bg-amber-950/30 border border-amber-500/30 text-amber-200 leading-relaxed">
                <p className="font-bold mb-1 text-amber-300">
                  Notice: {confirmationPending.openPositionsCount} Open Position(s) Active
                </p>
                Switching active account will redirect future order placement and margin routing to the new account.
                Existing positions on <strong>{activeAccount?.account_label || 'Current Account'}</strong> will remain open and will NOT be automatically squared off.
              </div>
            </div>

            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                variant="outline"
                size="sm"
                className="border-zinc-800 hover:bg-zinc-900 text-zinc-300 text-xs"
                onClick={() => setConfirmationPending(null)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                className="bg-amber-600 hover:bg-amber-500 text-black font-bold text-xs"
                onClick={handleConfirmSwitchWithPositions}
                disabled={isSwitchingAccount}
              >
                {isSwitchingAccount ? 'Switching...' : 'Confirm & Switch Active Account'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
