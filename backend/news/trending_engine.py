# backend/news/trending_engine.py
"""
Trending Score Algorithm and Market Impact Classifier for Financial News.
"""

from datetime import datetime, timezone
import math
import re
from typing import Any, Dict, List

# High-Impact Trigger Patterns
HIGH_IMPACT_PATTERNS = [
    r"\b(rbi|repo rate|monetary policy|rate hike|rate cut|interest rate|reverse repo)\b",
    r"\b(federal reserve|fed rate|jerome powell|fomc|ecb rate)\b",
    r"\b(gdp|inflation|cpi|wpi|fiscal deficit|union budget|tax cut|recession)\b",
    r"\b(q[1-4]\s*(profit|results|net profit|earnings|loss)|quarterly profit|profit jumps|net loss)\b",
    r"\b(merger|acquisition|takeover|demerger|buyout|open offer)\b",
    r"\b(sebi|regulatory ban|fraud|investigation|penalty|ed raid|cbi|arrest|sanction|tariff)\b",
    r"\b(war|missile|geopolitical|crude surge|opec cut|embargo|lockdown)\b",
]

MEDIUM_IMPACT_PATTERNS = [
    r"\b(target price|upgrade|downgrade|brokerage view|buy call|sell call|rating)\b",
    r"\b(order win|contract award|secures order|bags order|deal worth|mou signed)\b",
    r"\b(dividend|bonus shares|stock split|rights issue|fpo|ipo listing|anchor book)\b",
    r"\b(management change|resigns|appointed ceo|md steps down|board approves)\b",
    r"\b(capacity expansion|new plant|capex|greenfield|commercial production)\b",
]


def classify_market_impact(title: str, summary: str = "") -> Dict[str, str]:
    """
    Classify the potential market impact of an event as HIGH, MEDIUM, or LOW.
    Returns the impact level and trader-safe standardized label.
    """
    text = f"{title} {summary}".lower()

    for pattern in HIGH_IMPACT_PATTERNS:
        if re.search(pattern, text):
            return {
                "impact": "HIGH",
                "label": "Potential Market Impact: HIGH",
                "badge_color": "rose",
            }

    for pattern in MEDIUM_IMPACT_PATTERNS:
        if re.search(pattern, text):
            return {
                "impact": "MEDIUM",
                "label": "Potential Market Impact: MEDIUM",
                "badge_color": "amber",
            }

    return {
        "impact": "LOW",
        "label": "Potential Market Impact: LOW",
        "badge_color": "slate",
    }


def parse_timestamp(ts_str: str) -> datetime:
    """Safely parse various ISO/RFC timestamps into UTC datetime."""
    if not ts_str:
        return datetime.now(timezone.utc)
    try:
        if "T" in ts_str:
            clean_ts = ts_str.replace("Z", "+00:00")
            return datetime.fromisoformat(clean_ts).astimezone(timezone.utc)
        return datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def compute_trending_score(article: Dict[str, Any]) -> float:
    """
    Compute a quantitative Trending Score based on:
    - Recency decay (half-life of 2 hours)
    - Multi-source reporting cluster count (N sources)
    - Market impact severity
    - Macro/Market benchmark relevance (NIFTY, SENSEX, RBI)
    """
    pub_dt = parse_timestamp(article.get("published_at", ""))
    now_dt = datetime.now(timezone.utc)
    age_hours = max(0.0, (now_dt - pub_dt).total_seconds() / 3600.0)

    # 1. Recency Score (Decays with age, max 100 for brand new)
    # Exponential decay with half-life ~ 3 hours
    recency_score = 100.0 * math.exp(-0.25 * age_hours)

    # 2. Multi-Source Boost (More outlets reporting = higher trending score)
    sources_count = article.get("sources_count", 1)
    source_score = (sources_count - 1) * 35.0

    # 3. Market Impact Bonus
    impact_info = article.get("market_impact_info", {})
    impact = impact_info.get("impact", "LOW")
    impact_score = 45.0 if impact == "HIGH" else (20.0 if impact == "MEDIUM" else 0.0)

    # 4. Macro / Benchmark Relevance
    symbols = article.get("symbols", [])
    sectors = article.get("sectors", [])
    title_lower = article.get("title", "").lower()
    
    macro_bonus = 0.0
    if any(s in symbols for s in ("NIFTY", "BANKNIFTY", "SENSEX", "RELIANCE", "HDFCBANK")):
        macro_bonus += 25.0
    if any(k in title_lower for k in ("rbi", "fed", "budget", "gdp", "repo rate", "sensex")):
        macro_bonus += 20.0
    if "Economy" in sectors or "Banking" in sectors:
        macro_bonus += 10.0

    # 5. Breaking News Flag
    is_breaking = age_hours <= 0.75 and (impact == "HIGH" or sources_count >= 2)

    total_score = round(recency_score + source_score + impact_score + macro_bonus, 1)
    return total_score, is_breaking


def rank_and_enrich_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Classify market impact, calculate trending scores, and sort articles.
    """
    enriched = []
    for art in articles:
        impact_info = classify_market_impact(art.get("title", ""), art.get("summary", ""))
        art["market_impact_info"] = impact_info
        art["market_impact"] = impact_info["impact"]
        art["market_impact_label"] = impact_info["label"]

        score, is_breaking = compute_trending_score(art)
        art["trending_score"] = score
        art["is_breaking"] = is_breaking
        enriched.append(art)

    return enriched
