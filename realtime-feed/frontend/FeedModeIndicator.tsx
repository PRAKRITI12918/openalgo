/**
 * Feed Mode Visual Indicator Component.
 *
 * Enforces the non-negotiable safety rule:
 * NEVER let mock data be labeled, displayed, or mistaken as real market data.
 */

import React from 'react'
import type { ConnectionStatus, FeedSource } from './types'

export interface FeedModeIndicatorProps {
  status: ConnectionStatus
  feedSource: FeedSource
  isMock: boolean
  className?: string
}

export const FeedModeIndicator: React.FC<FeedModeIndicatorProps> = ({
  status,
  feedSource,
  isMock,
  className = '',
}) => {
  if (status === 'DISCONNECTED') {
    return (
      <div
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-zinc-800 bg-zinc-900/80 text-zinc-400 font-mono text-[11px] ${className}`}
        title="WebSocket stream disconnected"
      >
        <span className="w-2 h-2 rounded-full bg-zinc-600" />
        <span>STREAM OFFLINE</span>
      </div>
    )
  }

  if (status === 'CONNECTING' || status === 'RECONNECTING') {
    return (
      <div
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-amber-800/60 bg-amber-950/40 text-amber-300 font-mono text-[11px] animate-pulse ${className}`}
        title={`Attempting connection (${status})`}
      >
        <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
        <span>RECONNECTING...</span>
      </div>
    )
  }

  // Active Connection — Render Mode Provenance
  if (isMock || feedSource === 'mock') {
    return (
      <div
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-amber-500/50 bg-amber-950/50 text-amber-300 font-mono text-[11px] font-bold shadow-sm shadow-amber-950/40 ${className}`}
        title="SAFETY NOTICE: All ticks, prices, and P&L on this feed are synthetically simulated for local development. Never treat as real market data."
      >
        <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
        <span className="tracking-wide">SIMULATED / MOCK FEED</span>
      </div>
    )
  }

  if (feedSource === 'sandbox') {
    return (
      <div
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-cyan-500/50 bg-cyan-950/50 text-cyan-300 font-mono text-[11px] font-bold ${className}`}
        title="Broker sandbox paper stream active. Exercising real integration code without real financial exposure."
      >
        <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
        <span className="tracking-wide">BROKER SANDBOX STREAM</span>
      </div>
    )
  }

  if (feedSource === 'live') {
    return (
      <div
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-emerald-500/50 bg-emerald-950/50 text-emerald-300 font-mono text-[11px] font-bold shadow-md shadow-emerald-950/50 ${className}`}
        title="Real live exchange/broker market data feed active."
      >
        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
        <span className="tracking-wide">LIVE BROKER FEED</span>
      </div>
    )
  }

  return null
}
