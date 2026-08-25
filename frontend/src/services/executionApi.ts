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
}
