// frontend/src/api/news.ts
/**
 * API client functions for the Market News feature.
 */

import axios from 'axios'
import type {
  AiSummaryResponse,
  NewsArticle,
  NewsFeedResponse,
  NewsImpactFilter,
  NewsTab,
  NewsTimeframe,
  SearchNewsResponse,
  SymbolNewsResponse,
} from '@/types/news'

export async function fetchNewsFeed(params: {
  tab?: NewsTab
  category?: string
  timeframe?: NewsTimeframe
  impact?: NewsImpactFilter
  page?: number
  pageSize?: number
}): Promise<NewsFeedResponse> {
  const {
    tab = 'All',
    category = 'All',
    timeframe = 'all',
    impact = 'all',
    page = 1,
    pageSize = 25,
  } = params

  const response = await axios.get<NewsFeedResponse>('/api/news/feed', {
    params: {
      tab,
      category,
      timeframe,
      impact,
      page,
      page_size: pageSize,
    },
    withCredentials: true,
  })
  return response.data
}

export async function fetchSymbolNews(symbol: string, limit = 15): Promise<SymbolNewsResponse> {
  const response = await axios.get<SymbolNewsResponse>(`/api/news/symbol/${encodeURIComponent(symbol)}`, {
    params: { limit },
    withCredentials: true,
  })
  return response.data
}

export async function searchMarketNews(query: string, limit = 30): Promise<SearchNewsResponse> {
  const response = await axios.get<SearchNewsResponse>('/api/news/search', {
    params: { q: query, limit },
    withCredentials: true,
  })
  return response.data
}

export async function fetchAiSummary(article: NewsArticle): Promise<AiSummaryResponse> {
  const response = await axios.post<AiSummaryResponse>(
    '/api/news/ai-summary',
    {
      id: article.id,
      title: article.title,
      summary: article.summary,
      symbols: article.symbols,
      market_impact: article.market_impact,
    },
    {
      headers: { 'Content-Type': 'application/json' },
      withCredentials: true,
    }
  )
  return response.data
}
