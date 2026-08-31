// frontend/src/types/news.ts
/**
 * TypeScript interfaces for the Market News feature.
 */

export type MarketImpact = 'HIGH' | 'MEDIUM' | 'LOW'

export interface NewsSourceReport {
  source: string
  title: string
  url: string
  published_at: string
}

export interface MarketImpactInfo {
  impact: MarketImpact
  label: string
  badge_color: 'rose' | 'amber' | 'slate'
}

export interface NewsArticle {
  id: string
  title: string
  summary: string
  source: string
  source_url: string
  image_url?: string
  published_at: string
  category: string
  country: string
  symbols: string[]
  sectors: string[]
  sources_count: number
  sources: NewsSourceReport[]
  market_impact: MarketImpact
  market_impact_label: string
  market_impact_info: MarketImpactInfo
  trending_score: number
  is_breaking?: boolean
}

export interface NewsFeedResponse {
  status: string
  page: number
  page_size: number
  total_count: number
  total_pages: number
  articles: NewsArticle[]
  breaking_news: NewsArticle[]
  trending_news: NewsArticle[]
  last_updated: string
}

export interface SymbolNewsResponse {
  status: string
  symbol: string
  count: number
  articles: NewsArticle[]
  last_updated: string
}

export interface SearchNewsResponse {
  status: string
  query: string
  count: number
  articles: NewsArticle[]
  last_updated: string
}

export interface AiSummaryResponse {
  status: string
  article_id: string
  ai_summary: string
  disclaimer: string
}

export type NewsTab =
  | 'All'
  | 'Trending'
  | 'Breaking'
  | 'India'
  | 'Global'
  | 'Stocks'
  | 'Indices'
  | 'Sectors'
  | 'Commodities'
  | 'Economy'

export type NewsTimeframe = 'all' | '15m' | '1h' | 'today'

export type NewsImpactFilter = 'all' | 'high' | 'medium' | 'low'
