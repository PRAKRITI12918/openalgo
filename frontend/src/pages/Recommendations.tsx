import React, { useCallback, useEffect, useState } from 'react'
import {
  AlertCircle,
  Clock,
  Layers,
  Loader2,
  RefreshCw,
  Sparkles,
  TrendingUp,
} from 'lucide-react'
import { strategyPortfolioApi } from '@/api/strategy-portfolio'
import { tradingApi } from '@/api/trading'
import { RecommendationsCard } from '@/components/recommendations/RecommendationsCard'
import { mapToRecommendations } from '@/lib/recommendationMapper'
import { useAuthStore } from '@/stores/authStore'
import type { RecommendationCardData } from '@/types/recommendation'
import '@/styles/recommendations.css'

export default function Recommendations() {
  const { apiKey } = useAuthStore()
  const [recommendations, setRecommendations] = useState<RecommendationCardData[]>([])
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<string>('')

  const fetchData = useCallback(
    async (showRefreshSpinner = false) => {
      if (showRefreshSpinner) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        // Parallel queries to existing OpenAlgo APIs
        const [positionsRes, tradesRes, ordersRes, fundsRes, portfoliosRes] =
          await Promise.allSettled([
            apiKey ? tradingApi.getPositions(apiKey) : Promise.resolve(null),
            apiKey ? tradingApi.getTrades(apiKey) : Promise.resolve(null),
            apiKey ? tradingApi.getOrders(apiKey) : Promise.resolve(null),
            apiKey ? tradingApi.getFunds(apiKey) : Promise.resolve(null),
            strategyPortfolioApi.list().catch(() => []),
          ])

        const positions =
          positionsRes.status === 'fulfilled' && positionsRes.value?.status === 'success'
            ? positionsRes.value.data || []
            : []

        const trades =
          tradesRes.status === 'fulfilled' && tradesRes.value?.status === 'success'
            ? tradesRes.value.data || []
            : []

        const orders =
          ordersRes.status === 'fulfilled' && ordersRes.value?.status === 'success'
            ? ordersRes.value.data?.orders || []
            : []

        const funds =
          fundsRes.status === 'fulfilled' && fundsRes.value?.status === 'success'
            ? fundsRes.value.data
            : null

        const portfolios =
          portfoliosRes.status === 'fulfilled' ? portfoliosRes.value || [] : []

        // Extract underlyings to optionally query quotes
        const underlyings = new Set<string>()
        for (const p of positions) {
          const u = p.symbol.split(/[0-9]/)[0]
          if (u) underlyings.add(u)
        }
        for (const port of portfolios) {
          if (port.underlying) underlyings.add(port.underlying)
        }

        const quotesMap: Record<string, any> = {}
        if (apiKey && underlyings.size > 0) {
          const quotesPromises = Array.from(underlyings).map(async (sym) => {
            try {
              const exchange = sym === 'SENSEX' || sym === 'BANKEX' ? 'BSE_INDEX' : 'NSE_INDEX'
              const q = await tradingApi.getQuotes(apiKey, sym, exchange)
              if (q.status === 'success' && q.data) {
                quotesMap[sym] = q.data
              }
            } catch {}
          })
          await Promise.allSettled(quotesPromises)
        }

        // Map existing raw data into RecommendationCardData contracts
        const mapped = mapToRecommendations({
          positions,
          trades,
          orders,
          funds,
          portfolios,
          underlyingQuotes: quotesMap,
        })

        setRecommendations(mapped)
        setLastUpdated(
          new Date().toLocaleTimeString('en-IN', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
          })
        )
      } catch (err: any) {
        setError(err?.message || 'Failed to load recommendations data')
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [apiKey]
  )

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return (
    <div className="container mx-auto px-4 py-6">
      {/* Standard Page Header */}
      <div className="page-header d-flex justify-content-between align-items-start px-4 py-3 mb-4">
        <div className="page-header-text">
          <h2 className="page-title">Recommendations</h2>
          <p className="page-subtitle text-muted mb-0">
            AI-generated trade ideas and options strategies
          </p>
        </div>
        <div className="page-header-actions d-flex align-items-center gap-2">
          <button
            type="button"
            className="btn btn-outline-secondary btn-page-action"
            id="refreshRecommendations"
            onClick={() => fetchData(true)}
            disabled={isLoading || isRefreshing}
          >
            <RefreshCw
              className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`}
            />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      <div className="recommendations-page" style={{ padding: 0 }}>

      {/* Loading State */}
      {isLoading && (
        <div className="loading-indicator">
          <Loader2 className="icon-small spin-loader text-accent" />
          <span>Analyzing positions and strategy recommendations...</span>
        </div>
      )}

      {/* Error State */}
      {!isLoading && error && (
        <div className="error-state-box">
          <AlertCircle className="empty-state-icon" style={{ color: '#f87171' }} />
          <h3 className="empty-state-title">Unable to Load Recommendations</h3>
          <p className="empty-state-desc">{error}</p>
          <button
            type="button"
            className="btn-refresh-pill"
            style={{ marginTop: 8 }}
            onClick={() => fetchData(true)}
          >
            <RefreshCw className="icon-tiny" />
            <span>Retry</span>
          </button>
        </div>
      )}

      {/* Clean Empty State */}
      {!isLoading && !error && recommendations.length === 0 && (
        <div className="empty-state-box">
          <TrendingUp className="empty-state-icon" />
          <h3 className="empty-state-title">No Active Recommendations</h3>
          <p className="empty-state-desc">
            Multi-leg options recommendations will appear here automatically as active positions are initiated or when strategies are configured in the Strategy Builder.
          </p>
          <button
            type="button"
            className="btn-refresh-pill"
            style={{ marginTop: 8 }}
            onClick={() => fetchData(true)}
          >
            <RefreshCw className="icon-tiny" />
            <span>Check Again</span>
          </button>
        </div>
      )}

      {/* Cards Render */}
      {!isLoading && !error && recommendations.length > 0 && (
        <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {recommendations.map((rec, index) => (
            <RecommendationsCard key={`${rec.tradeId}-${index}`} data={rec} />
          ))}
        </div>
      )}
      </div>
    </div>
  )
}

