# backend/news/routes.py
"""
Flask API Routes for Real-Time Financial Market News.
"""

import logging
from flask import Blueprint, jsonify, request
from flask_cors import cross_origin

from backend.news.news_service import get_news_service

logger = logging.getLogger("news.routes")

news_bp = Blueprint("news_bp", __name__, url_prefix="/api/news")


@news_bp.route("/feed", methods=["GET"])
@cross_origin()
def get_news_feed():
    """
    Get paginated, clustered, and ranked market news feed.
    Query params: tab, category, timeframe, impact, page, page_size
    """
    try:
        tab = request.args.get("tab", "All").strip()
        category = request.args.get("category", "All").strip()
        timeframe = request.args.get("timeframe", "all").strip().lower()
        impact = request.args.get("impact", "all").strip().lower()
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 25))

        service = get_news_service()
        result = service.get_feed(
            tab=tab,
            category=category,
            timeframe=timeframe,
            impact_filter=impact,
            page=page,
            page_size=page_size,
        )
        return jsonify(result), 200

    except Exception as e:
        logger.exception(f"Error in /api/news/feed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@news_bp.route("/symbol/<symbol>", methods=["GET"])
@cross_origin()
def get_symbol_news(symbol: str):
    """
    Get targeted news articles for a specific trading symbol.
    """
    try:
        limit = int(request.args.get("limit", 15))
        service = get_news_service()
        result = service.get_by_symbol(symbol=symbol, limit=limit)
        return jsonify(result), 200

    except Exception as e:
        logger.exception(f"Error in /api/news/symbol/{symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@news_bp.route("/search", methods=["GET"])
@cross_origin()
def search_news():
    """
    Search news articles by keyword, symbol, or sector.
    """
    try:
        query = request.args.get("q", "").strip()
        limit = int(request.args.get("limit", 30))

        if not query:
            return jsonify({"status": "error", "message": "Search query cannot be empty."}), 400

        service = get_news_service()
        result = service.search_news(query=query, limit=limit)
        return jsonify(result), 200

    except Exception as e:
        logger.exception(f"Error in /api/news/search: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@news_bp.route("/ai-summary", methods=["POST"])
@cross_origin()
def generate_ai_summary():
    """
    Generate an AI 3-bullet takeaway for a specific news article.
    """
    try:
        data = request.get_json(silent=True) or {}
        if not data.get("title"):
            return jsonify({"status": "error", "message": "Article title is required."}), 400

        service = get_news_service()
        result = service.generate_ai_summary(data)
        return jsonify(result), 200

    except Exception as e:
        logger.exception(f"Error in /api/news/ai-summary: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@news_bp.route("/status", methods=["GET"])
@cross_origin()
def news_status():
    """Health status check for the News engine."""
    return jsonify({
        "status": "online",
        "service": "OpenAlgo Market News Engine",
        "provider": "Multi-Feed Financial Aggregator",
        "clustering": "active",
        "trending_algorithm": "active",
    }), 200
