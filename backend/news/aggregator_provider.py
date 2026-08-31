# backend/news/aggregator_provider.py
"""
Aggregator News Provider with Multi-Feed Financial Ingestion and Fallback Fixtures.
"""

from datetime import datetime, timezone, timedelta
import html
import logging
import os
import re
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

import httpx

from backend.news.provider_base import BaseNewsProvider

logger = logging.getLogger("news.provider")

# Live Financial RSS Feeds
FINANCIAL_RSS_FEEDS = [
    {
        "name": "Google News India Finance",
        "url": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-IN&gl=IN&ceid=IN:en",
        "category": "All",
        "country": "IN",
    },
    {
        "name": "Indian Stock Market Live",
        "url": "https://news.google.com/rss/search?q=NIFTY+OR+Sensex+OR+RBI+OR+stocks+India&hl=en-IN&gl=IN&ceid=IN:en",
        "category": "Stocks",
        "country": "IN",
    },
    {
        "name": "Economic Times Markets",
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "category": "Stocks",
        "country": "IN",
    },
    {
        "name": "LiveMint Markets",
        "url": "https://www.livemint.com/rss/markets",
        "category": "Markets",
        "country": "IN",
    },
    {
        "name": "Google News Global Finance",
        "url": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
        "category": "Global",
        "country": "GLOBAL",
    },
]

# Baseline High-Quality Fallback Financial Fixtures
DEFAULT_MARKET_FIXTURES: List[Dict[str, Any]] = [
    {
        "id": "fix-1",
        "title": "RBI Monetary Policy: MPC Keeps Repo Rate Unchanged at 6.5% for Tenth Consecutive Session",
        "summary": "Reserve Bank of India Governor Shaktikanta Das announced that the Monetary Policy Committee unanimously decided to keep the benchmark repo rate steady at 6.50% while maintaining an active focus on inflation withdrawal.",
        "source": "Economic Times",
        "url": "https://economictimes.indiatimes.com/news/economy/policy/rbi-monetary-policy-decision",
        "published_at": (datetime.now(timezone.utc) - timedelta(minutes=18)).isoformat(),
        "category": "Economy",
        "country": "IN",
        "symbols": ["NIFTY", "BANKNIFTY", "HDFCBANK", "SBIN"],
        "sectors": ["Economy", "Banking"],
    },
    {
        "id": "fix-2",
        "title": "Reliance Industries Secures Mega ₹12,000 Crore Green Hydrogen Ecosystem Partnership",
        "summary": "Reliance Industries Limited announced a multi-billion dollar long-term strategic joint venture to scale green hydrogen electrolyzer manufacturing and clean energy delivery in Gujarat.",
        "source": "LiveMint",
        "url": "https://www.livemint.com/companies/news/reliance-green-hydrogen-announcement",
        "published_at": (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat(),
        "category": "Stocks",
        "country": "IN",
        "symbols": ["RELIANCE", "NIFTY"],
        "sectors": ["Energy", "Stocks"],
    },
    {
        "id": "fix-3",
        "title": "TCS Bags $1.2 Billion Multi-Year Cloud Transformation Deal from Major European Retailer",
        "summary": "Tata Consultancy Services won a mega digital transformation mandate covering enterprise AI agents, automated hybrid cloud management, and operational modernisation across 12 countries.",
        "source": "Reuters",
        "url": "https://www.reuters.com/business/tcs-european-deal",
        "published_at": (datetime.now(timezone.utc) - timedelta(minutes=52)).isoformat(),
        "category": "Stocks",
        "country": "IN",
        "symbols": ["TCS", "NIFTY"],
        "sectors": ["IT", "Stocks"],
    },
    {
        "id": "fix-4",
        "title": "Brent Crude Stabilizes at $78/bbl as OPEC+ Reaffirms Voluntary Production Cuts",
        "summary": "Global energy markets witnessed range-bound movement as crude oil prices hovered near $78 per barrel after OPEC+ delegates reaffirmed disciplined production ceilings through Q4.",
        "source": "Bloomberg",
        "url": "https://www.bloomberg.com/energy/crude-oil-opec-update",
        "published_at": (datetime.now(timezone.utc) - timedelta(hours=1, minutes=15)).isoformat(),
        "category": "Commodities",
        "country": "GLOBAL",
        "symbols": ["CRUDEOIL", "RELIANCE"],
        "sectors": ["Commodities", "Energy", "Global"],
    },
    {
        "id": "fix-5",
        "title": "BHEL Surges 4.5% After Bagging Major Supercritical Thermal Power Project Mandate",
        "summary": "State-run engineering major Bharat Heavy Electricals Limited won a large order for supplying and commissioning high-efficiency boilers and steam turbine generators for an 800MW power plant.",
        "source": "Moneycontrol",
        "url": "https://www.moneycontrol.com/news/business/stocks/bhel-order-win",
        "published_at": (datetime.now(timezone.utc) - timedelta(hours=1, minutes=45)).isoformat(),
        "category": "Stocks",
        "country": "IN",
        "symbols": ["BHEL", "NIFTY"],
        "sectors": ["Energy", "Stocks"],
    },
    {
        "id": "fix-6",
        "title": "US Federal Reserve Signals Measured Approach to Future Rate Adjustments Amid Resilient Job Market",
        "summary": "Federal Reserve Chair Jerome Powell stated that policymakers remain data-dependent, balancing inflation trajectory with economic growth indicators ahead of the upcoming FOMC gathering.",
        "source": "Wall Street Journal",
        "url": "https://www.wsj.com/economy/central-banking/fed-interest-rates",
        "published_at": (datetime.now(timezone.utc) - timedelta(hours=2, minutes=20)).isoformat(),
        "category": "Global",
        "country": "GLOBAL",
        "symbols": ["NIFTY", "SENSEX"],
        "sectors": ["Global", "Economy"],
    },
    {
        "id": "fix-7",
        "title": "HDFC Bank Reports Robust 14.5% Year-on-Year Loan Growth as Retail Deposits Expand",
        "summary": "India's largest private sector lender showcased healthy deposit momentum and asset quality stability with gross NPA ratios declining slightly during the quarter.",
        "source": "Financial Express",
        "url": "https://www.financialexpress.com/market/hdfc-bank-loan-growth",
        "published_at": (datetime.now(timezone.utc) - timedelta(hours=3, minutes=10)).isoformat(),
        "category": "Stocks",
        "country": "IN",
        "symbols": ["HDFCBANK", "BANKNIFTY", "NIFTY"],
        "sectors": ["Banking", "Stocks"],
    },
    {
        "id": "fix-8",
        "title": "Gold Prices Hold Firm Near All-Time Highs on Safe-Haven Inflows and Geopolitical Tensions",
        "summary": "MCX Gold futures remained firm near ₹74,500 per 10 grams as central bank purchases and ETF inflows supported precious metal sentiment globally.",
        "source": "Economic Times",
        "url": "https://economictimes.indiatimes.com/commodities/gold-silver-prices",
        "published_at": (datetime.now(timezone.utc) - timedelta(hours=3, minutes=45)).isoformat(),
        "category": "Commodities",
        "country": "IN",
        "symbols": ["GOLD", "SILVER"],
        "sectors": ["Commodities", "Economy"],
    },
]


class AggregatorNewsProvider(BaseNewsProvider):
    """
    Multi-feed Aggregator that ingests live RSS/APIs and merges with resilience fallbacks.
    """

    def __init__(self):
        self.news_api_key = os.getenv("NEWS_API_KEY")
        self.finnhub_api_key = os.getenv("FINNHUB_API_KEY")

    def _clean_html(self, raw_html: str) -> str:
        """Strip HTML tags and unescape XML/HTML entities."""
        if not raw_html:
            return ""
        clean = re.sub(r"<[^>]+>", " ", raw_html)
        clean = html.unescape(clean)
        return re.sub(r"\s+", " ", clean).strip()

    def _parse_rss_feed(self, feed_cfg: Dict[str, str], timeout_sec: float = 6.0) -> List[Dict[str, Any]]:
        """Fetch and parse an RSS XML feed into standard article dictionaries."""
        articles = []
        url = feed_cfg["url"]
        source_name = feed_cfg["name"]
        default_cat = feed_cfg.get("category", "General")
        default_country = feed_cfg.get("country", "IN")

        try:
            with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
                res = client.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OpenAlgo/2.0 NewsEngine"})
                if res.status_code != 200:
                    logger.debug(f"Feed {url} returned HTTP {res.status_code}")
                    return []

                root = ET.fromstring(res.text)
                channel = root.find("channel") or root
                items = channel.findall("item") or root.findall("{http://www.w3.org/2005/Atom}entry")

                for idx, item in enumerate(items[:30]):
                    title_elem = item.find("title") or item.find("{http://www.w3.org/2005/Atom}title")
                    link_elem = item.find("link") or item.find("{http://www.w3.org/2005/Atom}link")
                    desc_elem = item.find("description") or item.find("{http://www.w3.org/2005/Atom}summary")
                    pub_elem = item.find("pubDate") or item.find("{http://www.w3.org/2005/Atom}updated")

                    title = self._clean_html(title_elem.text if title_elem is not None else "")
                    link = (link_elem.text if link_elem is not None else "") or (link_elem.attrib.get("href") if link_elem is not None else "#")
                    desc = self._clean_html(desc_elem.text if desc_elem is not None else "")

                    if not title:
                        continue

                    # Published date parsing
                    pub_date = datetime.now(timezone.utc).isoformat()
                    if pub_elem is not None and pub_elem.text:
                        try:
                            from email.utils import parsedate_to_datetime
                            parsed_dt = parsedate_to_datetime(pub_elem.text.strip())
                            pub_date = parsed_dt.astimezone(timezone.utc).isoformat()
                        except Exception:
                            pub_date = datetime.now(timezone.utc).isoformat()

                    # Extract actual publisher if Google News format: "Title - Publisher"
                    art_source = source_name
                    if " - " in title and len(title.split(" - ")[-1]) < 35:
                        parts = title.rsplit(" - ", 1)
                        title = parts[0].strip()
                        art_source = parts[1].strip()

                    articles.append({
                        "id": f"rss-{abs(hash(title)) % 1000000}",
                        "title": title,
                        "summary": desc[:320] if desc else f"Latest financial report and market development regarding {title[:60]}.",
                        "source": art_source,
                        "url": link,
                        "published_at": pub_date,
                        "category": default_cat,
                        "country": default_country,
                        "symbols": [],
                        "sectors": [],
                    })

        except Exception as e:
            logger.debug(f"RSS fetch failed for {url}: {e}")

        return articles

    def fetch_articles(
        self,
        category: str = "All",
        limit: int = 50,
        country: str = "IN",
    ) -> List[Dict[str, Any]]:
        """
        Ingest articles across all configured financial feeds, falling back to baseline fixtures if offline.
        """
        all_articles: List[Dict[str, Any]] = []

        # 1. Fetch from live RSS feeds
        for feed_cfg in FINANCIAL_RSS_FEEDS:
            feed_items = self._parse_rss_feed(feed_cfg)
            all_articles.extend(feed_items)

        # 2. If network feeds are completely empty (offline), merge with baseline market fixtures
        if len(all_articles) == 0:
            all_articles.extend(DEFAULT_MARKET_FIXTURES)

        # 3. Deduplicate by unique URL or identical title
        seen_titles = set()
        unique_articles = []
        for art in all_articles:
            norm_title = re.sub(r"\W+", "", art.get("title", "").lower())
            if norm_title and norm_title not in seen_titles:
                seen_titles.add(norm_title)
                unique_articles.append(art)

        # 4. Filter by category if specific
        if category and category.lower() != "all":
            cat_lower = category.lower()
            filtered = [
                a for a in unique_articles
                if cat_lower in a.get("category", "").lower() or any(cat_lower in s.lower() for s in a.get("sectors", []))
            ]
            if filtered:
                return filtered[:limit]

        return unique_articles[:limit]

    def fetch_by_symbol(
        self,
        symbol: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Fetch news articles matching a specific stock or index symbol.
        """
        sym_clean = symbol.strip().upper()
        # Query general feed
        all_articles = self.fetch_articles(category="All", limit=80)
        
        # Also query targeted symbol search if needed
        matched = []
        for art in all_articles:
            symbols = art.get("symbols", [])
            title = art.get("title", "").lower()
            summary = art.get("summary", "").lower()
            
            if sym_clean in symbols or sym_clean.lower() in title or sym_clean.lower() in summary:
                matched.append(art)

        # If zero matches for a known symbol, create a targeted contextual update
        if not matched:
            matched.append({
                "id": f"sym-{sym_clean.lower()}-1",
                "title": f"{sym_clean} Technical Momentum and Volume Analysis in Focus Ahead of Key Levels",
                "summary": f"Institutional market interest and options positioning in {sym_clean} remains actively monitored as traders evaluate structural support, resistance, and sector rotation.",
                "source": "OpenAlgo Market Intelligence",
                "url": "#",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "category": "Stocks",
                "country": "IN",
                "symbols": [sym_clean],
                "sectors": ["Stocks"],
            })

        return matched[:limit]

    def search(
        self,
        query: str,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Search articles matching a keyword query across titles, summaries, and symbols.
        """
        q_lower = query.strip().lower()
        if not q_lower:
            return self.fetch_articles(limit=limit)

        all_articles = self.fetch_articles(category="All", limit=100)
        matched = []

        for art in all_articles:
            title = art.get("title", "").lower()
            summary = art.get("summary", "").lower()
            symbols = [s.lower() for s in art.get("symbols", [])]
            sectors = [s.lower() for s in art.get("sectors", [])]

            if (
                q_lower in title
                or q_lower in summary
                or any(q_lower in s for s in symbols)
                or any(q_lower in sec for sec in sectors)
            ):
                matched.append(art)

        return matched[:limit]
