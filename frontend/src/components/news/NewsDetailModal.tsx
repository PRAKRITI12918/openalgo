// frontend/src/components/news/NewsDetailModal.tsx
/**
 * Detail modal for financial news articles with multi-source cluster view and AI summary.
 */

import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ExternalLink, Layers, Sparkles, X, Zap } from 'lucide-react'
import type { NewsArticle } from '@/types/news'
import { fetchAiSummary } from '@/api/news'
import { formatRelativeTime } from './NewsCard'
import { cn } from '@/lib/utils'

interface NewsDetailModalProps {
  article: NewsArticle | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSymbolClick?: (symbol: string) => void
}

export function NewsDetailModal({
  article,
  open,
  onOpenChange,
  onSymbolClick,
}: NewsDetailModalProps) {
  const [aiSummary, setAiSummary] = useState<string | null>(null)
  const [loadingAi, setLoadingAi] = useState(false)

  if (!article) return null

  const handleGenerateAi = async () => {
    try {
      setLoadingAi(true)
      const res = await fetchAiSummary(article)
      setAiSummary(res.ai_summary)
    } catch (e) {
      console.error('Failed to generate AI summary:', e)
      setAiSummary('Failed to generate summary. Please try again.')
    } finally {
      setLoadingAi(false)
    }
  }

  const impactColor =
    article.market_impact === 'HIGH'
      ? 'text-rose-400 bg-rose-950/40 border-rose-800/60'
      : article.market_impact === 'MEDIUM'
        ? 'text-amber-400 bg-amber-950/40 border-amber-800/60'
        : 'text-muted-foreground bg-secondary/60 border-border/50'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto border-border bg-card/95 backdrop-blur-md p-6 text-foreground">
        <DialogHeader className="space-y-2">
          {/* Metadata Row */}
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <div className="flex items-center gap-2">
              <span className="font-bold text-foreground">{article.source}</span>
              <span className="text-muted-foreground">•</span>
              <span className="text-muted-foreground">{formatRelativeTime(article.published_at)}</span>
            </div>

            <div className="flex items-center gap-1.5">
              {article.is_breaking && (
                <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold text-rose-300 bg-rose-950 border border-rose-800">
                  <Zap className="h-3 w-3" /> Breaking
                </span>
              )}
              <span
                className={cn(
                  'inline-flex items-center rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
                  impactColor
                )}
              >
                {article.market_impact_label}
              </span>
            </div>
          </div>

          <DialogTitle className="text-lg font-bold leading-snug text-foreground">
            {article.title}
          </DialogTitle>
        </DialogHeader>

        {/* Article Summary */}
        <div className="mt-4 space-y-4 text-sm leading-relaxed text-muted-foreground">
          <p>{article.summary}</p>

          {/* Related Instruments & Sectors */}
          <div className="flex flex-wrap items-center gap-1.5 border-y border-border/40 py-2.5">
            <span className="text-xs font-semibold text-foreground/80">Related:</span>
            {article.symbols?.map((sym) => (
              <button
                key={sym}
                type="button"
                onClick={() => {
                  onOpenChange(false)
                  onSymbolClick?.(sym)
                }}
                className="inline-flex items-center rounded bg-secondary px-2 py-0.5 text-xs font-semibold text-foreground transition-colors hover:bg-primary/20 hover:text-primary border border-border/60"
              >
                {sym}
              </button>
            ))}
            {article.sectors?.map((sec) => (
              <span
                key={sec}
                className="text-xs text-muted-foreground bg-muted/40 px-2 py-0.5 rounded border border-border/40"
              >
                {sec}
              </span>
            ))}
          </div>

          {/* AI Executive Takeaway Block */}
          <div className="rounded-lg border border-purple-800/40 bg-purple-950/20 p-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5 text-xs font-bold text-purple-300">
                <Sparkles className="h-4 w-4 text-purple-400" />
                AI Quantitative Takeaway
              </div>
              {!aiSummary && (
                <button
                  type="button"
                  disabled={loadingAi}
                  onClick={handleGenerateAi}
                  className="rounded bg-purple-600 px-2.5 py-1 text-xs font-semibold text-white transition hover:bg-purple-500 disabled:opacity-50"
                >
                  {loadingAi ? 'Analyzing...' : 'Generate AI Summary'}
                </button>
              )}
            </div>

            {aiSummary ? (
              <div className="mt-2.5 space-y-1.5 text-xs text-foreground/90 leading-relaxed font-mono whitespace-pre-line border-t border-purple-800/30 pt-2">
                {aiSummary}
                <div className="mt-2 text-[10px] text-muted-foreground/70 italic">
                  AI-generated analysis for informational purposes only. Not financial advice.
                </div>
              </div>
            ) : (
              <p className="mt-1.5 text-xs text-muted-foreground">
                Get an instant 3-bullet breakdown covering the factual catalyst, affected instruments, and key technical levels to watch.
              </p>
            )}
          </div>

          {/* Multi-Source Reporting Cluster */}
          {article.sources?.length > 1 && (
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3.5 space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-bold text-foreground/90">
                <Layers className="h-3.5 w-3.5 text-muted-foreground" />
                Coverage by {article.sources.length} Independent Publishers:
              </div>
              <div className="space-y-1.5 text-xs">
                {article.sources.map((src, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between gap-2 border-b border-border/30 pb-1.5 last:border-0 last:pb-0"
                  >
                    <span className="font-semibold text-foreground/80">{src.source}</span>
                    <a
                      href={src.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-primary hover:underline"
                    >
                      Read Report <ExternalLink className="h-3 w-3" />
                    </a>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Primary Outbound Link Button */}
        <div className="mt-6 flex justify-end gap-3 border-t border-border/50 pt-3">
          {article.source_url && article.source_url !== '#' && (
            <a
              href={article.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
            >
              Read Full Article on {article.source} <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
