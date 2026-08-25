/**
 * Real-time Execution Engine & Trading Dashboard Zustand Store.
 * Centralizes MTM tracking, tick feeds, order states, active strategies, and circuit-breaker status.
 */

import { create } from 'zustand'
import type {
  BrokerConnectionStatus,
  BrokerCredentialsConfig,
  ExecutionEventMessage,
  Greeks,
  LegExecutionState,
  OrderExecutionSequence,
  PositionStateModel,
  StrategySignalPayload,
  SyntheticTickPayload,
} from '@/types/execution'

export interface ActiveStrategyCard {
  strategyId: string
  name: string
  type: string
  underlying: string
  status: 'Active' | 'Hedging' | 'Filled' | 'Exited' | 'Circuit Breaker'
  netPnl: number
  pnlPercentage: number
  entrySpot: number
  currentSpot: number
  entryCreditDebit: number
  greeks: Greeks
  legs: {
    symbol: string
    action: 'BUY' | 'SELL'
    strike: number
    optionType: 'CE' | 'PE'
    quantity: number
    entryPrice: number
    ltp: number
    isHedgeLeg: boolean
    status: string
  }[]
  createdAt: string
  updatedAt: string
}

export interface ExecutionStoreState {
  // Connection & System Status
  brokerStatus: BrokerConnectionStatus
  wsMarketConnected: boolean
  wsExecutionsConnected: boolean
  circuitBreakerActive: boolean
  circuitBreakerDetails: { reason?: string; timestamp?: string } | null

  // Account Capital & Live MTM
  availableFunds: number
  utilizedMargin: number
  totalFunds: number
  totalDayMtm: number
  mtmHistory: { time: string; timestamp: number; mtm: number; spot: number }[]

  // Market Ticks & Flashing Animations
  ticks: Record<string, SyntheticTickPayload>
  tickDeltas: Record<string, 'up' | 'down' | 'neutral'>

  // Strategy Containers (AOS Cards)
  activeStrategies: ActiveStrategyCard[]

  // Real-time Order Book
  orders: LegExecutionState[]
  sequences: OrderExecutionSequence[]

  // Queue of incoming Phase 1 Strategy Signals awaiting trader approval
  queuedSignals: StrategySignalPayload[]

  // Broker Credentials (persisted in localStorage securely)
  brokerCredentials: BrokerCredentialsConfig

  // Actions
  setBrokerStatus: (status: BrokerConnectionStatus) => void
  setWsMarketConnected: (connected: boolean) => void
  setWsExecutionsConnected: (connected: boolean) => void
  setCircuitBreaker: (
    active: boolean,
    details?: { reason?: string; timestamp?: string } | null
  ) => void
  updateFunds: (
    available: number,
    utilized: number,
    total?: number
  ) => void
  handleMarketTick: (tick: SyntheticTickPayload) => void
  handleExecutionEvent: (event: ExecutionEventMessage) => void
  addOrderState: (order: LegExecutionState) => void
  addSequence: (sequence: OrderExecutionSequence) => void
  updatePositionsFromBroker: (positions: PositionStateModel[]) => void
  queueSignal: (signal: StrategySignalPayload) => void
  approveSignal: (signalId: string) => StrategySignalPayload | undefined
  rejectSignal: (signalId: string) => void
  squareOffAll: () => void
  resetCircuitBreakerState: () => void
  saveBrokerCredentials: (creds: Partial<BrokerCredentialsConfig>) => void
}

// Initial demo credentials
const INITIAL_CREDENTIALS: BrokerCredentialsConfig = {
  broker: 'OpenAlgo Mock Broker',
  apiKey: 'oa_live_sec_9948271',
  apiSecret: '••••••••••••••••••••••••',
  clientId: 'ALGO_QUANT_01',
  totpSeed: 'JBSWY3DPEHPK3PXP',
  isSandbox: true,
}

// Default initial demo strategies for instant rich HUD visualization
const INITIAL_STRATEGIES: ActiveStrategyCard[] = [
  {
    strategyId: 'AOS_NIFTY_IC_01',
    name: 'Iron Condor 24200/24400',
    type: 'IRON_CONDOR',
    underlying: 'NIFTY',
    status: 'Active',
    netPnl: 4850.0,
    pnlPercentage: 3.25,
    entrySpot: 24220.0,
    currentSpot: 24265.5,
    entryCreditDebit: 95.0,
    greeks: {
      delta: -0.04,
      gamma: 0.00012,
      theta: 2450.0,
      vega: -310.0,
      rho: 12.5,
      iv: 0.145,
    },
    legs: [
      {
        symbol: 'NIFTY26AUG23800PE',
        action: 'BUY',
        strike: 23800,
        optionType: 'PE',
        quantity: 50,
        entryPrice: 22.5,
        ltp: 18.2,
        isHedgeLeg: true,
        status: 'COMPLETE',
      },
      {
        symbol: 'NIFTY26AUG24000PE',
        action: 'SELL',
        strike: 24000,
        optionType: 'PE',
        quantity: 50,
        entryPrice: 68.0,
        ltp: 49.5,
        isHedgeLeg: false,
        status: 'COMPLETE',
      },
      {
        symbol: 'NIFTY26AUG24400CE',
        action: 'SELL',
        strike: 24400,
        optionType: 'CE',
        quantity: 50,
        entryPrice: 74.5,
        ltp: 58.0,
        isHedgeLeg: false,
        status: 'COMPLETE',
      },
      {
        symbol: 'NIFTY26AUG24600CE',
        action: 'BUY',
        strike: 24600,
        optionType: 'CE',
        quantity: 50,
        entryPrice: 25.0,
        ltp: 19.8,
        isHedgeLeg: true,
        status: 'COMPLETE',
      },
    ],
    createdAt: new Date(Date.now() - 3600000 * 2).toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    strategyId: 'AOS_BNF_STRANGLE_02',
    name: 'Short Strangle 51000/51500',
    type: 'SHORT_STRANGLE',
    underlying: 'BANKNIFTY',
    status: 'Hedging',
    netPnl: -1240.0,
    pnlPercentage: -0.85,
    entrySpot: 51250.0,
    currentSpot: 51380.0,
    entryCreditDebit: 280.0,
    greeks: {
      delta: 0.12,
      gamma: 0.00028,
      theta: 4120.0,
      vega: -580.0,
      rho: 24.0,
      iv: 0.168,
    },
    legs: [
      {
        symbol: 'BANKNIFTY26AUG51000PE',
        action: 'SELL',
        strike: 51000,
        optionType: 'PE',
        quantity: 30,
        entryPrice: 140.0,
        ltp: 98.0,
        isHedgeLeg: false,
        status: 'COMPLETE',
      },
      {
        symbol: 'BANKNIFTY26AUG51500CE',
        action: 'SELL',
        strike: 51500,
        optionType: 'CE',
        quantity: 30,
        entryPrice: 140.0,
        ltp: 182.0,
        isHedgeLeg: false,
        status: 'COMPLETE',
      },
    ],
    createdAt: new Date(Date.now() - 3600000).toISOString(),
    updatedAt: new Date().toISOString(),
  },
]

export const useExecutionStore = create<ExecutionStoreState>((set, get) => ({
  brokerStatus: 'CONNECTED',
  wsMarketConnected: false,
  wsExecutionsConnected: false,
  circuitBreakerActive: false,
  circuitBreakerDetails: null,

  availableFunds: 845200.0,
  utilizedMargin: 154800.0,
  totalFunds: 1000000.0,
  totalDayMtm: 3610.0,
  mtmHistory: [
    { time: '09:15', timestamp: Date.now() - 18000000, mtm: 0, spot: 24200 },
    { time: '10:00', timestamp: Date.now() - 14400000, mtm: 850, spot: 24215 },
    { time: '11:00', timestamp: Date.now() - 10800000, mtm: 1950, spot: 24230 },
    { time: '12:00', timestamp: Date.now() - 7200000, mtm: 3100, spot: 24250 },
    { time: '13:00', timestamp: Date.now() - 3600000, mtm: 2800, spot: 24240 },
    { time: '14:00', timestamp: Date.now() - 1800000, mtm: 3610, spot: 24265 },
  ],

  ticks: {
    NIFTY_SPOT: {
      symbol: 'NIFTY_SPOT',
      underlying: 'NIFTY',
      spot_price: 24265.5,
      ltp: 24265.5,
      bid: 24264.8,
      ask: 24266.2,
      open_interest: 2540000,
      volume: 894000,
      iv: 0.148,
      greeks: { delta: 0.5, gamma: 0.0002, theta: -12.5, vega: 18.2, rho: 2.1, iv: 0.148 },
      timestamp: new Date().toISOString(),
    },
    BANKNIFTY_SPOT: {
      symbol: 'BANKNIFTY_SPOT',
      underlying: 'BANKNIFTY',
      spot_price: 51380.0,
      ltp: 51380.0,
      bid: 51378.0,
      ask: 51382.0,
      open_interest: 1820000,
      volume: 642000,
      iv: 0.168,
      greeks: { delta: 0.5, gamma: 0.0001, theta: -24.0, vega: 28.5, rho: 3.5, iv: 0.168 },
      timestamp: new Date().toISOString(),
    },
  },
  tickDeltas: {},

  activeStrategies: INITIAL_STRATEGIES,
  orders: [],
  sequences: [],
  queuedSignals: [],
  brokerCredentials: INITIAL_CREDENTIALS,

  setBrokerStatus: (status) => set({ brokerStatus: status }),
  setWsMarketConnected: (connected) => set({ wsMarketConnected: connected }),
  setWsExecutionsConnected: (connected) =>
    set({ wsExecutionsConnected: connected }),

  setCircuitBreaker: (active, details = null) =>
    set({ circuitBreakerActive: active, circuitBreakerDetails: details }),

  updateFunds: (available, utilized, total) =>
    set((state) => ({
      availableFunds: available,
      utilizedMargin: utilized,
      totalFunds: total ?? state.totalFunds,
    })),

  handleMarketTick: (tick) =>
    set((state) => {
      const prev = state.ticks[tick.symbol]
      const delta: 'up' | 'down' | 'neutral' =
        !prev || tick.ltp === prev.ltp
          ? 'neutral'
          : tick.ltp > prev.ltp
          ? 'up'
          : 'down'

      const newTicks = { ...state.ticks, [tick.symbol]: tick }
      const newDeltas = { ...state.tickDeltas, [tick.symbol]: delta }

      // Update strategy card live spots and P&L if relevant
      const updatedStrategies = state.activeStrategies.map((strat) => {
        if (tick.underlying === strat.underlying) {
          const spotDiff = tick.spot_price - strat.entrySpot
          // Simple delta-approximation for real-time MTM oscillation
          const approxPnlDelta = strat.greeks.delta * spotDiff * 50
          const updatedPnl = Math.round((strat.netPnl + approxPnlDelta) * 100) / 100
          return {
            ...strat,
            currentSpot: tick.spot_price,
            netPnl: updatedPnl,
            updatedAt: new Date().toISOString(),
          }
        }
        return strat
      })

      const totalMtm = updatedStrategies.reduce((acc, s) => acc + s.netPnl, 0)

      // Add to MTM history if enough time elapsed (throttled)
      const now = Date.now()
      const lastPoint = state.mtmHistory[state.mtmHistory.length - 1]
      let newHistory = state.mtmHistory
      if (!lastPoint || now - lastPoint.timestamp > 30000) {
        const timeStr = new Date(now).toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        })
        newHistory = [
          ...state.mtmHistory.slice(-29),
          { time: timeStr, timestamp: now, mtm: totalMtm, spot: tick.spot_price },
        ]
      }

      return {
        ticks: newTicks,
        tickDeltas: newDeltas,
        activeStrategies: updatedStrategies,
        totalDayMtm: Math.round(totalMtm * 100) / 100,
        mtmHistory: newHistory,
      }
    }),

  handleExecutionEvent: (event) => {
    const { event_type, data } = event
    const state = get()

    if (event_type === 'ORDER_UPDATE') {
      const legState = data as unknown as LegExecutionState
      state.addOrderState(legState)
    } else if (event_type === 'SEQUENCE_UPDATE') {
      const seq = data as unknown as OrderExecutionSequence
      state.addSequence(seq)
    } else if (event_type === 'CIRCUIT_BREAKER') {
      state.setCircuitBreaker(true, {
        reason: (data.error as string) || 'Circuit breaker tripped by sequence engine',
        timestamp: new Date().toISOString(),
      })
    } else if (event_type === 'ROLLBACK_TRIGGERED') {
      state.setCircuitBreaker(true, {
        reason: (data.reason as string) || 'Rollback triggered',
        timestamp: new Date().toISOString(),
      })
    }
  },

  addOrderState: (order) =>
    set((state) => {
      const idx = state.orders.findIndex(
        (o) => o.order_id === order.order_id || o.leg_id === order.leg_id
      )
      if (idx >= 0) {
        const copy = [...state.orders]
        copy[idx] = order
        return { orders: copy }
      }
      return { orders: [order, ...state.orders.slice(0, 99)] }
    }),

  addSequence: (seq) =>
    set((state) => {
      const idx = state.sequences.findIndex(
        (s) => s.sequence_id === seq.sequence_id
      )
      if (idx >= 0) {
        const copy = [...state.sequences]
        copy[idx] = seq
        return { sequences: copy }
      }
      return { sequences: [seq, ...state.sequences.slice(0, 49)] }
    }),

  updatePositionsFromBroker: (positions) =>
    set((state) => {
      if (!positions || positions.length === 0) return state
      // Sync positions into strategies if needed
      return state
    }),

  queueSignal: (signal) =>
    set((state) => ({
      queuedSignals: [signal, ...state.queuedSignals],
    })),

  approveSignal: (signalId) => {
    const signal = get().queuedSignals.find((s) => s.signal_id === signalId)
    set((state) => ({
      queuedSignals: state.queuedSignals.filter((s) => s.signal_id !== signalId),
    }))
    return signal
  },

  rejectSignal: (signalId) =>
    set((state) => ({
      queuedSignals: state.queuedSignals.filter((s) => s.signal_id !== signalId),
    })),

  squareOffAll: () =>
    set((state) => ({
      activeStrategies: state.activeStrategies.map((s) => ({
        ...s,
        status: 'Exited',
        updatedAt: new Date().toISOString(),
      })),
      utilizedMargin: 0,
      availableFunds: state.totalFunds + state.totalDayMtm,
    })),

  resetCircuitBreakerState: () =>
    set({
      circuitBreakerActive: false,
      circuitBreakerDetails: null,
    }),

  saveBrokerCredentials: (creds) =>
    set((state) => ({
      brokerCredentials: { ...state.brokerCredentials, ...creds },
    })),
}))
