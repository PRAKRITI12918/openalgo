import React from 'react'
import type { RecommendationPosition } from '@/types/recommendation'

interface StrikeVisualizerProps {
  positions: RecommendationPosition[]
  currentPrice?: number
}

interface StrikeNode {
  strike: number
  optionType: 'CE' | 'PE'
  netQuantity: number
  isBuy: boolean
}

export const StrikeVisualizer: React.FC<StrikeVisualizerProps> = ({
  positions,
  currentPrice,
}) => {
  if (!positions || positions.length === 0) {
    return null
  }

  // Aggregate by strike
  const strikeMap = new Map<number, { strike: number; optionType: 'CE' | 'PE'; netQty: number }>()

  for (const pos of positions) {
    const existing = strikeMap.get(pos.strike)
    const signedQty = pos.side === 'BUY' ? pos.quantity : -pos.quantity
    if (existing) {
      existing.netQty += signedQty
    } else {
      strikeMap.set(pos.strike, {
        strike: pos.strike,
        optionType: pos.optionType,
        netQty: signedQty,
      })
    }
  }

  const nodes: StrikeNode[] = Array.from(strikeMap.values())
    .map((item) => ({
      strike: item.strike,
      optionType: item.optionType,
      netQuantity: Math.abs(item.netQty),
      isBuy: item.netQty >= 0,
    }))
    .sort((a, b) => a.strike - b.strike)

  if (nodes.length === 0) return null

  const minStrike = nodes[0].strike
  const maxStrike = nodes[nodes.length - 1].strike
  const strikeRange = maxStrike - minStrike || 1

  // Compute spot marker percentage if in range
  const spotPercent =
    currentPrice && currentPrice >= minStrike && currentPrice <= maxStrike
      ? ((currentPrice - minStrike) / strikeRange) * 100
      : null

  return (
    <div className="recommendation-strike-visualizer">
      <div className="strike-track-container">
        {/* Horizontal baseline track */}
        <div className="strike-axis-line" />

        {/* Current spot price marker if in range */}
        {spotPercent !== null && (
          <div
            className="spot-indicator-marker"
            style={{ left: `${Math.min(95, Math.max(5, spotPercent))}%` }}
            title={`Current Spot: ₹${currentPrice?.toLocaleString('en-IN')}`}
          >
            <div className="spot-dot" />
            <div className="spot-label">LTP</div>
          </div>
        )}

        {/* Dynamic Strike Nodes */}
        <div className="strike-nodes-row">
          {nodes.map((node, idx) => {
            // Position percentage along the horizontal line
            const percent =
              nodes.length === 1
                ? 50
                : ((node.strike - minStrike) / strikeRange) * 88 + 6

            const qtyText = node.isBuy ? `+${node.netQuantity}` : `-${node.netQuantity}`

            return (
              <div
                key={`${node.strike}-${idx}`}
                className="strike-node"
                style={{ left: `${percent}%` }}
              >
                {/* Quantity Pill Above */}
                <div
                  className={`strike-qty-badge ${
                    node.isBuy ? 'buy-tone' : 'sell-tone'
                  }`}
                >
                  {qtyText}
                </div>

                {/* Circular Marker On Axis */}
                <div
                  className={`strike-circle-marker ${
                    node.isBuy ? 'marker-buy' : 'marker-sell'
                  }`}
                >
                  <div className="inner-dot" />
                </div>

                {/* Strike Label Below */}
                <div className="strike-label-text">
                  {node.strike.toLocaleString('en-IN')}&nbsp;{node.optionType}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
