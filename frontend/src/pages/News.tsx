// frontend/src/pages/News.tsx
/**
 * Professional, real-time Market News page with multi-source clustering,
 * trending ranking, market impact classification, and watchlist intelligence.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  Clock,
  Filter,
  Flame,
  Globe,
  Layers,
  Newspaper,
  Radio,
  RefreshCw,
  Search,
  Sparkles,
  TrendingUp,
  X,
  Zap,
} from 'lucide-react'
import type {
  NewsArticle,
  NewsImpactFilter,
  NewsTab,
  NewsTimeframe,
} from '@/types/news'
import { fetchAiSummary, fetchNewsFeed, searchMarketNews } from '@/api/news'
import { NewsCard, formatRelativeTime } from '@/components/news/NewsCard'
import { NewsDetailModal } from '@/components/news/NewsDetailModal'
import { cn } from '@/lib/utils'

const TABS: { id: NewsTab; label: string }[] = [
  { id: 'All', label: 'All' },
  { id: 'Trending', label: 'Trending' },
  { id: 'Breaking', label: 'Breaking' },
  { id: 'India', label: 'India' },
  { id: 'Global', label: 'Global' },
  { id: 'Stocks', label: 'Stocks' },
  { id: 'Indices', label: 'Indices' },
  { id: 'Sectors', label: 'Sectors' },
  { id: 'Commodities', label: 'Commodities' },
  { id: 'Economy', label: 'Economy' },
]

export default function News() {
  const [activeTab, setActiveTab] = useState<NewsTab>('All')
  const [timeframe, setTimeframe] = useState<NewsTimeframe>('all')
  const [impactFilter, setImpactFilter] = useState<NewsImpactFilter>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')

  const [articles, setArticles] = useState<NewsArticle[]>([])
  const [breakingNews, setBreakingNews] = useState<NewsArticle[]>([])
  const [trendingNews, setTrendingNews] = useState<NewsArticle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdatedSec, setLastUpdatedSec] = useState(0)

  const [selectedArticle, setSelectedArticle] = useState<NewsArticle | null>(null)
  const [aiModalArticle, setAiModalArticle] = useState<NewsArticle | null>(null)

  // Debounce search query
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedQuery(searchQuery.trim())
    }, 350)
    return () => clearTimeout(handler)
  }, [searchQuery])

  // Load news feed from server
  const loadNews = useCallback(async (isSilent = false) => {
    try {
      if (!isSilent) setLoading(true)
      setError(null)

      if (debouncedQuery) {
        const res = await searchMarketNews(debouncedQuery)
        setArticles(res.articles || [])
      } else {
        const res = await fetchNewsFeed({
          tab: activeTab,
          timeframe,
          impact: impactFilter,
        })
        setArticles(res.articles || [])
        setBreakingNews(res.breaking_news || [])
        setTrendingNews(res.trending_news || [])
      }
      setLastUpdatedSec(0)
    } catch (e: any) {
      console.error('Failed to load news:', e)
      setError(e?.message || 'News temporarily unavailable. Retrying...')
    } finally {
      if (!isSilent) setLoading(false)
    }
  }, [activeTab, timeframe, impactFilter, debouncedQuery])

  // Initial load and filter change
  useEffect(() => {
    loadNews()
  }, [loadNews])

  // Auto-refresh interval (every 30 seconds)
  useEffect(() => {
    const timer = setInterval(() => {
      loadNews(true)
    }, 30000)
    return () => clearInterval(timer)
  }, [loadNews])

  // Live timer tick
  useEffect(() => {
    const tick = setInterval(() => {
      setLastUpdatedSec((prev) => prev + 1)
    }, 1000)
    return () => clearInterval(tick)
  }, [])

  const handleSymbolFilter = (symbol: string) => {
    setSearchQuery(symbol)
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="container-fluid px-4">
        {/* Canonical Page Top Header */}
        <div className="page-header d-flex justify-content-between align-items-start px-4 py-3 mb-4">
          <div className="page-header-text">
            <h2 className="page-title d-flex align-items-center">
              Market News
              <span className="badge bg-success-subtle text-success ms-2">Live Feed</span>
            </h2>
            <p className="page-subtitle text-muted mb-0">
              Real-time market intelligence, multi-source event clusters, and algorithmic trending ranking
            </p>
          </div>

          {/* Top Actions: Search & Refresh */}
          <div className="page-header-actions d-flex align-items-center gap-2">
            <div className="relative">
              <input
                type="text"
                id="oa-news-search-input"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search news, stocks, RBI, Fed..."
                className="form-control-sm"
                style={{ width: '240px' }}
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2.5 top-2.5 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            <button
              type="button"
              id="oa-news-refresh-btn"
              onClick={() => loadNews()}
              disabled={loading}
              className="btn btn-outline-secondary btn-page-action"
              title="Refresh News"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Filter Pill Row (Sitting below .page-header with px-4 pb-3 and no top margin collision) */}
        <div
          className="d-flex flex-wrap items-center justify-between gap-3 px-4 pb-3"
          id="oa-news-tabs-bar"
          style={{ borderBottom: '1px solid var(--bs-border-color, #27272a)', marginTop: 0 }}
        >
          {/* Horizontal Scrollable Tabs */}
          <div className="flex overflow-x-auto no-scrollbar gap-1.5 py-0.5">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => {
                  setActiveTab(tab.id)
                  setSearchQuery('')
                }}
                className={cn(
                  'rounded-md px-3 py-1 text-xs font-semibold whitespace-nowrap transition-all',
                  activeTab === tab.id
                    ? 'bg-primary text-primary-foreground shadow-sm'
                    : 'text-muted-foreground hover:bg-secondary/60 hover:text-foreground'
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Time & Impact Filters */}
          <div className="flex items-center gap-2 text-xs">
            {/* Timeframe Dropdown */}
            <div className="flex items-center gap-1">
              <Clock className="h-3.5 w-3.5 text-muted-foreground" />
              <select
                value={timeframe}
                onChange={(e) => setTimeframe(e.target.value as NewsTimeframe)}
                className="rounded border border-border/60 bg-card/80 px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="all">All Times</option>
                <option value="15m">Last 15 min</option>
                <option value="1h">Last 1 hour</option>
                <option value="today">Today</option>
              </select>
            </div>

            {/* Impact Filter Dropdown */}
            <div className="flex items-center gap-1">
              <Filter className="h-3.5 w-3.5 text-muted-foreground" />
              <select
                value={impactFilter}
                onChange={(e) => setImpactFilter(e.target.value as NewsImpactFilter)}
                className="rounded border border-border/60 bg-card/80 px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="all">All Impacts</option>
                <option value="high">High Impact Only</option>
                <option value="medium">Medium Impact Only</option>
                <option value="low">Low Impact Only</option>
              </select>
            </div>
          </div>
        </div>

        {/* Breaking News Alert Banner (if active) */}
        {breakingNews.length > 0 && !debouncedQuery && (
          <div className="mt-4 rounded-lg border border-rose-800/60 bg-rose-950/20 p-3 text-xs backdrop-blur-sm animate-in fade-in-50">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="flex h-2 w-2 rounded-full bg-rose-500 animate-ping" />
                <span className="font-bold uppercase tracking-wider text-rose-400">
                  Macro Alert:
                </span>
                <span
                  onClick={() => setSelectedArticle(breakingNews[0])}
                  className="cursor-pointer font-semibold text-foreground hover:underline"
                >
                  {breakingNews[0].title}
                </span>
              </div>
              <span className="text-[11px] text-muted-foreground shrink-0">
                {formatRelativeTime(breakingNews[0].published_at)}
              </span>
            </div>
          </div>
        )}

        {/* Error Alert (Graceful Fallback) */}
        {error && (
          <div className="mt-4 flex items-center gap-2 rounded-md border border-amber-800/60 bg-amber-950/20 p-3 text-xs text-amber-300">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Two-Column Grid Layout: Main Feed (Left) & Market Movers / Watchlist (Right) */}
        <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-12">
          {/* Main News Feed (8 Columns on Desktop) */}
          <div className="space-y-3.5 lg:col-span-8">
            {loading && !articles.length ? (
              // Loading Skeleton
              <div className="space-y-3">
                {[1, 2, 3, 4].map((i) => (
                  <div
                    key={i}
                    className="h-28 rounded-lg border border-border/40 bg-card/40 animate-pulse p-4"
                  />
                ))}
              </div>
            ) : articles.length > 0 ? (
              articles.map((article) => (
                <NewsCard
                  key={article.id}
                  article={article}
                  onSelect={(a) => setSelectedArticle(a)}
                  onSymbolClick={handleSymbolFilter}
                  onAiSummaryClick={(a) => setSelectedArticle(a)}
                />
              ))
            ) : (
              <div className="rounded-lg border border-border/50 bg-card/40 p-12 text-center text-xs text-muted-foreground">
                <Newspaper className="mx-auto h-8 w-8 text-muted-foreground/50 mb-2" />
                <p className="font-semibold text-foreground">No market news found</p>
                <p className="mt-1">Try switching tabs or clearing search filters.</p>
              </div>
            )}
          </div>

          {/* Right Sidebar: Trending & Watchlist News (4 Columns on Desktop) */}
          <div className="space-y-4 lg:col-span-4">
            {/* Top Trending Market Movers */}
            <div className="rounded-lg border border-border/70 bg-card/60 p-4 backdrop-blur-sm">
              <div className="flex items-center gap-2 border-b border-border/40 pb-2.5">
                <Flame className="h-4 w-4 text-amber-400" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-foreground">
                  Trending Market Movers
                </h2>
              </div>

              <div className="mt-3 space-y-3">
                {trendingNews.map((tArt, idx) => (
                  <div
                    key={tArt.id}
                    onClick={() => setSelectedArticle(tArt)}
                    className="group cursor-pointer border-b border-border/30 pb-2.5 last:border-0 last:pb-0"
                  >
                    <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                      <span className="font-semibold text-primary/90">#{idx + 1} {tArt.source}</span>
                      <span>{formatRelativeTime(tArt.published_at)}</span>
                    </div>
                    <p className="mt-1 text-xs font-semibold leading-snug text-foreground/90 group-hover:text-primary transition-colors line-clamp-2">
                      {tArt.title}
                    </p>
                    <div className="mt-1 flex items-center gap-1.5">
                      <span className="text-[10px] text-amber-300 bg-amber-950/60 px-1.5 py-0.2 rounded border border-amber-800/40">
                        Score {tArt.trending_score}
                      </span>
                      {tArt.symbols?.slice(0, 2).map((s) => (
                        <span key={s} className="text-[10px] text-muted-foreground bg-secondary px-1 rounded">
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* My Market / Key Watchlist Section */}
            <div className="rounded-lg border border-border/70 bg-card/60 p-4 backdrop-blur-sm">
              <div className="flex items-center gap-2 border-b border-border/40 pb-2.5">
                <TrendingUp className="h-4 w-4 text-primary" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-foreground">
                  My Market & Watchlist
                </h2>
              </div>
              <p className="mt-2 text-[11px] text-muted-foreground">
                Quickly filter high-impact catalysts for core index and stock heavyweights:
              </p>

              <div className="mt-3 flex flex-wrap gap-1.5">
                {['NIFTY', 'BANKNIFTY', 'SENSEX', 'RELIANCE', 'HDFCBANK', 'TCS', 'BHEL', 'CRUDEOIL', 'GOLD'].map(
                  (sym) => (
                    <button
                      key={sym}
                      type="button"
                      onClick={() => handleSymbolFilter(sym)}
                      className="rounded bg-secondary/80 px-2 py-1 text-xs font-semibold text-foreground hover:bg-primary/20 hover:text-primary border border-border/60 transition-colors"
                    >
                      {sym}
                    </button>
                  )
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Article Detail & AI Modal */}
      <NewsDetailModal
        article={selectedArticle}
        open={Boolean(selectedArticle)}
        onOpenChange={(v) => !v && setSelectedArticle(null)}
        onSymbolClick={handleSymbolFilter}
      />
    </div>
  )
}
