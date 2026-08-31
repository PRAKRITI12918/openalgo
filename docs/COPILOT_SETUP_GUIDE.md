# Quantitative Copilot Setup & Configuration Guide

> **Module**: OpenAlgo Quantitative Copilot  
> **Integrations**: Google Gemini GenAI SDK + DhanHQ Market Data API v2 + OpenAlgo Execution Core  
> **Safety Protocol**: 2-Step Action Confirmation Requirement for Order Placement

---

## 1. Environment Variables Configuration

Copy and configure the following variables in your `.env` file:

```env
# ==============================================================================
# Quantitative AI Copilot Settings
# ==============================================================================
# Google Gemini API Key (from Google AI Studio / Vertex AI)
GEMINI_API_KEY=your_gemini_api_key_here

# Model Selection: gemini-2.5-flash (Fast, low-latency) or gemini-1.5-pro (High-reasoning)
GEMINI_MODEL=gemini-2.5-flash

# Dhan Market Data Credentials
DHAN_CLIENT_ID=1113284554
DHAN_ACCESS_TOKEN=your_dhan_jwt_access_token_here

# Copilot Audit Log File Destination
COPILOT_AUDIT_LOG=log/copilot_audit.log

# OpenAlgo Secret Key for Signing Confirmation Payloads
OPENALGO_SECRET_KEY=openalgo-copilot-secret-key-2026
```

---

## 2. Architecture & Directory Layout

The Copilot engine is organized into modular, production-ready components:

| Component | File Path | Description |
|---|---|---|
| **Market Data Provider** | [`backend/copilot/dhan_client.py`](file:///d:/Openalgo/openalgo/backend/copilot/dhan_client.py) | Token-bucket rate limiter (10 req/s), REST quotes, OHLCV, 20-depth, and TTL cache |
| **Execution Adapter** | [`backend/copilot/openalgo_trader.py`](file:///d:/Openalgo/openalgo/backend/copilot/openalgo_trader.py) | Standardized routing, pre-trade risk checks, 2-step confirmation generation, audit logging |
| **Gemini Tool Orchestrator** | [`backend/copilot/copilot_engine.py`](file:///d:/Openalgo/openalgo/backend/copilot/copilot_engine.py) | Gemini tool calling (`fetch_market_data`, `fetch_portfolio_state`, `prepare_order_intent`), multi-turn memory |
| **API Endpoints** | [`backend/copilot/routes.py`](file:///d:/Openalgo/openalgo/backend/copilot/routes.py) | Flask routes (`/api/copilot/chat`, `/api/copilot/execute-confirmed-order`, `/api/copilot/history/<id>`) |
| **React Component** | [`frontend/src/components/Copilot/CopilotPanel.jsx`](file:///d:/Openalgo/openalgo/frontend/src/components/Copilot/CopilotPanel.jsx) | Interactive Copilot sidebar with Markdown, quote cards, and 2-step order execution cards |

---

## 3. Endpoints Reference

### 1. `POST /api/copilot/chat`
**Request Payload**:
```json
{
  "session_id": "session-12345",
  "message": "Analyze trend and support resistance for BHEL",
  "active_symbol": "BHEL",
  "active_timeframe": "5m"
}
```

**Response**:
```json
{
  "status": "success",
  "session_id": "session-12345",
  "response_text": "### 📈 Quantitative Market Analysis: **BHEL**...",
  "action_required": false,
  "data_payload": {
    "market_data": { "ltp": 430.85, "vwap": 431.05, ... }
  },
  "order_confirmation": null
}
```

### 2. `POST /api/copilot/execute-confirmed-order`
**Request Payload**:
```json
{
  "session_id": "session-12345",
  "token": "4a7c8d9e2b1f0a3c4e5d6f7a8b9c0d1e"
}
```

**Response**:
```json
{
  "status": "SUCCESS",
  "order_id": "DHAN-1788029999-a1b2",
  "message": "Successfully executed BUY 10 BHEL @ MARKET on NSE."
}
```

---

## 4. Audit Trails & Compliance

Every user query, tool execution, and confirmed order placement is logged in real-time to:
📂 `log/copilot_audit.log`

```json
{"timestamp": "2026-08-30 00:25:00", "event": "USER_QUERY", "payload": {"session_id": "session-1", "message": "Buy 10 BHEL"}}
{"timestamp": "2026-08-30 00:25:01", "event": "ORDER_INTENT_PREPARED", "payload": {"symbol": "BHEL", "action": "BUY", "qty": 10, "token": "..."}}
{"timestamp": "2026-08-30 00:25:05", "event": "ORDER_EXECUTED", "payload": {"order_id": "DHAN-1788029999", "symbol": "BHEL", "action": "BUY"}}
```
