/**
 * Live Market Watch & Greeks Analytics Panel.
 * Features:
 * - Real-time synthetic / replayed spot tickers with dynamic green/red tick animations
 * - Bid/Ask depth and spread metrics
 * - Live aggregate Greeks sensitivity gauges (Delta, Theta, Gamma, Vega)
 */

import {
  Activity,
  ArrowDown,
  ArrowUp,
  BarChart2,
  Compass,
  Gauge,
  Layers,
  Radio,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react'
import { useExecutionStore } from '@/stores/executionStore'
import { Badge } from '@/components/ui/badge'

export function MarketWatchGreeksPanel() {
  const { ticks, tickDeltas, activeStrategies } = useExecutionStore()

  const niftyTick = ticks.NIFTY_SPOT || {
    symbol: 'NIFTY_SPOT',
    underlying: 'NIFTY',
    spot_price: 24265.5,
    ltp: 24265.5,
    bid: 24264.8,
    ask: 24266.2,
    open_interest: 2540000,
    volume: 894000,
    iv: 0.148,
    timestamp: new Date().toISOString(),
  }

  const bnfTick = ticks.BANKNIFTY_SPOT || {
    symbol: 'BANKNIFTY_SPOT',
    underlying: 'BANKNIFTY',
    spot_price: 51380.0,
    ltp: 51380.0,
    bid: 51378.0,
    ask: 51382.0,
    open_interest: 1820000,
    volume: 642000,
    iv: 0.168,
    timestamp: new Date().toISOString(),
  }

  // Aggregate Greeks across active strategies
  const totalDelta = activeStrategies.reduce((acc, s) => acc + s.greeks.delta, 0)
  const totalTheta = activeStrategies.reduce((acc, s) => acc + s.greeks.theta, 0)
  const totalVega = activeStrategies.reduce((acc, s) => acc + s.greeks.vega, 0)
  const totalGamma = activeStrategies.reduce((acc, s) => acc + s.greeks.gamma, 0)

  const indices = [
    {
      name: 'NIFTY 50',
      key: 'NIFTY_SPOT',
      tick: niftyTick,
      delta: tickDeltas['NIFTY_SPOT'] || 'neutral',
      step: 50,
    },
    {
      name: 'BANK NIFTY',
      key: 'BANKNIFTY_SPOT',
      tick: bnfTick,
      delta: tickDeltas['BANKNIFTY_SPOT'] || 'neutral',
      step: 100,
    },
  ]

  return (
    <div className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl p-4 shadow-lg flex flex-col gap-3.5">
      <div className="flex items-center justify-between pb-2 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <Radio className="w-4 h-4 text-emerald-400 animate-pulse" />
          <h3 className="font-mono font-bold text-sm text-zinc-100 uppercase tracking-wider">
            Live Market Watch & Greeks Analytics
          </h3>
        </div>
        <Badge
          variant="outline"
          className="text-[10px] font-mono border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
        >
          STREAMING (0.5s TICKS)
        </Badge>
      </div>

      {/* Index Spot Tickers */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {indices.map((idx) => {
          const isUp = idx.delta === 'up'
          const isDown = idx.delta === 'down'

          return (
            <div
              key={idx.key}
              className={`p-3 rounded-lg border bg-zinc-950/80 transition-colors duration-300 font-mono ${
                isUp
                  ? 'border-emerald-500/60 shadow-[0_0_15px_rgba(16,185,129,0.15)]'
                  : isDown
                  ? 'border-rose-500/60 shadow-[0_0_15px_rgba(244,63,94,0.15)]'
                  : 'border-zinc-800'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-zinc-300">
                  {idx.name}
                </span>
                <Badge
                  variant="secondary"
                  className="text-[9px] px-1.5 py-0 font-mono"
                >
                  Step: {idx.step}
                </Badge>
              </div>

              <div className="flex items-baseline justify-between mt-1.5">
                <div className="flex items-center gap-1.5">
                  <span className="text-lg font-black text-zinc-100">
                    ₹{idx.tick.spot_price.toFixed(2)}
                  </span>
                  {isUp && <ArrowUp className="w-4 h-4 text-emerald-400 animate-bounce" />}
                  {isDown && <ArrowDown className="w-4 h-4 text-rose-400 animate-bounce" />}
                </div>

                <div className="text-[11px] text-zinc-400">
                  IV: <span className="text-zinc-200 font-bold">{(idx.tick.iv * 100).toFixed(1)}%</span>
                </div>
              </div>

              <div className="flex items-center justify-between mt-2 pt-2 border-t border-zinc-850 text-[11px] text-zinc-400">
                <span>
                  Bid: <strong className="text-emerald-400">₹{idx.tick.bid.toFixed(2)}</strong>
                </span>
                <span>
                  Ask: <strong className="text-rose-400">₹{idx.tick.ask.toFixed(2)}</strong>
                </span>
                <span>
                  Spread: <strong className="text-zinc-300">₹{(idx.tick.ask - idx.tick.bid).toFixed(2)}</strong>
                </span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Portfolio Greeks Risk Gauge */}
      <div className="p-3 bg-zinc-950/60 border border-zinc-800 rounded-lg">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-zinc-300">
            <Compass className="w-3.5 h-3.5 text-cyan-400" />
            <span>PORTFOLIO AGGREGATE GREEK SENSITIVITIES</span>
          </div>
          <span className="text-[10px] font-mono text-zinc-400">
            Black-Scholes Analytical Engine
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
          <div className="flex flex-col p-2 bg-zinc-900/80 rounded border border-zinc-800/80">
            <span className="text-[10px] text-zinc-400 uppercase">Net Delta (Δ)</span>
            <span
              className={`font-bold text-sm ${
                Math.abs(totalDelta) < 0.1 ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {totalDelta > 0 ? '+' : ''}
              {totalDelta.toFixed(2)}
            </span>
            <span className="text-[9px] text-zinc-400 mt-0.5">
              {Math.abs(totalDelta) < 0.1 ? 'Delta Neutral' : 'Directional Bias'}
            </span>
          </div>

          <div className="flex flex-col p-2 bg-zinc-900/80 rounded border border-zinc-800/80">
            <span className="text-[10px] text-zinc-400 uppercase">Daily Theta (θ)</span>
            <span className="font-bold text-sm text-emerald-400">
              +₹{totalTheta.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </span>
            <span className="text-[9px] text-zinc-400 mt-0.5">Positive Decay / Day</span>
          </div>

          <div className="flex flex-col p-2 bg-zinc-900/80 rounded border border-zinc-800/80">
            <span className="text-[10px] text-zinc-400 uppercase">Net Vega (ν)</span>
            <span className="font-bold text-sm text-rose-400">
              {totalVega > 0 ? '+' : ''}₹{totalVega.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </span>
            <span className="text-[9px] text-zinc-400 mt-0.5">PnL per 1% IV shift</span>
          </div>

          <div className="flex flex-col p-2 bg-zinc-900/80 rounded border border-zinc-800/80">
            <span className="text-[10px] text-zinc-400 uppercase">Net Gamma (Γ)</span>
            <span className="font-bold text-sm text-zinc-200">
              {totalGamma.toFixed(5)}
            </span>
            <span className="text-[9px] text-zinc-400 mt-0.5">Delta Curvature</span>
          </div>
        </div>
      </div>
    </div>
  )
}
