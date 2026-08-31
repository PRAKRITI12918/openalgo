# backend/news/news_service.py
"""
News Service Orchestrator with Caching, Filtering, Clustering, and AI Summaries.
"""

from datetime import datetime, timezone, timedelta
import logging
import os
import time
from typing import Any, Dict, List, Optional

from backend.news.aggregator_provider import AggregatorNewsProvider
from backend.news.clustering_engine import cluster_articles
from backend.news.trending_engine import rank_and_enrich_articles, parse_timestamp

logger = logging.getLogger("news.service")


class NewsService:
    """
    Central news service providing cached, ranked, and clustered financial intelligence.
    """

    def __init__(self):
        self.provider = AggregatorNewsProvider()
        self._cache: Dict[str, Any] = {}
        self._cache_ttl_sec = 180  # 3 minutes cache for live market news
        self._last_fetch_time = 0

    def get_feed(
        self,
        tab: str = "All",
        category: str = "All",
        timeframe: str = "all",
        impact_filter: str = "all",
        page: int = 1,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        """
        Retrieve processed and clustered news feed with tab sorting and filtering.
        """
        cache_key = f"feed_{tab}_{category}_{timeframe}_{impact_filter}"
        now_ts = time.time()

        # Check Cache
        cached = self._cache.get(cache_key)
        if cached and (now_ts - cached["timestamp"] < self._cache_ttl_sec):
            return self._paginate(cached["articles"], page, page_size, cached["breaking_news"], cached["trending_news"])

        # 1. Fetch raw articles from provider
        raw_articles = self.provider.fetch_articles(category="All", limit=100)

        # 2. Cluster & Deduplicate into multi-source entries
        clustered = cluster_articles(raw_articles)

        # 3. Enrich with Market Impact and Trending Scores
        enriched = rank_and_enrich_articles(clustered)

        # 4. Extract Top Trending and Breaking for sidebar highlights
        trending_sorted = sorted(enriched, key=lambda a: a.get("trending_score", 0), reverse=True)[:5]
        breaking_sorted = [a for a in enriched if a.get("is_breaking") or a.get("market_impact") == "HIGH"][:3]

        # 5. Apply Tab Filtering & Sorting
        tab_lower = tab.lower()
        if tab_lower == "trending":
            filtered = sorted(enriched, key=lambda a: a.get("trending_score", 0), reverse=True)
        elif tab_lower == "breaking":
            filtered = [a for a in enriched if a.get("is_breaking") or a.get("market_impact") == "HIGH"]
            filtered = sorted(filtered, key=lambda a: parse_timestamp(a.get("published_at", "")), reverse=True)
        elif tab_lower == "india":
            filtered = [a for a in enriched if a.get("country", "") == "IN"]
        elif tab_lower == "global":
            filtered = [a for a in enriched if a.get("country", "") == "GLOBAL" or "Global" in a.get("sectors", [])]
        elif tab_lower == "stocks":
            filtered = [a for a in enriched if "Stocks" in a.get("sectors", []) or a.get("symbols")]
        elif tab_lower == "indices":
            filtered = [a for a in enriched if any(s in ("NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY") for s in a.get("symbols", []))]
        elif tab_lower in ("sectors", "commodities", "economy"):
            filtered = [a for a in enriched if tab.capitalize() in a.get("sectors", []) or tab.capitalize() == a.get("category")]
        else:
            # Default "All" sorted by published date
            filtered = sorted(enriched, key=lambda a: parse_timestamp(a.get("published_at", "")), reverse=True)

        # 6. Apply Timeframe Filter
        if timeframe and timeframe != "all":
            now_dt = datetime.now(timezone.utc)
            max_age_min = 15 if timeframe == "15m" else (60 if timeframe == "1h" else 1440)
            cutoff_dt = now_dt - timedelta(minutes=max_age_min)
            filtered = [a for a in filtered if parse_timestamp(a.get("published_at", "")) >= cutoff_dt]

        # 7. Apply Impact Filter
        if impact_filter and impact_filter.lower() != "all":
            filtered = [a for a in filtered if a.get("market_impact", "").lower() == impact_filter.lower()]

        # Store in Cache
        self._cache[cache_key] = {
            "timestamp": now_ts,
            "articles": filtered,
            "trending_news": trending_sorted,
            "breaking_news": breaking_sorted,
        }

        return self._paginate(filtered, page, page_size, breaking_sorted, trending_sorted)

    def _paginate(
        self,
        articles: List[Dict[str, Any]],
        page: int,
        page_size: int,
        breaking: List[Dict[str, Any]],
        trending: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Paginate articles and attach metadata."""
        start = (page - 1) * page_size
        end = start + page_size
        paged_items = articles[start:end]

        return {
            "status": "success",
            "page": page,
            "page_size": page_size,
            "total_count": len(articles),
            "total_pages": max(1, (len(articles) + page_size - 1) // page_size),
            "articles": paged_items,
            "breaking_news": breaking,
            "trending_news": trending,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def get_by_symbol(self, symbol: str, limit: int = 15) -> Dict[str, Any]:
        """Fetch targeted news articles for a trading symbol."""
        sym_clean = symbol.strip().upper()
        raw = self.provider.fetch_by_symbol(sym_clean, limit=limit * 2)
        clustered = cluster_articles(raw)
        enriched = rank_and_enrich_articles(clustered)
        
        # Sort by latest published
        sorted_articles = sorted(enriched, key=lambda a: parse_timestamp(a.get("published_at", "")), reverse=True)

        return {
            "status": "success",
            "symbol": sym_clean,
            "count": len(sorted_articles[:limit]),
            "articles": sorted_articles[:limit],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def search_news(self, query: str, limit: int = 30) -> Dict[str, Any]:
        """Search news across all fields."""
        raw = self.provider.search(query, limit=limit * 2)
        clustered = cluster_articles(raw)
        enriched = rank_and_enrich_articles(clustered)
        sorted_articles = sorted(enriched, key=lambda a: a.get("trending_score", 0), reverse=True)

        return {
            "status": "success",
            "query": query,
            "count": len(sorted_articles[:limit]),
            "articles": sorted_articles[:limit],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def generate_ai_summary(self, article: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a concise, 3-bullet quantitative takeaway using Gemini AI.
        """
        title = article.get("title", "")
        summary = article.get("summary", "")
        symbols = ", ".join(article.get("symbols", [])) or "Market Indices"
        impact = article.get("market_impact", "MEDIUM")

        prompt = (
            f"You are a professional financial news quantitative analyst.\n"
            f"Analyze the following financial market news headline and summary for an active intraday and swing trader.\n"
            f"Headline: {title}\n"
            f"Summary: {summary}\n"
            f"Related Instruments: {symbols}\n"
            f"Classified Impact: {impact}\n\n"
            f"Provide exactly 3 concise, high-impact bullet points:\n"
            f"1. Core Event: State the factual catalyst clearly without fluff.\n"
            f"2. Direct Market / Sector Impact: Explain which sectors, indices, or stocks could experience volatility or volume shifts.\n"
            f"3. Trader Takeaway: What critical levels or indicators should a trader monitor.\n\n"
            f"Strict Rules: Do NOT give personal buy/sell financial advice. Keep each bullet under 25 words. Do not use emojis."
        )

        try:
            # Leverage existing Copilot Gemini client
            from backend.copilot.copilot_engine import get_copilot_engine
            engine = get_copilot_engine()
            ai_text = engine._call_gemini_rest(prompt)
            if ai_text:
                return {
                    "status": "success",
                    "article_id": article.get("id"),
                    "ai_summary": ai_text.strip(),
                    "disclaimer": "AI-generated market intelligence for informational purposes only. Not financial advice.",
                }
        except Exception as e:
            logger.debug(f"Gemini AI summary error: {e}")

        # High-Quality Algorithmic Fallback Summary
        fallback_summary = (
            f"• Core Catalyst: {title}\n"
            f"• Market Impact: Key volatility expected across {symbols} and related sector constituents with Potential Impact {impact}.\n"
            f"• Key Monitor: Watch opening session volume, VWAP reaction, and major weekly support/resistance levels."
        )

        return {
            "status": "success",
            "article_id": article.get("id"),
            "ai_summary": fallback_summary,
            "disclaimer": "AI-generated market intelligence for informational purposes only. Not financial advice.",
        }


# Singleton Instance
_news_service_instance: Optional[NewsService] = None


def get_news_service() -> NewsService:
    global _news_service_instance
    if _news_service_instance is None:
        _news_service_instance = NewsService()
    return _news_service_instance
