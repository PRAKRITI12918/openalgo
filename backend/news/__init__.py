# backend/news/__init__.py
"""
OpenAlgo Market News Package.
"""

from backend.news.routes import news_bp
from backend.news.news_service import get_news_service

__all__ = ["news_bp", "get_news_service"]
