/**
 * Real-time Execution Engine & Trading Dashboard Zustand Store.
 * Centralizes MTM tracking, tick feeds, order states, active strategies,
 * multi-account broker state, positions, and circuit-breaker status.
 *
 * HARD CONSTRAINTS ENFORCED:
 * - NO fake/mock seed data in production mode: Starts with honest empty states.
 * - Multi-account awareness: Scoped to active account; refreshed upon account switch.
 * - Genuine mock flag: isMockMode is driven by backend /api/v1/health.
 */

import { create } from 'zustand'
import type {
  BrokerAccountDisplay,
  BrokerConnectionStatus,
  BrokerCredentialsConfig,
  ExecutionEventMessage,
  Greeks,
  LegExecutionState,
  OrderExecutionSequence,
  PendingSignalSummary,
  PositionStateModel,
  StrategySignalPayload,
  SyntheticTickPayload,
} from '@/types/execution'
import { executionApi } from '@/services/executionApi'

export interface ActiveStrategyCard {
  strategyId: string
  name: string
  type: string
  underlying: string
  status: 'RECEIVED' | 'VALIDATED' | 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED' | 'EXECUTING' | 'COMPLETED' | 'FAILED' | string
  netPnl: number
  pnlPercentage: number
  entrySpot?: number
  currentSpot?: number
  entryCreditDebit?: number
  greeks?: Greeks
  legs: {
    symbol: string
    action: 'BUY' | 'SELL'
    strike: number
    optionType: 'CE' | 'PE'
    quantity: number
    entryPrice: number
    ltp?: number
    isHedgeLeg: boolean
    status: string
  }[]
  createdAt: string
  updatedAt: string
}

export interface ExecutionStoreState {
  // Multi-Account & Broker Connection
  activeAccount: BrokerAccountDisplay | null
  connectedAccounts: BrokerAccountDisplay[]
  brokerStatus: BrokerConnectionStatus
  isMockMode: boolean
  isSwitchingAccount: boolean

  // WebSocket Live Connectivity
  wsMarketConnected: boolean
  wsExecutionsConnected: boolean
  circuitBreakerActive: boolean
  circuitBreakerDetails: { reason?: string; timestamp?: string } | null

  // Capital & Live MTM
  availableFunds: number
  utilizedMargin: number
  totalFunds: number
  totalDayMtm: number
  mtmHistory: { time: string; timestamp: number; mtm: number; spot: number }[]

  // Market Ticks
  ticks: Record<string, SyntheticTickPayload>
  tickDeltas: Record<string, 'up' | 'down' | 'neutral'>

  // Positions & Strategy Containers
  positions: PositionStateModel[]
  activeStrategies: ActiveStrategyCard[]

  // Real-time Orders & Executions
  orders: LegExecutionState[]
  sequences: OrderExecutionSequence[]

  // Pending Signals Queue (Awaiting manual trader authorization)
  pendingSignals: PendingSignalSummary[]
  queuedSignals: StrategySignalPayload[]

  // Section Loading & Error States
  loadingStates: Record<string, boolean>
  errorStates: Record<string, string | null>

  // Broker Credentials
  brokerCredentials: BrokerCredentialsConfig

  // Actions
  setActiveAccount: (account: BrokerAccountDisplay | null) => void
  setConnectedAccounts: (accounts: BrokerAccountDisplay[]) => void
  setBrokerStatus: (status: BrokerConnectionStatus) => void
  setIsMockMode: (isMock: boolean) => void
  setWsMarketConnected: (connected: boolean) => void
  setWsExecutionsConnected: (connected: boolean) => void
  setCircuitBreaker: (
    active: boolean,
    details?: { reason?: string; timestamp?: string } | null
  ) => void
  setLoading: (key: string, loading: boolean) => void
  setError: (key: string, error: string | null) => void

  updateFunds: (
    available: number,
    utilized: number,
    total?: number
  ) => void
  handleMarketTick: (tick: SyntheticTickPayload) => void
  handleExecutionEvent: (event: ExecutionEventMessage) => void
  addOrderState: (order: LegExecutionState) => void
  addSequence: (sequence: OrderExecutionSequence) => void
  setPositions: (positions: PositionStateModel[]) => void
  setPendingSignals: (signals: PendingSignalSummary[]) => void
  setOrders: (orders: LegExecutionState[]) => void

  // Account Operations
  switchAccount: (accountId: string, confirm?: boolean) => Promise<{ success: boolean; requires_confirmation?: boolean; message?: string; open_positions_count?: number }>
  refreshAllData: () => Promise<void>

  // Signal Approvals
  queueSignal: (signal: StrategySignalPayload) => void
  approveSignal: (signalId: string) => StrategySignalPayload | undefined
  rejectSignal: (signalId: string) => void
  isSquareOffInFlight: boolean
  prepareSquareOff: () => Promise<any>
  executeSquareOff: (token: string, confirmPhrase: string) => Promise<any>
  squareOffAll: () => Promise<{ success: boolean; message: string }>
  resetCircuitBreakerState: () => void
  saveBrokerCredentials: (creds: Partial<BrokerCredentialsConfig>) => void
}

const INITIAL_CREDENTIALS: BrokerCredentialsConfig = {
  broker: 'OpenAlgo',
  apiKey: '',
  apiSecret: '',
  clientId: '',
  totpSeed: '',
  isSandbox: true,
}

export const useExecutionStore = create<ExecutionStoreState>((set, get) => ({
  // Multi-Account initial state: honest empty states
  activeAccount: null,
  connectedAccounts: [],
  brokerStatus: 'DISCONNECTED',
  isMockMode: false,
  isSwitchingAccount: false,

  wsMarketConnected: false,
  wsExecutionsConnected: false,
  circuitBreakerActive: false,
  circuitBreakerDetails: null,

  // Financial metrics start at zero pending real fetch
  availableFunds: 0,
  utilizedMargin: 0,
  totalFunds: 0,
  totalDayMtm: 0,
  mtmHistory: [],

  ticks: {},
  tickDeltas: {},

  positions: [],
  activeStrategies: [],
  orders: [],
  sequences: [],
  pendingSignals: [],
  queuedSignals: [],

  loadingStates: {
    accounts: true,
    positions: true,
    orders: true,
    funds: true,
    signals: true,
  },
  errorStates: {
    accounts: null,
    positions: null,
    orders: null,
    funds: null,
    signals: null,
  },

  isSquareOffInFlight: false,
  brokerCredentials: INITIAL_CREDENTIALS,

  setActiveAccount: (account) =>
    set({
      activeAccount: account,
      brokerStatus: account ? account.status : 'DISCONNECTED',
    }),

  setConnectedAccounts: (accounts) => set({ connectedAccounts: accounts }),
  setBrokerStatus: (status) => set({ brokerStatus: status }),
  setIsMockMode: (isMock) => set({ isMockMode: isMock }),
  setWsMarketConnected: (connected) => set({ wsMarketConnected: connected }),
  setWsExecutionsConnected: (connected) => set({ wsExecutionsConnected: connected }),

  setCircuitBreaker: (active, details = null) =>
    set({
      circuitBreakerActive: active,
      circuitBreakerDetails: details,
    }),

  setLoading: (key, loading) =>
    set((state) => ({
      loadingStates: { ...state.loadingStates, [key]: loading },
    })),

  setError: (key, error) =>
    set((state) => ({
      errorStates: { ...state.errorStates, [key]: error },
    })),

  updateFunds: (available, utilized, total) =>
    set((state) => ({
      availableFunds: available,
      utilizedMargin: utilized,
      totalFunds: total !== undefined ? total : (available + utilized),
    })),

  setPositions: (positions) =>
    set((state) => {
      // Map positions into active strategy cards if applicable
      const totalUnrealized = positions.reduce((acc, p) => acc + (p.unrealized_pnl || 0), 0)
      const totalRealized = positions.reduce((acc, p) => acc + (p.realized_pnl || 0), 0)
      const totalPnl = totalUnrealized + totalRealized
      const roundedPnl = Math.round(totalPnl * 100) / 100

      const strategies: ActiveStrategyCard[] = positions.map((pos) => ({
        strategyId: pos.position_id,
        name: pos.strategy_name || 'Multi-Leg Position',
        type: 'SPREAD',
        underlying: pos.underlying || 'NIFTY',
        status: pos.is_active ? 'COMPLETED' : 'REJECTED',
        netPnl: pos.total_pnl || 0,
        pnlPercentage: pos.margin_utilized ? Math.round(((pos.total_pnl || 0) / pos.margin_utilized) * 10000) / 100 : 0,
        greeks: (pos.net_delta || pos.net_theta) ? {
          delta: pos.net_delta || 0,
          gamma: pos.net_gamma || 0,
          theta: pos.net_theta || 0,
          vega: pos.net_vega || 0,
          rho: 0,
          iv: 0,
        } : undefined,
        legs: (pos.legs || []).map((leg) => ({
          symbol: leg.symbol,
          action: leg.action,
          strike: leg.strike,
          optionType: leg.option_type || 'CE',
          quantity: leg.quantity,
          entryPrice: leg.price || 0,
          ltp: undefined,
          isHedgeLeg: leg.is_hedge_leg || false,
          status: 'COMPLETE',
        })),
        createdAt: pos.entry_time ? String(pos.entry_time) : new Date().toISOString(),
        updatedAt: pos.updated_at ? String(pos.updated_at) : new Date().toISOString(),
      }))

      // Record real cumulative MTM history points when positions exist
      let updatedMtmHistory = state.mtmHistory
      if (positions.length > 0) {
        const lastEntry = state.mtmHistory[state.mtmHistory.length - 1]
        const now = Date.now()
        if (!lastEntry || lastEntry.mtm !== roundedPnl || now - lastEntry.timestamp > 10000) {
          const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
          updatedMtmHistory = [
            ...state.mtmHistory.slice(-49),
            { time: nowStr, timestamp: now, mtm: roundedPnl, spot: 0 },
          ]
        }
      } else {
        updatedMtmHistory = []
      }

      return {
        positions,
        activeStrategies: strategies,
        totalDayMtm: roundedPnl,
        mtmHistory: updatedMtmHistory,
      }
    }),

  setPendingSignals: (signals) => set({ pendingSignals: signals }),
  setOrders: (orders) => set({ orders }),

  handleMarketTick: (tick) =>
    set((state) => {
      const prev = state.ticks[tick.symbol]
      let delta: 'up' | 'down' | 'neutral' = 'neutral'
      if (prev) {
        if (tick.ltp > prev.ltp) delta = 'up'
        else if (tick.ltp < prev.ltp) delta = 'down'
      }

      const newTicks = { ...state.ticks, [tick.symbol]: tick }
      const newDeltas = { ...state.tickDeltas, [tick.symbol]: delta }

      // Update spot on strategies if matching underlying
      const updatedStrategies = state.activeStrategies.map((strat) => {
        if (tick.symbol.includes(strat.underlying) || strat.underlying === tick.underlying) {
          return { ...strat, currentSpot: tick.spot_price || tick.ltp }
        }
        return strat
      })

      return {
        ticks: newTicks,
        tickDeltas: newDeltas,
        activeStrategies: updatedStrategies,
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
        reason: (data?.error as string) || 'Circuit breaker tripped by sequence engine',
        timestamp: new Date().toISOString(),
      })
    } else if (event_type === 'ROLLBACK_TRIGGERED') {
      state.setCircuitBreaker(true, {
        reason: (data?.reason as string) || 'Rollback triggered',
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

  // Multi-Account Switching Action
  switchAccount: async (accountId: string, confirm = false) => {
    set({ isSwitchingAccount: true })
    try {
      const res = await executionApi.activateAccount(accountId, confirm)
      if (res.requires_confirmation) {
        set({ isSwitchingAccount: false })
        return {
          success: false,
          requires_confirmation: true,
          message: res.message,
          open_positions_count: res.open_positions_count,
        }
      }

      if (res.active_account) {
        set({
          activeAccount: res.active_account,
          brokerStatus: res.active_account.status,
        })
      }

      // Refresh all account-scoped dashboard data immediately!
      await get().refreshAllData()
      set({ isSwitchingAccount: false })
      return { success: true, message: res.message }
    } catch (err: any) {
      set({ isSwitchingAccount: false })
      const errorMsg = err?.response?.data?.detail?.message || err?.response?.data?.detail || err.message || 'Failed to switch account'
      return { success: false, message: errorMsg }
    }
  },

  // Refresh All Dashboard Data
  refreshAllData: async () => {
    const { setLoading, setError } = get()
    
    // 1. Health & Mode Check
    try {
      const health = await executionApi.checkHealth()
      set({ isMockMode: health.broker_mode === 'MOCK' })
    } catch {
      set({ isMockMode: true })
    }

    // 2. Fetch Accounts
    setLoading('accounts', true)
    try {
      const [accounts, active] = await Promise.all([
        executionApi.listAccounts(),
        executionApi.getActiveAccount(),
      ])
      set({
        connectedAccounts: accounts,
        activeAccount: active,
        brokerStatus: active ? active.status : 'DISCONNECTED',
      })
      setError('accounts', null)
    } catch (err: any) {
      setError('accounts', err?.response?.data?.detail || err.message || 'Failed to load accounts')
    } finally {
      setLoading('accounts', false)
    }

    // 3. Fetch Positions & Funds
    setLoading('positions', true)
    setLoading('funds', true)
    try {
      const [positions, funds] = await Promise.all([
        executionApi.getPositions(),
        executionApi.getFunds(),
      ])
      get().setPositions(positions)
      get().updateFunds(funds.available_funds, funds.utilized_margin, funds.total_funds)
      setError('positions', null)
      setError('funds', null)
    } catch (err: any) {
      setError('positions', err?.response?.data?.detail || err.message || 'Failed to load positions')
    } finally {
      setLoading('positions', false)
      setLoading('funds', false)
    }

    // 4. Fetch Order History
    setLoading('orders', true)
    try {
      const sequences = await executionApi.listOrderSequences()
      set({ sequences })
      // Extract leg orders from sequences
      const allLegs: LegExecutionState[] = []
      sequences.forEach((seq) => {
        if (seq.leg_states) {
          allLegs.push(...seq.leg_states)
        }
      })
      set({ orders: allLegs })
      setError('orders', null)
    } catch (err: any) {
      setError('orders', err?.response?.data?.detail || err.message || 'Failed to load order sequences')
    } finally {
      setLoading('orders', false)
    }

    // 5. Fetch Pending Signals
    setLoading('signals', true)
    try {
      const pending = await executionApi.getPendingSignals()
      set({ pendingSignals: pending })
      setError('signals', null)
    } catch (err: any) {
      setError('signals', err?.response?.data?.detail || err.message || 'Failed to load pending signals')
    } finally {
      setLoading('signals', false)
    }
  },

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

  prepareSquareOff: async () => {
    const activeAcc = get().activeAccount
    return await executionApi.prepareSquareOff(activeAcc?.id)
  },

  executeSquareOff: async (token: string, confirmPhrase: string) => {
    const activeAcc = get().activeAccount
    set({ isSquareOffInFlight: true })
    try {
      const res = await executionApi.executeSquareOff(token, confirmPhrase, activeAcc?.id)
      await get().refreshAllData()
      return res
    } finally {
      set({ isSquareOffInFlight: false })
    }
  },

  squareOffAll: async () => {
    const activeAcc = get().activeAccount
    set({ isSquareOffInFlight: true })
    try {
      const res = await executionApi.squareOffAllPositions(activeAcc?.id)
      await get().refreshAllData()
      return { success: true, message: res.message }
    } catch (err: any) {
      const errorMsg =
        err?.response?.data?.detail?.message ||
        err?.response?.data?.detail ||
        err.message ||
        'Failed to square off positions'
      return { success: false, message: errorMsg }
    } finally {
      set({ isSquareOffInFlight: false })
    }
  },

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
