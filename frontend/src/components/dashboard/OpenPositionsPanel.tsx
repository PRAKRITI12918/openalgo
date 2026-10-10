/**
 * Open Positions Panel for Multi-Account Trading Terminal.
 * Displays consolidated open positions strictly scoped to the active broker account.
 * Features:
 * - Realized / Unrealized / Total P&L color coding
 * - Clear Long vs Short direction indicator
 * - Independent skeleton loading, error retry, and empty states
 */

import {
  Activity,
  AlertCircle,
  ArrowDownRight,
  ArrowUpRight,
  Layers,
  RefreshCw,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import { useExecutionStore } from '@/stores/executionStore'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export function OpenPositionsPanel() {
  const {
    positions,
    activeAccount,
    loadingStates,
    errorStates,
    refreshAllData,
  } = useExecutionStore()

  const isLoading = loadingStates.positions
  const errorMessage = errorStates.positions

  // Flatten active legs or individual position records
  const allPositionRows = positions.flatMap((pos) => {
    if (pos.legs && pos.legs.length > 0) {
      return pos.legs.map((leg) => ({
        positionId: pos.position_id,
        underlying: pos.underlying,
        strategyName: pos.strategy_name,
        symbol: leg.symbol,
        netQuantity: leg.action === 'BUY' ? leg.quantity : -leg.quantity,
        avgPrice: leg.price || 0,
        realizedPnl: pos.realized_pnl || 0,
        unrealizedPnl: pos.unrealized_pnl || 0,
        totalPnl: pos.total_pnl || 0,
        isHedge: leg.is_hedge_leg,
      }))
    }
    return [{
      positionId: pos.position_id,
      underlying: pos.underlying,
      strategyName: pos.strategy_name,
      symbol: pos.underlying,
      netQuantity: 0,
      avgPrice: 0,
      realizedPnl: pos.realized_pnl || 0,
      unrealizedPnl: pos.unrealized_pnl || 0,
      totalPnl: pos.total_pnl || 0,
      isHedge: false,
    }]
  })

  const totalUnrealized = positions.reduce((acc, p) => acc + (p.unrealized_pnl || 0), 0)
  const totalRealized = positions.reduce((acc, p) => acc + (p.realized_pnl || 0), 0)

  return (
    <div className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl p-4 shadow-lg flex flex-col gap-3">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 pb-2 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-emerald-400" />
          <h3 className="font-mono font-bold text-sm text-zinc-100 uppercase tracking-wider">
            Open Portfolio Positions
          </h3>
          {activeAccount && (
            <Badge variant="outline" className="text-[10px] font-mono border-emerald-500/40 text-emerald-400 bg-emerald-500/10">
              {activeAccount.account_label} ({activeAccount.broker_display_name})
            </Badge>
          )}
        </div>

        <div className="flex items-center gap-3 text-xs font-mono">
          <div className="flex items-center gap-1">
            <span className="text-zinc-400">Realized:</span>
            <span className={`font-semibold ${totalRealized >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {totalRealized >= 0 ? '+' : ''}₹{totalRealized.toFixed(2)}
            </span>
          </div>
          <div className="h-4 w-px bg-zinc-800" />
          <div className="flex items-center gap-1">
            <span className="text-zinc-400">Unrealized:</span>
            <span className={`font-semibold ${totalUnrealized >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {totalUnrealized >= 0 ? '+' : ''}₹{totalUnrealized.toFixed(2)}
            </span>
          </div>
        </div>
      </div>

      {/* Content States */}
      {isLoading ? (
        <div className="flex flex-col gap-2 py-3">
          <Skeleton className="h-9 w-full bg-zinc-800/60 rounded" />
          <Skeleton className="h-9 w-full bg-zinc-800/60 rounded" />
          <Skeleton className="h-9 w-full bg-zinc-800/60 rounded" />
        </div>
      ) : errorMessage ? (
        <div className="p-4 rounded-lg bg-rose-950/20 border border-rose-500/30 flex items-center justify-between font-mono text-xs">
          <div className="flex items-center gap-2 text-rose-300">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>Could not load positions: {errorMessage}</span>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs border-rose-500/40 hover:bg-rose-950/40 text-rose-300 font-mono"
            onClick={refreshAllData}
          >
            <RefreshCw className="w-3 h-3 mr-1" /> Retry
          </Button>
        </div>
      ) : allPositionRows.length === 0 ? (
        <div className="py-8 text-center text-xs font-mono text-zinc-400 border border-dashed border-zinc-800 rounded-lg flex flex-col items-center justify-center gap-1">
          <p className="text-zinc-300 font-medium">No Open Positions</p>
          <p className="text-[11px] text-zinc-500">
            {activeAccount
              ? `Account '${activeAccount.account_label}' currently has no open market commitments.`
              : 'Please activate a connected broker account to view positions.'}
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-zinc-800/80 overflow-x-auto bg-zinc-950/40">
          <Table>
            <TableHeader className="bg-zinc-950/80">
              <TableRow className="border-zinc-800/80 hover:bg-transparent">
                <TableHead className="font-mono text-[11px] text-zinc-400 h-9">Underlying</TableHead>
                <TableHead className="font-mono text-[11px] text-zinc-400 h-9">Instrument / Symbol</TableHead>
                <TableHead className="font-mono text-[11px] text-zinc-400 h-9">Strategy</TableHead>
                <TableHead className="font-mono text-[11px] text-zinc-400 h-9 text-right">Net Qty</TableHead>
                <TableHead className="font-mono text-[11px] text-zinc-400 h-9 text-right">Avg Price</TableHead>
                <TableHead className="font-mono text-[11px] text-zinc-400 h-9 text-right">Realized P&L</TableHead>
                <TableHead className="font-mono text-[11px] text-zinc-400 h-9 text-right">Unrealized P&L</TableHead>
                <TableHead className="font-mono text-[11px] text-zinc-400 h-9 text-right">Total P&L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {allPositionRows.map((row, index) => {
                const isLong = row.netQuantity > 0
                const isShort = row.netQuantity < 0
                const pnlPositive = row.totalPnl >= 0

                return (
                  <TableRow
                    key={`${row.positionId}_${row.symbol}_${index}`}
                    className="border-zinc-850 hover:bg-zinc-900/60 font-mono text-xs"
                  >
                    <TableCell className="font-semibold text-zinc-200 py-2">
                      {row.underlying}
                    </TableCell>

                    <TableCell className="font-medium text-zinc-100 py-2 flex items-center gap-1.5">
                      <span>{row.symbol}</span>
                      {row.isHedge && (
                        <Badge variant="outline" className="text-[9px] px-1 py-0 border-blue-500/40 text-blue-400">
                          HEDGE
                        </Badge>
                      )}
                    </TableCell>

                    <TableCell className="text-zinc-400 text-[11px] py-2">
                      {row.strategyName}
                    </TableCell>

                    <TableCell className="text-right py-2">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          isLong
                            ? 'text-emerald-400 bg-emerald-500/10 border border-emerald-500/30'
                            : isShort
                            ? 'text-rose-400 bg-rose-500/10 border border-rose-500/30'
                            : 'text-zinc-400'
                        }`}
                      >
                        {isLong ? `+${row.netQuantity}` : row.netQuantity}
                      </span>
                    </TableCell>

                    <TableCell className="text-right text-zinc-300 py-2">
                      ₹{row.avgPrice.toFixed(2)}
                    </TableCell>

                    <TableCell
                      className={`text-right py-2 ${
                        row.realizedPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
                      }`}
                    >
                      {row.realizedPnl >= 0 ? '+' : ''}₹{row.realizedPnl.toFixed(2)}
                    </TableCell>

                    <TableCell
                      className={`text-right py-2 ${
                        row.unrealizedPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
                      }`}
                    >
                      {row.unrealizedPnl >= 0 ? '+' : ''}₹{row.unrealizedPnl.toFixed(2)}
                    </TableCell>

                    <TableCell
                      className={`text-right font-bold py-2 ${
                        pnlPositive ? 'text-emerald-400' : 'text-rose-400'
                      }`}
                    >
                      {pnlPositive ? '+' : ''}₹{row.totalPnl.toFixed(2)}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
