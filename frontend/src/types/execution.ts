/**
 * Phase 2 & 3 Execution Engine and Trading Dashboard Domain Types.
 * Matches backend FastAPI Pydantic V2 schemas and WebSocket event contracts.
 */

export type UnderlyingIndex = 'NIFTY' | 'BANKNIFTY' | 'SENSEX'

export type StrategyType =
  | 'IRON_CONDOR'
  | 'BULL_CALL_SPREAD'
  | 'BEAR_PUT_SPREAD'
  | 'CALENDAR_SPREAD'
  | 'RATIO_SPREAD'
  | 'HEDGED_STRADDLE'
  | 'SHORT_STRANGLE'

export type OptionType = 'CE' | 'PE'

export type OrderAction = 'BUY' | 'SELL'

export type OrderType = 'MARKET' | 'LIMIT' | 'SL_MARKET' | 'SL_LIMIT'

export type SignalType =
  | 'ENTRY'
  | 'EXIT'
  | 'STOP_LOSS'
  | 'TARGET'
  | 'TRAILING_STOP'
  | 'HEDGE_ADJUSTMENT'
  | 'NO_ACTION'

export type MarketRegime =
  | 'HIGH_IV_TRENDING'
  | 'LOW_IV_RANGING'
  | 'VOLATILITY_EXPANSION'
  | 'MEAN_REVERTING'

export type OrderStatus =
  | 'PENDING'
  | 'OPEN'
  | 'TRIGGERED'
  | 'COMPLETE'
  | 'REJECTED'
  | 'CANCELLED'
  | 'ROLLED_BACK'

export type BrokerConnectionStatus =
  | 'CONNECTED'
  | 'CONNECTING'
  | 'DISCONNECTED'
  | 'TOKEN_EXPIRED'
  | 'AUTHENTICATION_FAILED'

export interface BrokerAccountDisplay {
  account_id: string
  broker_id: string
  broker_display_name: string
  account_label: string
  masked_external_id: string
  status: BrokerConnectionStatus
  is_active: boolean
  connected_at?: string
  last_verified_at?: string
}

export interface PendingSignalSummary {
  signal_id: string
  strategy_name: string
  underlying: UnderlyingIndex
  legs_count: number
  requires_approval: boolean
  received_at: string
  expires_at: string
  remaining_seconds: number
  legs: LegOrderRequest[]
  max_loss?: number
  max_profit?: number
  reason?: string
}

export interface PendingSignalListResponse {
  success: boolean
  count: number
  signals: PendingSignalSummary[]
  timestamp: string
}

export interface Greeks {
  delta: number
  gamma: number
  theta: number
  vega: number
  rho: number
  iv: number
}

export interface LegOrderRequest {
  leg_id: string
  symbol: string
  underlying: UnderlyingIndex
  strike: number
  option_type: OptionType
  expiry: string
  action: OrderAction
  quantity: number
  order_type?: OrderType
  price?: number
  trigger_price?: number
  is_hedge_leg?: boolean
  sequence_group?: number
  target_delta?: number
  actual_delta?: number
  greeks?: Greeks
  product?: string
  exchange?: string
}

export interface StrategySignalPayload {
  signal_id: string
  strategy_name: string
  strategy_type?: StrategyType
  signal_type: SignalType
  underlying: UnderlyingIndex
  regime: MarketRegime
  legs: LegOrderRequest[]
  entry_credit_debit?: number
  max_profit?: number
  max_loss?: number
  stop_loss_threshold?: number
  target_threshold?: number
  trailing_stop_step?: number
  correlation_id: string
  timestamp: string
  reason?: string
  metadata?: Record<string, unknown>
}

export interface LegExecutionState {
  leg_id: string
  symbol: string
  action: OrderAction
  strike: number
  quantity: number
  filled_quantity: number
  requested_price: number
  execution_price: number
  slippage: number
  status: OrderStatus
  order_id?: string
  broker_response?: Record<string, unknown>
  error_message?: string
  latency_ms: number
  is_hedge_leg: boolean
  placed_at: string
  updated_at: string
}

export interface OrderExecutionSequence {
  sequence_id: string
  signal_id: string
  correlation_id: string
  strategy_name: string
  underlying: UnderlyingIndex
  status:
    | 'PENDING'
    | 'IN_PROGRESS'
    | 'FULLY_FILLED'
    | 'PARTIALLY_FILLED'
    | 'FAILED'
    | 'ABORTED_CIRCUIT_BREAKER'
    | 'ROLLED_BACK'
  total_legs: number
  completed_legs: number
  failed_legs: number
  circuit_breaker_triggered: boolean
  leg_states: LegExecutionState[]
  error_summary?: string
  execution_start_time: string
  execution_end_time?: string
}

export interface RollbackReport {
  sequence_id: string
  signal_id: string
  correlation_id: string
  reason: string
  rolled_back_legs: LegExecutionState[]
  status: string
  timestamp: string
}

export interface PositionStateModel {
  position_id: string
  strategy_name: string
  underlying: UnderlyingIndex
  legs: LegOrderRequest[]
  net_delta: number
  net_gamma: number
  net_theta: number
  net_vega: number
  unrealized_pnl: number
  realized_pnl: number
  total_pnl: number
  margin_utilized: number
  is_active: boolean
  entry_time: string
  updated_at: string
}

export interface SyntheticTickPayload {
  symbol: string
  underlying: UnderlyingIndex
  spot_price: number
  ltp: number
  bid: number
  ask: number
  open_interest: number
  volume: number
  iv: number
  greeks?: Greeks
  timestamp: string
}

export type WebSocketEventType =
  | 'TICK'
  | 'ORDER_SUBMITTED'
  | 'ORDER_UPDATE'
  | 'SEQUENCE_UPDATE'
  | 'POSITION_UPDATE'
  | 'CIRCUIT_BREAKER'
  | 'ROLLBACK_TRIGGERED'
  | 'HEARTBEAT'
  | 'ERROR'

export interface ExecutionEventMessage {
  event_type: WebSocketEventType
  correlation_id: string
  timestamp: string
  data: Record<string, unknown>
}

export interface BrokerCredentialsConfig {
  broker: string
  apiKey: string
  apiSecret: string
  clientId: string
  totpSeed: string
  isSandbox: boolean
}
