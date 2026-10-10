/**
 * Real-time WebSocket Protocol & Event Schema Types.
 * Standardizes { type, timestamp, source, payload } envelopes for the trading dashboard.
 */

export type FeedSource = 'mock' | 'sandbox' | 'live'

export type RealtimeEventType =
  | 'market_tick'
  | 'position_update'
  | 'pnl_update'
  | 'order_status'
  | 'strategy_status'
  | 'subscription_ack'
  | 'heartbeat'
  | 'error'

export type ConnectionStatus =
  | 'CONNECTING'
  | 'CONNECTED'
  | 'DISCONNECTED'
  | 'RECONNECTING'

export interface RealtimeEnvelope<T = Record<string, unknown>> {
  type: RealtimeEventType | string
  timestamp: string
  source: FeedSource
  payload: T
  symbol?: string
  ltp?: number
}

export interface MarketTickPayload {
  symbol: string
  ltp: number
  change: number
  change_pct: number
  bid?: number
  ask?: number
  open?: number
  high?: number
  low?: number
  volume?: number
}

export interface PositionUpdatePayload {
  account_id: string
  symbol: string
  quantity: number
  average_price: number
  current_price: number
  unrealized_pnl: number
  realized_pnl?: number
}

export interface PnlUpdatePayload {
  account_id: string
  total_unrealized_pnl: number
  total_realized_pnl: number
  net_pnl: number
  currency: string
  strategies: Record<string, number>
}

export interface OrderStatusPayload {
  order_id: string
  account_id: string
  symbol: string
  side: 'BUY' | 'SELL'
  status: 'PENDING' | 'PLACED' | 'FILLED' | 'PARTIAL' | 'REJECTED' | 'CANCELLED'
  quantity: number
  filled_quantity: number
  price: number
  order_type: string
  error_message?: string
}

export interface StrategyStatusPayload {
  strategy_id: string
  strategy_name: string
  status: 'RUNNING' | 'PAUSED' | 'STOPPED' | 'ERROR'
  pnl: number
  details?: string
}

export interface SubscriptionAckPayload {
  subscribed_channel?: string
  unsubscribed_channel?: string
  active_channels: string[]
  active_symbols: string[]
  is_mock: boolean
}
