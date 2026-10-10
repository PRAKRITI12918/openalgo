/**
 * REST API client for Phase 2 FastAPI Execution Engine.
 * Endpoints for signal ingestion, order tracking, positions, funds, and circuit breaker resets.
 */

import axios from 'axios'
import type {
  OrderExecutionSequence,
  PositionStateModel,
  StrategySignalPayload,
  SyntheticTickPayload,
} from '@/types/execution'

// Configurable FastAPI backend URL with localhost fallback
const API_BASE =
  import.meta.env.VITE_EXECUTION_API_URL || 'http://localhost:8000'

export const executionAxios = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
})

export interface IngestSignalResponse {
  status: 'COMPLETED' | 'QUEUED'
  sequence_id?: string
  signal_id: string
  correlation_id: string
  execution_status?: string
  completed_legs?: number
  total_legs?: number
  message?: string
  sequence?: OrderExecutionSequence
}

export interface FundsResponse {
  status: string
  total_funds: number
  available_funds: number
  utilized_margin: number
  currency: string
}

export interface HealthResponse {
  status: 'healthy' | 'degraded'
  broker_mode: string
  broker_connected: boolean
  environment: string
}

export const executionApi = {
  /** Ingest trade signal directly to FastAPI engine (sync or async) */
  async ingestSignal(
    signal: StrategySignalPayload,
    sync = false
  ): Promise<IngestSignalResponse> {
    const res = await executionAxios.post<IngestSignalResponse>(
      `/api/v1/signals/ingest?sync=${sync}`,
      signal
    )
    return res.data
  },

  /** Query single sequence status */
  async getOrderSequence(sequenceId: string): Promise<OrderExecutionSequence> {
    const res = await executionAxios.get<OrderExecutionSequence>(
      `/api/v1/orders/${sequenceId}`
    )
    return res.data
  },

  /** Query all past execution sequences */
  async listOrderSequences(): Promise<OrderExecutionSequence[]> {
    const res = await executionAxios.get<OrderExecutionSequence[]>(
      '/api/v1/orders'
    )
    return res.data
  },

  /** Query active broker positions */
  async getPositions(): Promise<PositionStateModel[]> {
    const res = await executionAxios.get<PositionStateModel[]>(
      '/api/v1/positions'
    )
    return res.data
  },

  /** Query funds & margin utilization */
  async getFunds(): Promise<FundsResponse> {
    const res = await executionAxios.get<FundsResponse>('/api/v1/funds')
    return res.data
  },

  /** Reset circuit-breaker and clear broker failure state */
  async resetCircuitBreaker(): Promise<{ status: string; message: string }> {
    const res = await executionAxios.post<{ status: string; message: string }>(
      '/api/v1/circuit-breaker/reset'
    )
    return res.data
  },

  /** Trigger single synthetic tick */
  async triggerSyntheticTick(
    underlying = 'NIFTY'
  ): Promise<SyntheticTickPayload> {
    const res = await executionAxios.post<SyntheticTickPayload>(
      `/api/v1/ticks/single?underlying=${underlying}`
    )
    return res.data
  },

  /** Health check */
  async checkHealth(): Promise<HealthResponse> {
    const res = await executionAxios.get<HealthResponse>('/api/v1/health')
    return res.data
  },

  /** List connected broker accounts for authenticated user */
  async listAccounts(): Promise<import('@/types/execution').BrokerAccountDisplay[]> {
    const res = await executionAxios.get<import('@/types/execution').BrokerAccountDisplay[]>(
      '/api/v1/accounts'
    )
    return res.data
  },

  /** Get currently active broker account */
  async getActiveAccount(): Promise<import('@/types/execution').BrokerAccountDisplay | null> {
    const res = await executionAxios.get<import('@/types/execution').BrokerAccountDisplay | null>(
      '/api/v1/accounts/active'
    )
    return res.data
  },

  /** Switch active account (supports confirmation if open positions exist) */
  async activateAccount(
    accountId: string,
    confirm = false
  ): Promise<{
    status: string
    requires_confirmation?: boolean
    message: string
    active_account?: import('@/types/execution').BrokerAccountDisplay
    open_positions_count?: number
    open_positions?: any[]
  }> {
    const res = await executionAxios.post(
      `/api/v1/accounts/${accountId}/activate?confirm=${confirm}`
    )
    return res.data
  },

  /** Disconnect broker account */
  async disconnectAccount(
    accountId: string
  ): Promise<{ status: string; message: string; was_active: boolean }> {
    const res = await executionAxios.post(
      `/api/v1/accounts/${accountId}/disconnect`
    )
    return res.data
  },

  /** List pending trade signals awaiting manual approval */
  async getPendingSignals(statusFilter?: string): Promise<import('@/types/execution').PendingSignalSummary[]> {
    const url = statusFilter
      ? `/api/v1/signals/pending?status=${statusFilter}`
      : '/api/v1/signals/pending'
    const res = await executionAxios.get<import('@/types/execution').PendingSignalListResponse>(url)
    return res.data.signals || []
  },

  /** Approve pending trade signal */
  async approvePendingSignal(
    signalId: string,
    actor = 'dashboard-trader'
  ): Promise<any> {
    const res = await executionAxios.post(
      `/api/v1/signals/${signalId}/approve`,
      { actor }
    )
    return res.data
  },

  /** Reject pending trade signal */
  async rejectPendingSignal(
    signalId: string,
    reason = 'Rejected from trader dashboard',
    actor = 'dashboard-trader'
  ): Promise<any> {
    const res = await executionAxios.post(
      `/api/v1/signals/${signalId}/reject`,
      { reason, actor }
    )
    return res.data
  },

  /** Get signal execution progress and per-leg order status */
  async getSignalProgress(signalId: string): Promise<any> {
    const res = await executionAxios.get(
      `/api/v1/signals/${signalId}/progress`
    )
    return res.data
  },

  /** Emergency square-off: prepare two-step liquidation and receive single-use token */
  async prepareSquareOff(selectedAccountId?: string): Promise<{
    status: string
    confirmation_token: string
    expires_in_seconds: number
    account_id?: string
    account_label: string
    broker_name: string
    total_positions: number
    open_positions: any[]
    confirm_phrase: string
    audit_id: string
  }> {
    const res = await executionAxios.post('/api/v1/positions/square-off/prepare', {
      selected_account_id: selectedAccountId,
    })
    return res.data
  },

  /** Emergency square-off: execute liquidation with confirmation token */
  async executeSquareOff(
    confirmationToken: string,
    confirmPhrase: string,
    selectedAccountId?: string
  ): Promise<{
    status: string
    message: string
    square_off_id: string
    account_id?: string
    account_label: string
    total_positions: number
    filled_count: number
    partial_count: number
    failed_count: number
    results: any[]
    audit_id: string
  }> {
    const res = await executionAxios.post('/api/v1/positions/square-off/execute', {
      confirmation_token: confirmationToken,
      confirm_phrase: confirmPhrase,
      selected_account_id: selectedAccountId,
    })
    return res.data
  },

  /** Emergency square-off: query progress */
  async getSquareOffProgress(squareOffId: string): Promise<any> {
    const res = await executionAxios.get(
      `/api/v1/positions/square-off/${squareOffId}/progress`
    )
    return res.data
  },

  /** Emergency square-off: query audit trail */
  async getSquareOffAudit(accountId?: string): Promise<any[]> {
    const res = await executionAxios.get('/api/v1/positions/square-off/audit', {
      params: { account_id: accountId },
    })
    return res.data
  },

  /** Emergency square-off: liquidate all open positions for active account (direct) */
  async squareOffAllPositions(selectedAccountId?: string): Promise<{
    status: string
    message: string
    account_id?: string
    closed_count: number
    closed_positions?: any[]
    square_off_id?: string
    audit_id?: string
  }> {
    const res = await executionAxios.post<{
      status: string
      message: string
      account_id?: string
      closed_count: number
      closed_positions?: any[]
      square_off_id?: string
      audit_id?: string
    }>('/api/v1/positions/square-off-all', null, {
      params: { selected_account_id: selectedAccountId },
    })
    return res.data
  },
}
