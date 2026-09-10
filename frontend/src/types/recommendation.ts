/**
 * Types for the Recommendations feature.
 * Decoupled data contracts representing multi-leg option strategy recommendations.
 */

export interface RecommendationPosition {
  side: 'BUY' | 'SELL'
  instrument: string
  expiry: string
  strike: number
  optionType: 'CE' | 'PE'
  quantity: number
  price: number
  ltp?: number
}

export interface RecommendationCardData {
  symbol: string
  strategy: string
  tradeId: string
  status: 'BEARISH' | 'BULLISH' | 'NEUTRAL'
  timestamp: string
  currentPrice: number
  maxTarget: number
  maxLoss: number
  capitalRequired: number
  statusMessage: string
  positions: RecommendationPosition[]
  source: 'positions' | 'strategy_portfolio' | 'signal'
  notes?: string
}
