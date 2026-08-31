# backend/news/clustering_engine.py
"""
Deduplication, Clustering, and Entity Extraction Engine for Financial News.
"""

import re
from typing import Any, Dict, List, Set, Tuple

# Key Symbols Map (Ticker -> Name/Keywords)
KNOWN_SYMBOLS = {
    "NIFTY": ["nifty", "nifty 50", "nse index"],
    "BANKNIFTY": ["bank nifty", "nifty bank", "banking index"],
    "SENSEX": ["sensex", "bse index", "bse 30"],
    "FINNIFTY": ["finnifty", "nifty financial"],
    "RELIANCE": ["reliance", "ril", "mukesh ambani", "jio"],
    "TCS": ["tcs", "tata consultancy"],
    "HDFCBANK": ["hdfc bank", "hdfc"],
    "INFY": ["infosys", "infy", "salil parekh"],
    "ICICIBANK": ["icici bank", "icici"],
    "SBIN": ["state bank of india", "sbi", "sbin"],
    "BHEL": ["bhel", "bharat heavy electricals"],
    "TATAMOTORS": ["tata motors", "jlr", "jaguar land rover"],
    "ITC": ["itc", "itc limited"],
    "LT": ["l&t", "larsen & toubro", "larsen and toubro"],
    "BHARTIARTL": ["bharti airtel", "airtel"],
    "MARUTI": ["maruti suzuki", "maruti"],
    "SUNPHARMA": ["sun pharma", "sun pharmaceutical"],
    "WIPRO": ["wipro"],
    "TITAN": ["titan company", "titan"],
    "ADANIENT": ["adani enterprises", "adani group", "gautam adani"],
    "KOTAKBANK": ["kotak mahindra bank", "kotak"],
    "BAJFINANCE": ["bajaj finance", "bajfinance"],
    "TATASTEEL": ["tata steel"],
    "ASIANPAINT": ["asian paints"],
    "AXISBANK": ["axis bank"],
    "HCLTECH": ["hcl tech", "hcl technologies"],
    "CRUDEOIL": ["crude oil", "brent crude", "opec", "wti"],
    "GOLD": ["gold", "bullion", "mcx gold"],
    "SILVER": ["silver", "mcx silver"],
}

# Sector Keywords
SECTOR_MAP = {
    "Banking": ["bank", "banking", "rbi", "repo rate", "lending", "npa", "credit", "deposits", "hdfc", "icici", "sbi", "kotak", "axis"],
    "IT": ["it sector", "tech", "software", "ai", "cloud", "tcs", "infosys", "wipro", "hcl", "tech mahindra", "nasdaq"],
    "Auto": ["auto", "automotive", "ev", "electric vehicle", "tata motors", "maruti", "mahindra", "bajaj auto", "hero motocorp"],
    "Pharma": ["pharma", "pharmaceutical", "fda", "drug", "healthcare", "sun pharma", "dr reddy", "cipla", "lupin"],
    "Energy": ["energy", "oil", "gas", "power", "solar", "renewable", "reliance", "ongc", "ntpc", "power grid", "crude"],
    "Metals": ["metal", "steel", "mining", "iron ore", "aluminum", "copper", "tata steel", "jsw steel", "hindalco", "vedanta"],
    "Economy": ["gdp", "inflation", "cpi", "wpi", "fiscal deficit", "rbi", "budget", "fed", "federal reserve", "interest rate", "imf", "world bank"],
    "Commodities": ["gold", "silver", "crude", "natural gas", "copper", "agri", "mcx"],
    "FMCG": ["fmcg", "consumption", "retail", "itc", "hul", "nestle", "dabur", "britannia"],
    "Global": ["wall street", "us markets", "dow jones", "s&p 500", "nasdaq", "china", "europe", "ftse", "nikkei", "geopolitical"],
}

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "at", "from",
    "by", "for", "with", "about", "against", "between", "into", "through", "during",
    "before", "after", "above", "below", "to", "of", "in", "on", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "as",
    "its", "it", "this", "that", "these", "those", "says", "said", "new", "amid", "over"
}


def extract_symbols_and_sectors(title: str, summary: str = "") -> Tuple[List[str], List[str]]:
    """
    Extract matching trading symbols and sector classifications from news text.
    """
    combined = f"{title} {summary}".lower()
    symbols: Set[str] = set()
    sectors: Set[str] = set()

    for sym, aliases in KNOWN_SYMBOLS.items():
        if sym.lower() in combined or any(re.search(rf"\b{re.escape(alias)}\b", combined) for alias in aliases):
            symbols.add(sym)

    for sec, keywords in SECTOR_MAP.items():
        if any(re.search(rf"\b{re.escape(kw)}\b", combined) for kw in keywords):
            sectors.add(sec)

    return sorted(list(symbols)), sorted(list(sectors)) or ["Stocks"]


def tokenize(text: str) -> Set[str]:
    """Tokenize and remove stop words for similarity scoring."""
    words = re.findall(r"\b[a-zA-Z0-9]{3,}\b", text.lower())
    return {w for w in words if w not in STOP_WORDS}


def calculate_similarity(title1: str, title2: str) -> float:
    """
    Calculate Jaccard token similarity between two headlines.
    """
    tokens1 = tokenize(title1)
    tokens2 = tokenize(title2)
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


def cluster_articles(articles: List[Dict[str, Any]], similarity_threshold: float = 0.40) -> List[Dict[str, Any]]:
    """
    Deduplicate and cluster news articles covering the same core event.
    Returns a list of cluster parent articles with nested multi-source reports.
    """
    clusters: List[Dict[str, Any]] = []

    for art in articles:
        title = art.get("title", "")
        symbols, sectors = extract_symbols_and_sectors(title, art.get("summary", ""))
        art["symbols"] = list(set(art.get("symbols", []) + symbols))
        art["sectors"] = list(set(art.get("sectors", []) + sectors))

        matched_cluster = None
        for cluster in clusters:
            sim = calculate_similarity(title, cluster["title"])
            # High similarity or same core ticker + overlapping action keywords
            if sim >= similarity_threshold:
                matched_cluster = cluster
                break

        if matched_cluster:
            # Append as an additional source report
            matched_cluster["sources_count"] += 1
            matched_cluster["sources"].append({
                "source": art.get("source", "Financial News"),
                "title": title,
                "url": art.get("url") or art.get("sourceUrl", "#"),
                "published_at": art.get("published_at") or art.get("publishedAt", ""),
            })
            # Merge symbols and sectors
            matched_cluster["symbols"] = list(set(matched_cluster["symbols"] + art["symbols"]))
            matched_cluster["sectors"] = list(set(matched_cluster["sectors"] + art["sectors"]))
        else:
            # Create new cluster entry
            new_cluster = {
                "id": art.get("id") or f"art-{len(clusters)+1}",
                "title": title,
                "summary": art.get("summary", ""),
                "source": art.get("source", "Financial News"),
                "source_url": art.get("url") or art.get("sourceUrl", "#"),
                "image_url": art.get("image_url") or art.get("imageUrl", ""),
                "published_at": art.get("published_at") or art.get("publishedAt", ""),
                "category": art.get("category", "General"),
                "country": art.get("country", "IN"),
                "symbols": art["symbols"],
                "sectors": art["sectors"],
                "sources_count": 1,
                "sources": [
                    {
                        "source": art.get("source", "Financial News"),
                        "title": title,
                        "url": art.get("url") or art.get("sourceUrl", "#"),
                        "published_at": art.get("published_at") or art.get("publishedAt", ""),
                    }
                ],
            }
            clusters.append(new_cluster)

    return clusters
