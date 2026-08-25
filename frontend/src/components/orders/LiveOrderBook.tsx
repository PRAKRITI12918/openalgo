/**
 * Live Order Book & Multi-Leg Execution Pipeline Stream.
 * Features:
 * - Real-time tabular streaming from /ws/executions and /api/v1/orders
 * - Clear Tier 0 (Hedge Protection) vs Tier 1 (Short Credit) sequence demarcation
 * - Status filtering, execution latency, and slippage monitoring
 */

import {
  Activity,
  AlertCircle,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Filter,
  Layers,
  Search,
  Shield,
  Zap,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useExecutionStore } from '@/stores/executionStore'
import type { LegExecutionState, OrderStatus } from '@/types/execution'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

// Demo fallback seed orders if store is initially empty
const SEED_ORDERS: LegExecutionState[] = [
  {
    leg_id: 'LEG_NIFTY_23800_PE',
    symbol: 'NIFTY26AUG23800PE',
    action: 'BUY',
    strike: 23800,
    quantity: 50,
    filled_quantity: 50,
    requested_price: 22.5,
    execution_price: 22.55,
    slippage: 0.05,
    status: 'COMPLETE',
    order_id: 'MOCK_ORD_7F89B21A',
    latency_ms: 12.4,
    is_hedge_leg: true,
    placed_at: new Date(Date.now() - 120000).toISOString(),
    updated_at: new Date(Date.now() - 119980).toISOString(),
  },
  {
    leg_id: 'LEG_NIFTY_24600_CE',
    symbol: 'NIFTY26AUG24600CE',
    action: 'BUY',
    strike: 24600,
    quantity: 50,
    filled_quantity: 50,
    requested_price: 25.0,
    execution_price: 24.95,
    slippage: -0.05,
    status: 'COMPLETE',
    order_id: 'MOCK_ORD_4E31C98D',
    latency_ms: 14.8,
    is_hedge_leg: true,
    placed_at: new Date(Date.now() - 118000).toISOString(),
    updated_at: new Date(Date.now() - 117980).toISOString(),
  },
  {
    leg_id: 'LEG_NIFTY_24000_PE',
    symbol: 'NIFTY26AUG24000PE',
    action: 'SELL',
    strike: 24000,
    quantity: 50,
    filled_quantity: 50,
    requested_price: 68.0,
    execution_price: 67.9,
    slippage: -0.1,
    status: 'COMPLETE',
    order_id: 'MOCK_ORD_9A12DF4E',
    latency_ms: 11.2,
    is_hedge_leg: false,
    placed_at: new Date(Date.now() - 115000).toISOString(),
    updated_at: new Date(Date.now() - 114980).toISOString(),
  },
  {
    leg_id: 'LEG_NIFTY_24400_CE',
    symbol: 'NIFTY26AUG24400CE',
    action: 'SELL',
    strike: 24400,
    quantity: 50,
    filled_quantity: 50,
    requested_price: 74.5,
    execution_price: 74.6,
    slippage: 0.1,
    status: 'COMPLETE',
    order_id: 'MOCK_ORD_2B88AE9C',
    latency_ms: 13.5,
    is_hedge_leg: false,
    placed_at: new Date(Date.now() - 113000).toISOString(),
    updated_at: new Date(Date.now() - 112980).toISOString(),
  },
]

export function LiveOrderBook() {
  const { orders } = useExecutionStore()
  const [filterStatus, setFilterStatus] = useState<string>('ALL')
  const [searchQuery, setSearchQuery] = useState<string>('')

  const displayOrders = orders.length > 0 ? orders : SEED_ORDERS

  const filteredOrders = useMemo(() => {
    return displayOrders.filter((order) => {
      const matchStatus =
        filterStatus === 'ALL' || order.status === filterStatus
      const matchSearch =
        searchQuery === '' ||
        order.symbol.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (order.order_id &&
          order.order_id.toLowerCase().includes(searchQuery.toLowerCase()))
      return matchStatus && matchSearch
    })
  }, [displayOrders, filterStatus, searchQuery])

  return (
    <div className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl p-4 shadow-lg flex flex-col gap-3">
      {/* Header & Filter Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 pb-2 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-emerald-400" />
          <h3 className="font-mono font-bold text-sm text-zinc-100 uppercase tracking-wider">
            Live Order Book & Margin-Safety Execution Pipeline
          </h3>
          <Badge variant="outline" className="text-[10px] font-mono text-zinc-400">
            {filteredOrders.length} Orders
          </Badge>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
          <div className="relative w-full sm:w-44">
            <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-2.5" />
            <Input
              placeholder="Search symbol/ID..."
              className="h-8 pl-8 text-xs font-mono bg-zinc-950/60 border-zinc-800"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <div className="flex items-center gap-1 bg-zinc-950/60 p-0.5 rounded-lg border border-zinc-800">
            {['ALL', 'COMPLETE', 'PENDING', 'REJECTED'].map((st) => (
              <Button
                key={st}
                variant="ghost"
                size="sm"
                className={`h-7 px-2.5 text-[11px] font-mono rounded ${
                  filterStatus === st
                    ? 'bg-zinc-800 text-zinc-100 font-bold'
                    : 'text-zinc-400 hover:text-zinc-200'
                }`}
                onClick={() => setFilterStatus(st)}
              >
                {st}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {/* Margin Sequencing Explanation Banner */}
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-950/60 border border-zinc-800/80 text-[11px] font-mono text-zinc-400">
        <Shield className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
        <span>
          <strong className="text-emerald-400">Margin-Safe Rule Enforced:</strong>{' '}
          Tier 0 (Hedge Wings: BUY) confirmed before Tier 1 (Short Credit: SELL)
          submits.
        </span>
      </div>

      {/* Order Table */}
      <div className="rounded-lg border border-zinc-800/80 overflow-x-auto bg-zinc-950/40">
        <Table>
          <TableHeader className="bg-zinc-950/80">
            <TableRow className="border-zinc-800/80 hover:bg-transparent">
              <TableHead className="font-mono text-[11px] text-zinc-400 h-9">Time</TableHead>
              <TableHead className="font-mono text-[11px] text-zinc-400 h-9">Order ID</TableHead>
              <TableHead className="font-mono text-[11px] text-zinc-400 h-9">Instrument</TableHead>
              <TableHead className="font-mono text-[11px] text-zinc-400 h-9">Sequence Tier</TableHead>
              <TableHead className="font-mono text-[11px] text-zinc-400 h-9">Action</TableHead>
              <TableHead className="font-mono text-[11px] text-zinc-400 h-9 text-right">Qty</TableHead>
              <TableHead className="font-mono text-[11px] text-zinc-400 h-9 text-right">Req Price</TableHead>
              <TableHead className="font-mono text-[11px] text-zinc-400 h-9 text-right">Fill Price</TableHead>
              <TableHead className="font-mono text-[11px] text-zinc-400 h-9 text-right">Slippage</TableHead>
              <TableHead className="font-mono text-[11px] text-zinc-400 h-9 text-right">Latency</TableHead>
              <TableHead className="font-mono text-[11px] text-zinc-400 h-9 text-center">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredOrders.map((ord, index) => {
              const timeFormatted = ord.placed_at
                ? new Date(ord.placed_at).toLocaleTimeString([], {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })
                : '--:--:--'

              const isBuy = ord.action === 'BUY'
              const isComplete = ord.status === 'COMPLETE'
              const isRejected = ord.status === 'REJECTED'

              return (
                <TableRow
                  key={ord.order_id || ord.leg_id || index}
                  className="border-zinc-850 hover:bg-zinc-900/60 font-mono text-xs"
                >
                  {/* Time */}
                  <TableCell className="text-zinc-400 text-[11px] py-2">
                    {timeFormatted}
                  </TableCell>

                  {/* Order ID */}
                  <TableCell className="font-semibold text-zinc-300 py-2">
                    {ord.order_id || ord.leg_id.slice(0, 12)}
                  </TableCell>

                  {/* Instrument */}
                  <TableCell className="font-medium text-zinc-100 py-2">
                    {ord.symbol}
                  </TableCell>

                  {/* Sequence Tier */}
                  <TableCell className="py-2">
                    {ord.is_hedge_leg || isBuy ? (
                      <Badge
                        variant="outline"
                        className="text-[10px] px-1.5 py-0 border-blue-500/40 bg-blue-500/10 text-blue-400"
                      >
                        TIER 0 • HEDGE
                      </Badge>
                    ) : (
                      <Badge
                        variant="outline"
                        className="text-[10px] px-1.5 py-0 border-purple-500/40 bg-purple-500/10 text-purple-400"
                      >
                        TIER 1 • CREDIT
                      </Badge>
                    )}
                  </TableCell>

                  {/* Action */}
                  <TableCell className="py-2">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        isBuy
                          ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                          : 'bg-rose-500/20 text-rose-400 border border-rose-500/40'
                      }`}
                    >
                      {ord.action}
                    </span>
                  </TableCell>

                  {/* Qty */}
                  <TableCell className="text-right text-zinc-200 py-2">
                    {ord.filled_quantity}/{ord.quantity}
                  </TableCell>

                  {/* Req Price */}
                  <TableCell className="text-right text-zinc-400 py-2">
                    ₹{ord.requested_price.toFixed(2)}
                  </TableCell>

                  {/* Fill Price */}
                  <TableCell className="text-right font-bold text-zinc-100 py-2">
                    {ord.execution_price > 0
                      ? `₹${ord.execution_price.toFixed(2)}`
                      : '---'}
                  </TableCell>

                  {/* Slippage */}
                  <TableCell className="text-right py-2">
                    {ord.slippage !== 0 ? (
                      <span
                        className={
                          ord.slippage > 0
                            ? 'text-rose-400'
                            : 'text-emerald-400'
                        }
                      >
                        {ord.slippage > 0 ? '+' : ''}
                        {ord.slippage.toFixed(2)}
                      </span>
                    ) : (
                      <span className="text-zinc-500">0.00</span>
                    )}
                  </TableCell>

                  {/* Latency */}
                  <TableCell className="text-right text-zinc-400 py-2">
                    {ord.latency_ms > 0 ? `${ord.latency_ms}ms` : '<10ms'}
                  </TableCell>

                  {/* Status */}
                  <TableCell className="text-center py-2">
                    <Badge
                      className={`text-[10px] font-mono px-2 py-0.5 ${
                        isComplete
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/40'
                          : isRejected
                          ? 'bg-rose-500/10 text-rose-400 border border-rose-500/40'
                          : 'bg-amber-500/10 text-amber-400 border border-amber-500/40'
                      }`}
                    >
                      {ord.status}
                    </Badge>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
