# DhanHQ API Version 2.0 Comprehensive Reference Guide

> **Official Documentation**: [https://dhanhq.co/docs/v2/](https://dhanhq.co/docs/v2/)  
> **Target Audience**: OpenAlgo Developers, Trading Engine, Brokers Adapter  
> **API Version**: `v2.0`

---

## 1. Overview & Architecture

DhanHQ API v2 is Dhan's REST and WebSocket API for algorithmic execution, live streaming market data, option analytics, and portfolio management.

### Base URLs
| Service | Endpoint URL | Description |
|---|---|---|
| **REST API** | `https://api.dhan.co/v2` | Main REST API base for orders, portfolio, funds, and quotes |
| **Direct TOTP Auth** | `https://auth.dhan.co/app/generateAccessToken` | Direct token generation with `dhanClientId`, `pin`, `totp` |
| **Market Feed WS** | `wss://api-feed.dhan.co` | High-speed binary WebSocket for live quotes and 20-depth |
| **Order Update WS** | `wss://api-order-update.dhan.co` | Real-time order execution & status notifications |
| **Scrip Master CSV** | `https://images.dhan.co/api-data/api-scrip-master.csv` | Daily compact master contract symbol list |
| **Scrip Master JSON**| `https://images.dhan.co/api-data/api-scrip-master.json`| Daily master contract JSON |

---

## 2. Authentication & Request Headers

### Headers Required for REST Requests
```http
access-token: <YOUR_JWT_ACCESS_TOKEN>
client-id: <YOUR_10_DIGIT_DHAN_CLIENT_ID>
Content-Type: application/json
Accept: application/json
```

### Direct TOTP Access Token Generation
```http
POST https://auth.dhan.co/app/generateAccessToken?dhanClientId={clientId}&pin={pin}&totp={totp}
```
**Response Format**:
```json
{
  "status": "success",
  "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "dhanClientId": "1113284554",
  "dhanClientName": "Prakriti Dhanasekar",
  "expiryTime": "2026-08-31 06:00:00"
}
```

---

## 3. Order Management APIs

### Place Order
- **Method & Path**: `POST /v2/orders`
- **Payload**:
```json
{
  "dhanClientId": "1113284554",
  "correlationId": "ORDER-123456",
  "transactionType": "BUY",
  "exchangeSegment": "NSE_EQ",
  "productType": "INTRADAY",
  "orderType": "MARKET",
  "validity": "DAY",
  "securityId": "1333",
  "quantity": 10,
  "disclosedQuantity": 0,
  "price": 0.0,
  "triggerPrice": 0.0,
  "afterMarketOrder": false,
  "amoTime": "OPEN"
}
```

### Modify Order
- **Method & Path**: `PUT /v2/orders/{order-id}`
- **Payload**:
```json
{
  "dhanClientId": "1113284554",
  "orderId": "1122334455",
  "orderType": "LIMIT",
  "legName": "ENTRY_LEG",
  "quantity": 15,
  "price": 420.50,
  "triggerPrice": 0.0,
  "disclosedQuantity": 0,
  "validity": "DAY"
}
```

### Cancel Order
- **Method & Path**: `DELETE /v2/orders/{order-id}`

### Order Book & Trade Book
- `GET /v2/orders` — All orders placed for the current trading session
- `GET /v2/orders/{order-id}` — Specific order status
- `GET /v2/trades` — All executed trades for the day
- `GET /v2/trades/{order-id}` — Trades belonging to a specific order ID

---

## 4. Portfolio & Positions

### Get Holdings
- **Method & Path**: `GET /v2/holdings`
- Returns long-term equity delivery holdings (CNC/DP).

### Get Positions
- **Method & Path**: `GET /v2/positions`
- Returns open and closed intraday / derivatives positions with MTM and realized/unrealized P&L.

### Convert Position
- **Method & Path**: `POST /v2/positions/convert`
- Converts product type between `INTRADAY` (MIS) and `MARGIN` / `CNC`.

---

## 5. Funds & Margin Calculation

### Get Fund Limits
- **Method & Path**: `GET /v2/fundlimit`
- Returns available cash balance, collateral margin, utilized margin, and payout limits.

### Single Margin Calculator
- **Method & Path**: `POST /v2/margincalculator`
- Returns required margin and available leverage for a single order.

### Basket Margin Calculator (Multi-Leg & Options)
- **Method & Path**: `POST /v2/margincalculator/basket`
- **Payload**:
```json
[
  {
    "exchangeSegment": "NSE_FNO",
    "transactionType": "BUY",
    "quantity": 50,
    "productType": "MARGIN",
    "securityId": "48920",
    "price": 120.5
  },
  {
    "exchangeSegment": "NSE_FNO",
    "transactionType": "SELL",
    "quantity": 50,
    "productType": "MARGIN",
    "securityId": "48925",
    "price": 85.0
  }
]
```
- Returns initial margin, span margin, exposure margin, and hedge benefit.

---

## 6. Market Data & Historical Candles

### Market Quotes (Snapshot REST)
- `POST /v2/marketfeed/ltp` — Quick LTP lookup for up to 1000 instruments
- `POST /v2/marketfeed/ohlc` — OHLC snapshot with previous close
- `POST /v2/marketfeed/quote` — Full quote with 5-depth bid/ask, volume, OI, and circuit limits

### Historical & Intraday Charts
- **Historical Daily Candles**: `POST /v2/charts/historical`
  - Payload: `{"securityId": "1333", "exchangeSegment": "NSE_EQ", "instrument": "EQUITY", "fromDate": "2026-01-01", "toDate": "2026-08-30"}`
- **Intraday Minute Candles**: `POST /v2/charts/intraday`
  - Payload: `{"securityId": "1333", "exchangeSegment": "NSE_EQ", "instrument": "EQUITY", "interval": "1", "fromDate": "2026-08-25 09:15:00", "toDate": "2026-08-29 15:30:00"}`

---

## 7. Option Chain APIs

### Fetch Option Chain
- **Method & Path**: `POST /v2/optionchain`
- **Payload**:
```json
{
  "UnderlyingScrip": 13,
  "UnderlyingSeg": "IDX_I",
  "Expiry": "2026-09-04"
}
```
- Returns complete matrix of Call (CE) and Put (PE) strike prices, LTP, Implied Volatility (IV), Greeks (Delta, Theta, Gamma, Vega), and Open Interest (OI).

### Fetch Expiry List
- **Method & Path**: `POST /v2/optionchain/expirylist`
- **Payload**:
```json
{
  "UnderlyingScrip": 13,
  "UnderlyingSeg": "IDX_I"
}
```

---

## 8. Live Market Feed WebSocket (`wss://api-feed.dhan.co`)

### Binary Protocol Specifications
1. **Connect**: `wss://api-feed.dhan.co`
2. **Authorize (Code 11)**:
```json
{
  "RequestCode": 11,
  "Token": "<ACCESS_TOKEN>",
  "ClientId": "<DHAN_CLIENT_ID>"
}
```
3. **Subscribe Request (Code 21)**:
```json
{
  "RequestCode": 21,
  "InstrumentCount": 1,
  "InstrumentList": [
    {
      "ExchangeSegment": "NSE_EQ",
      "SecurityId": "1333"
    }
  ]
}
```
4. **Subscription Modes**:
   - `Code 2` / `LTP`: Header + Last Traded Price (8 bytes)
   - `Code 4` / `Quote`: Header + OHLC, Volume, OI, Avg Price (50 bytes)
   - `Code 20` / `Full Depth`: Header + 20-Level Bid/Ask Matrix (Packets of ~800 bytes)
   - `Code 21` / `5-Depth`: Header + 5-Level Bid/Ask Matrix (164 bytes)

---

## 9. Exchange Segment Enums & Mappings

| Dhan Segment | Description | OpenAlgo Mapping |
|---|---|---|
| `NSE_EQ` | National Stock Exchange Equity | `NSE` / `NSE_EQ` |
| `NSE_FNO` | National Stock Exchange Futures & Options | `NFO` / `NSE_FNO` |
| `BSE_EQ` | Bombay Stock Exchange Equity | `BSE` / `BSE_EQ` |
| `BSE_FNO` | Bombay Stock Exchange Futures & Options | `BFO` / `BSE_FNO` |
| `MCX_COMM`| Multi Commodity Exchange | `MCX` / `MCX_COMM` |
| `NSE_CURR`| Currency Derivatives | `CDS` / `NSE_CURR` |
| `IDX_I` | Indices (Nifty 50, Sensex, etc.) | `NSE_INDEX` / `BSE_INDEX` |

---

## 10. Product Types & Order Types

### Product Types
- `CNC`: Cash and Carry (Delivery Equity)
- `INTRADAY` (or `MIS`): Intraday Equity / FNO
- `MARGIN` (or `NRML`): Carry-forward Futures & Options
- `CO`: Cover Order
- `BO`: Bracket Order

### Order Types
- `LIMIT`: Limit Order
- `MARKET`: Market Order
- `STOP_LOSS`: Stop Loss Limit (SL-L)
- `STOP_LOSS_MARKET`: Stop Loss Market (SL-M)

---

## 11. Error Codes & Best Practices

| HTTP Status | Dhan Code | Meaning | Action |
|---|---|---|---|
| `200 OK` | `RS-9005` | Success | Parse body payload |
| `400 Bad Request` | `DH-901` | Invalid Parameters / TOTP | Prompt user to verify inputs |
| `401 Unauthorized`| `DH-902` | Token Expired / Invalid | Re-authenticate via `/broker` |
| `429 Too Many Req`| `DH-903` | Rate limit exceeded | Implement exponential backoff |
| `500 Server Error`| `DH-904` | Dhan backend exchange downtime | Retry with circuit breaker |

---

*Document stored in `docs/DHAN_API_V2_REFERENCE.md` for permanent reference across all OpenAlgo broker and market operations.*
