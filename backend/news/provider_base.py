# backend/news/provider_base.py
"""
Base provider interface for financial news ingestion.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseNewsProvider(ABC):
    """Abstract base class for all financial news providers."""

    @abstractmethod
    def fetch_articles(
        self,
        category: str = "All",
        limit: int = 50,
        country: str = "IN",
    ) -> List[Dict[str, Any]]:
        """
        Fetch latest news articles filtered by category.
        """
        pass

    @abstractmethod
    def fetch_by_symbol(
        self,
        symbol: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Fetch news articles relevant to a specific trading symbol/ticker.
        """
        pass

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Search articles matching a query string across titles and summaries.
        """
        pass
