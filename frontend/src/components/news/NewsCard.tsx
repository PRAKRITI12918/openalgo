// frontend/src/components/news/NewsCard.tsx
/**
 * High-density trader news card with multi-source cluster expansion and impact badges.
 */

import { useState } from 'react'
import {
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Flame,
  Layers,
  Sparkles,
  Zap,
} from 'lucide-react'
import type { NewsArticle } from '@/types/news'
import { cn } from '@/lib/utils'

interface NewsCardProps {
  article: NewsArticle
  onSelect?: (article: NewsArticle) => void
  onSymbolClick?: (symbol: string) => void
  onAiSummaryClick?: (article: NewsArticle) => void
  compact?: boolean
}

export function formatRelativeTime(isoString: string): string {
  if (!isoString) return 'Just now'
  try {
    const pub = new Date(isoString).getTime()
    const now = Date.now()
    const diffSec = Math.max(0, Math.floor((now - pub) / 1000))

    if (diffSec < 60) return 'Just now'
    const diffMin = Math.floor(diffSec / 60)
    if (diffMin < 60) return `${diffMin}m ago`
    const diffHours = Math.floor(diffMin / 60)
    if (diffHours < 24) return `${diffHours}h ago`
    const diffDays = Math.floor(diffHours / 24)
    return `${diffDays}d ago`
  } catch {
    return 'Recently'
  }
}

export function NewsCard({
  article,
  onSelect,
  onSymbolClick,
  onAiSummaryClick,
  compact = false,
}: NewsCardProps) {
  const [expandedCluster, setExpandedCluster] = useState(false)

  const impactColor =
    article.market_impact === 'HIGH'
      ? 'text-rose-400 bg-rose-950/40 border-rose-800/60'
      : article.market_impact === 'MEDIUM'
        ? 'text-amber-400 bg-amber-950/40 border-amber-800/60'
        : 'text-muted-foreground bg-secondary/60 border-border/50'

  return (
    <div
      className={cn(
        'group relative flex flex-col justify-between rounded-lg border border-border/60 bg-card/60 p-3.5 backdrop-blur-sm transition-all duration-150 hover:border-border hover:bg-card/90 hover:shadow-md',
        article.is_breaking && 'border-rose-700/50 bg-rose-950/10'
      )}
    >
      {/* Top Metadata Header */}
      <div>
        <div className="flex flex-wrap items-center justify-between gap-1.5 pb-1.5 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="font-semibold text-foreground/90">{article.source}</span>
            <span className="text-muted-foreground/60">•</span>
            <span className="text-muted-foreground">{formatRelativeTime(article.published_at)}</span>
          </div>

          <div className="flex items-center gap-1.5">
            {/* Breaking Badge */}
            {article.is_breaking && (
              <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-rose-300 bg-rose-900/60 border border-rose-700/50 animate-pulse">
                <Zap className="h-3 w-3" /> Breaking
              </span>
            )}

            {/* Trending Score Badge */}
            {article.trending_score > 120 && (
              <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold text-amber-300 bg-amber-950/50 border border-amber-800/50">
                <Flame className="h-3 w-3" /> Trending
              </span>
            )}

            {/* Potential Market Impact Badge */}
            <span
              className={cn(
                'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
                impactColor
              )}
              title="Classified Potential Market Impact based on event type"
            >
              {article.market_impact_label}
            </span>
          </div>
        </div>

        {/* Headline */}
        <h3
          onClick={() => onSelect?.(article)}
          className={cn(
            'cursor-pointer text-sm font-semibold leading-snug text-foreground transition-colors group-hover:text-primary',
            compact ? 'line-clamp-2' : 'line-clamp-3'
          )}
        >
          {article.title}
        </h3>

        {/* Short Summary (if not super compact) */}
        {!compact && article.summary && (
          <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
            {article.summary}
          </p>
        )}
      </div>

      {/* Footer Tags & Controls */}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border/40 pt-2 text-xs">
        {/* Symbol Pills & Sectors */}
        <div className="flex flex-wrap items-center gap-1">
          {article.symbols?.map((sym) => (
            <button
              key={sym}
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onSymbolClick?.(sym)
              }}
              className="inline-flex items-center rounded bg-secondary/80 px-1.5 py-0.5 text-[11px] font-semibold text-foreground/90 transition-colors hover:bg-primary/20 hover:text-primary border border-border/50"
            >
              {sym}
            </button>
          ))}

          {article.sectors?.slice(0, 2).map((sec) => (
            <span
              key={sec}
              className="text-[10px] text-muted-foreground/80 bg-muted/40 px-1.5 py-0.5 rounded border border-border/30"
            >
              {sec}
            </span>
          ))}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          {/* Multi-Source Cluster Dropdown Trigger */}
          {article.sources_count > 1 && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setExpandedCluster(!expandedCluster)
              }}
              className="inline-flex items-center gap-1 rounded bg-secondary/60 px-1.5 py-0.5 text-[10px] font-medium text-foreground/80 hover:bg-secondary border border-border/50"
              title="Grouped duplicate reports covering this exact event"
            >
              <Layers className="h-3 w-3 text-muted-foreground" />
              {article.sources_count} sources
              {expandedCluster ? (
                <ChevronUp className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
            </button>
          )}

          {/* AI Takeaway Button */}
          {onAiSummaryClick && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onAiSummaryClick(article)
              }}
              className="inline-flex items-center gap-1 rounded bg-purple-950/40 px-1.5 py-0.5 text-[10px] font-semibold text-purple-300 hover:bg-purple-900/60 border border-purple-800/50 transition-colors"
              title="Generate 3-Bullet Trader AI Summary"
            >
              <Sparkles className="h-3 w-3 text-purple-400" />
              AI Summary
            </button>
          )}

          {/* Read Publisher Link */}
          {article.source_url && article.source_url !== '#' && (
            <a
              href={article.source_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center text-muted-foreground hover:text-foreground"
              title="Open full article on publisher site"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
      </div>

      {/* Expanded Multi-Source Cluster List */}
      {expandedCluster && article.sources?.length > 1 && (
        <div className="mt-2.5 rounded border border-border/50 bg-background/80 p-2 text-xs space-y-1.5 animate-in fade-in-50">
          <div className="text-[11px] font-semibold text-muted-foreground">
            All Reporting Sources ({article.sources.length}):
          </div>
          {article.sources.map((src, i) => (
            <div
              key={i}
              className="flex items-center justify-between gap-2 border-b border-border/30 pb-1 last:border-0 last:pb-0"
            >
              <div className="flex items-center gap-1.5 truncate">
                <span className="font-medium text-foreground/90">{src.source}:</span>
                <span className="truncate text-muted-foreground">{src.title}</span>
              </div>
              <a
                href={src.url}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 text-muted-foreground hover:text-primary"
              >
                <ExternalLink className="h-3 w-3" />
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
