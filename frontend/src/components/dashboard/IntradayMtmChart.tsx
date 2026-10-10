/**
 * Real-time Intraday Cumulative MTM Chart.
 * Renders smooth high-density SVG line chart with dynamic gradient fill,
 * peak P&L tracking, and drawdown bounds.
 *
 * HARD CONSTRAINT:
 * - Shows an explicit "No MTM data yet — awaiting order fills" state before
 *   any fills occur, never a flat fake line or mock data.
 */

import { BarChart3, Clock, Sparkles, TrendingUp } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useExecutionStore } from '@/stores/executionStore'
import { Badge } from '@/components/ui/badge'

export function IntradayMtmChart() {
  const { mtmHistory, totalDayMtm, activeAccount } = useExecutionStore()
  const [hoveredPoint, setHoveredPoint] = useState<{
    time: string
    mtm: number
    spot: number
  } | null>(null)

  const isPositive = totalDayMtm >= 0
  const hasHistory = mtmHistory && mtmHistory.length > 0

  // Calculate scaling for SVG
  const { minVal, maxVal, pathD, areaD, points } = useMemo(() => {
    if (!hasHistory) {
      return { minVal: 0, maxVal: 0, pathD: '', areaD: '', points: [] }
    }

    const values = mtmHistory.map((h) => h.mtm)
    const rawMin = Math.min(...values, 0)
    const rawMax = Math.max(...values, 0)
    const padding = Math.max((rawMax - rawMin) * 0.1, 50)
    const min = rawMin - padding
    const max = rawMax + padding

    const width = 600
    const height = 180

    const pts = mtmHistory.map((h, i) => {
      const x = (i / Math.max(mtmHistory.length - 1, 1)) * width
      const y = height - ((h.mtm - min) / (max - min)) * height
      return { x, y, data: h }
    })

    if (pts.length === 1) {
      const p = pts[0]
      return {
        minVal: min,
        maxVal: max,
        pathD: `M 0,${p.y} L ${width},${p.y}`,
        areaD: `M 0,${p.y} L ${width},${p.y} L ${width},${height} L 0,${height} Z`,
        points: pts,
      }
    }

    let d = `M ${pts[0].x},${pts[0].y}`
    for (let i = 1; i < pts.length; i++) {
      const prev = pts[i - 1]
      const curr = pts[i]
      const midX = (prev.x + curr.x) / 2
      d += ` C ${midX},${prev.y} ${midX},${curr.y} ${curr.x},${curr.y}`
    }

    const area = `${d} L ${width},${height} L 0,${height} Z`

    return { minVal: min, maxVal: max, pathD: d, areaD: area, points: pts }
  }, [mtmHistory, hasHistory])

  const peakMtm = useMemo(() => {
    if (!hasHistory) return 0
    return Math.max(...mtmHistory.map((h) => h.mtm), totalDayMtm)
  }, [mtmHistory, totalDayMtm, hasHistory])

  const maxDrawdown = useMemo(() => {
    if (!hasHistory) return 0
    return Math.min(...mtmHistory.map((h) => h.mtm), 0)
  }, [mtmHistory, hasHistory])

  return (
    <div className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl p-4 shadow-lg flex flex-col gap-3">
      <div className="flex items-center justify-between pb-2 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-emerald-400" />
          <h3 className="font-mono font-bold text-sm text-zinc-100 uppercase tracking-wider">
            Intraday Cumulative MTM Curve
          </h3>
        </div>

        {hasHistory && (
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-[10px] font-mono text-zinc-400">
              Peak: ₹{peakMtm.toFixed(0)}
            </Badge>
            <Badge
              variant="outline"
              className="text-[10px] font-mono text-rose-400 border-rose-500/30"
            >
              Max DD: ₹{maxDrawdown.toFixed(0)}
            </Badge>
          </div>
        )}
      </div>

      {/* SVG Chart Area or Honest Empty State */}
      <div className="relative w-full h-[180px] bg-zinc-950/80 rounded-lg p-2 overflow-hidden border border-zinc-850 flex items-center justify-center">
        {!hasHistory ? (
          <div className="flex flex-col items-center justify-center gap-1.5 text-center font-mono text-xs text-zinc-500">
            <BarChart3 className="w-6 h-6 text-zinc-700" />
            <span className="text-zinc-400 font-medium">No MTM Data Yet</span>
            <span className="text-[11px] text-zinc-600 max-w-xs">
              MTM tracking commences once trades execute and mark-to-market prices fluctuate.
            </span>
          </div>
        ) : (
          <svg
            viewBox="0 0 600 180"
            preserveAspectRatio="none"
            className="w-full h-full"
          >
            <defs>
              <linearGradient id="mtmGradientGreen" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#10b981" stopOpacity="0.35" />
                <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
              </linearGradient>
              <linearGradient id="mtmGradientRed" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f43f5e" stopOpacity="0.35" />
                <stop offset="100%" stopColor="#f43f5e" stopOpacity="0.0" />
              </linearGradient>
            </defs>

            {/* Grid lines */}
            <line x1="0" y1="45" x2="600" y2="45" stroke="#27272a" strokeDasharray="4 4" />
            <line x1="0" y1="90" x2="600" y2="90" stroke="#27272a" strokeDasharray="4 4" />
            <line x1="0" y1="135" x2="600" y2="135" stroke="#27272a" strokeDasharray="4 4" />

            {/* Area Fill */}
            {areaD && (
              <path
                d={areaD}
                fill={isPositive ? 'url(#mtmGradientGreen)' : 'url(#mtmGradientRed)'}
              />
            )}

            {/* Stroke Line */}
            {pathD && (
              <path
                d={pathD}
                fill="none"
                stroke={isPositive ? '#10b981' : '#f43f5e'}
                strokeWidth="2.5"
                strokeLinecap="round"
              />
            )}

            {/* Hover interactive markers */}
            {points.map((pt, i) => (
              <circle
                key={i}
                cx={pt.x}
                cy={pt.y}
                r="3.5"
                className="fill-zinc-950 stroke-emerald-400 stroke-2 hover:r-5 cursor-pointer transition-all"
                onMouseEnter={() => setHoveredPoint(pt.data)}
                onMouseLeave={() => setHoveredPoint(null)}
              />
            ))}
          </svg>
        )}

        {/* Hover Tooltip Overlay */}
        {hoveredPoint && (
          <div className="absolute top-3 right-3 bg-zinc-900 border border-zinc-700 px-2.5 py-1 rounded shadow-lg font-mono text-[11px] pointer-events-none">
            <span className="text-zinc-400">{hoveredPoint.time} • </span>
            <span
              className={
                hoveredPoint.mtm >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'
              }
            >
              {hoveredPoint.mtm >= 0 ? '+' : ''}₹{hoveredPoint.mtm.toFixed(2)}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
