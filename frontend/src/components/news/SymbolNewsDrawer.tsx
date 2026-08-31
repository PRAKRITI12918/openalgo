// frontend/src/components/news/SymbolNewsDrawer.tsx
/**
 * Slide-over drawer or dialog for viewing symbol-targeted news directly inside the Trading terminal.
 */

import { useEffect, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Newspaper, RefreshCw, X } from 'lucide-react'
import type { NewsArticle } from '@/types/news'
import { fetchSymbolNews } from '@/api/news'
import { NewsCard } from './NewsCard'
import { NewsDetailModal } from './NewsDetailModal'

interface SymbolNewsDrawerProps {
  symbol: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SymbolNewsDrawer({
  symbol,
  open,
  onOpenChange,
}: SymbolNewsDrawerProps) {
  const [articles, setArticles] = useState<NewsArticle[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedArticle, setSelectedArticle] = useState<NewsArticle | null>(null)

  const loadNews = async () => {
    if (!symbol) return
    try {
      setLoading(true)
      const res = await fetchSymbolNews(symbol)
      setArticles(res.articles || [])
    } catch (e) {
      console.error('Failed to load symbol news:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open && symbol) {
      loadNews()
    }
  }, [open, symbol])

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-xl max-h-[85vh] overflow-hidden flex flex-col border-border bg-card/95 backdrop-blur-md p-5 text-foreground">
          <DialogHeader className="flex flex-row items-center justify-between border-b border-border/50 pb-3">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/20 text-primary">
                <Newspaper className="h-4 w-4" />
              </div>
              <div>
                <DialogTitle className="text-base font-bold text-foreground">
                  Latest Market News for {symbol}
                </DialogTitle>
                <div className="text-xs text-muted-foreground">
                  Real-time catalysts, earnings, and regulatory updates
                </div>
              </div>
            </div>

            <button
              type="button"
              onClick={loadNews}
              disabled={loading}
              className="rounded p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-50 transition-colors"
              title="Refresh Symbol News"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </DialogHeader>

          {/* Articles Feed */}
          <div className="flex-1 overflow-y-auto space-y-3 pr-1 pt-3">
            {loading && !articles.length ? (
              <div className="space-y-3 py-6 text-center text-xs text-muted-foreground">
                <RefreshCw className="mx-auto h-5 w-5 animate-spin text-primary" />
                <p>Loading latest market intelligence for {symbol}...</p>
              </div>
            ) : articles.length > 0 ? (
              articles.map((art) => (
                <NewsCard
                  key={art.id}
                  article={art}
                  onSelect={(a) => setSelectedArticle(a)}
                  compact={true}
                />
              ))
            ) : (
              <div className="py-12 text-center text-xs text-muted-foreground">
                No active breaking news found for {symbol}. Market trading normally.
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Full Article Modal */}
      <NewsDetailModal
        article={selectedArticle}
        open={Boolean(selectedArticle)}
        onOpenChange={(v) => !v && setSelectedArticle(null)}
      />
    </>
  )
}
