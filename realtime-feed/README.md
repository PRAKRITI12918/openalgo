# Real-Time WebSocket Updates & Feed Streaming Module

Institutional-grade, low-latency WebSocket layer connecting backend data producers
(market feeds, order execution engine, position/P&L aggregators) to frontend trading
dashboards with strict provenance isolation and fail-closed safety guards.

---

## 1. How the Requirements Map to Code

| # | Requirement | Implementation | Location |
|---|---|---|---|
| **1** | **Backend WebSocket Server** | `RealtimeWebSocketManager` managing client lifecycle, dynamic channel subscriptions, and automated dead-socket cleanup. | [`src/connection_manager.py`](src/connection_manager.py) |
| **2** | **Frontend Client / Hook** | `useRealtimeWebSocket` hook with auto-reconnect, exponential backoff, client-side deduplication, and cleanup on unmount. | [`frontend/useRealtimeWebSocket.ts`](frontend/useRealtimeWebSocket.ts) |
| **3** | **Mock Tick Generation** | `MockTickGenerator` emitting realistic multi-asset ticks and quote spreads with guaranteed `source: "mock"`. | [`src/mock_tick_generator.py`](src/mock_tick_generator.py) |
| **4** | **Structural Separation of Mock vs Live** | `MockFeedProvider`, `SandboxFeedProvider`, and `LiveFeedProvider` as distinct classes behind `create_feed_provider()` factory. | [`src/feed_provider.py`](src/feed_provider.py) |
| **5** | **UI Mock Provenance Indicator** | `FeedModeIndicator` component rendering distinct badges for MOCK, SANDBOX, LIVE, and OFFLINE states. | [`frontend/FeedModeIndicator.tsx`](frontend/FeedModeIndicator.tsx) |
| **6** | **Never Display Mock as Live** | Non-negotiable rule enforced via `FeedSource` enum stamped on every event envelope and checked in tests. | [`src/types.py`](src/types.py) |
| **7** | **Explicit LIVE Mode Guard** | `LiveFeedProvider` throws `LiveFeedNotConfiguredError` unless constructed with explicit `live_feed_enabled: true` and an injected client. | [`src/feed_provider.py`](src/feed_provider.py) |
| **8** | **No Silent Fallback to Live** | `create_feed_provider()` fails closed with `InvalidFeedModeError` on unrecognized modes. | [`src/feed_provider.py`](src/feed_provider.py) |
| **9** | **Structured JSON Envelopes** | Universal `{ type, timestamp, source, payload }` envelope formatted by `EventDispatcher` across all 5 core trading streams. | [`src/event_dispatcher.py`](src/event_dispatcher.py) |
| **10** | **LTP Stream** | `market_tick` events with LTP, bid, ask, open, high, low, change, volume. | [`src/event_dispatcher.py`](src/event_dispatcher.py) |
| **11** | **Positions Stream** | `position_update` events with quantity, average price, current price, unrealized & realized P&L. | [`src/event_dispatcher.py`](src/event_dispatcher.py) |
| **12** | **P&L Stream** | `pnl_update` events with account-level and per-strategy aggregate P&L. | [`src/event_dispatcher.py`](src/event_dispatcher.py) |
| **13** | **Order Status Stream** | `order_status` events with full lifecycle transitions (`PLACED`, `FILLED`, `PARTIAL`, `REJECTED`, `CANCELLED`). | [`src/event_dispatcher.py`](src/event_dispatcher.py) |
| **14** | **Strategy Status Stream** | `strategy_status` events with operational status (`RUNNING`, `PAUSED`, `STOPPED`, `ERROR`). | [`src/event_dispatcher.py`](src/event_dispatcher.py) |
| **15** | **Prevent Duplicate Subscriptions** | `RealtimeWebSocketManager` and `useRealtimeWebSocket` store subscriptions in Sets, ensuring idempotent registration and no double-delivery. | [`src/connection_manager.py`](src/connection_manager.py) |
| **16** | **Unmount & Disconnect Cleanup** | Immediate cleanup of client subscription sets on disconnect/unmount, preventing orphaned listeners and memory leaks. | [`src/connection_manager.py`](src/connection_manager.py) |
| **17** | **Avoid Excessive Re-Renders** | `useRealtimeWebSocket` buffers incoming ticks in a ref and flushes to state on a 50ms interval (20fps). | [`frontend/useRealtimeWebSocket.ts`](frontend/useRealtimeWebSocket.ts) |

---

## 2. Data-Source Matrix (Mock Mode vs. Real Mode)

Where every piece of data originates in this implementation versus in production deployment:

| Data Type | MOCK Mode Implementation | Real Deployment (SANDBOX / LIVE Mode) |
|---|---|---|
| **LTP (`market_tick`)** | `MockTickGenerator` / `MockFeedProvider`<br>• Deterministic Geometric Brownian drift<br>• Guaranteed `source: "mock"`<br>• Zero network I/O | `LiveFeedProvider` / Broker WebSocket Stream<br>• Direct feed from broker exchange gateway (e.g. Dhan, Zerodha, Upstox via OpenAlgo)<br>• Injected `live_client`<br>• Tagged with `source: "live"` |
| **Positions (`position_update`)** | `EventDispatcher.format_position_update()`<br>• Generated from in-memory strategy engine simulation<br>• Tagged `source: "mock"` | `BrokerAdapter.get_positions()` / Exchange fill events<br>• Reconciled with live broker trade books<br>• Tagged `source: "live"` or `"sandbox"` |
| **P&L (`pnl_update`)** | `EventDispatcher.format_pnl_update()`<br>• Aggregated from mock strategy container legs and mark-to-market calculations | Portfolio Engine / Broker Ledger Stream<br>• Live unrealized and realized P&L based on confirmed broker fills and tick LTPs |
| **Order Status (`order_status`)** | `ExecutionSequenceEngine` simulated execution<br>• Emits `PLACED` → `FILLED` (or simulated partial/reject)<br>• Tagged `source: "mock"` | Broker Order Stream / Exchange WebSocket<br>• Real execution confirmations routed through `OpenAlgoBrokerAdapter`<br>• Tagged `source: "live"` or `"sandbox"` |
| **Strategy Status (`strategy_status`)** | Internal state transitions (`AOS_NIFTY_IC_01`, `RUNNING`, `PAUSED`, `ERROR`)<br>• Tagged `source: "mock"` | Strategy Engine Execution Container<br>• Live risk monitors, delta-neutral hedging loops, circuit-breaker triggers |

---

## 3. Directory Layout

```
realtime-feed/
├── src/
│   ├── __init__.py               # Re-exports all core providers, managers, and types
│   ├── types.py                  # FeedMode, FeedSource, RealtimeEnvelope, typed errors
│   ├── mock_tick_generator.py    # Synthetic tick generation with source="mock"
│   ├── feed_provider.py          # AbstractBaseFeedProvider, Mock/Sandbox/Live providers, factory
│   ├── connection_manager.py     # RealtimeWebSocketManager (channels, symbols, deduplication)
│   └── event_dispatcher.py       # Standardized { type, timestamp, source, payload } formatters
├── frontend/
│   ├── types.ts                  # TypeScript schemas and payload interfaces
│   ├── useRealtimeWebSocket.ts   # React hook: auto-reconnect, dedupe, cleanup, tick throttle
│   └── FeedModeIndicator.tsx     # Provenance visual badge component (MOCK vs LIVE)
├── tests/
│   └── test_realtime_websocket.py# 10 comprehensive async test scenarios
└── README.md                     # Requirements mapping and data-source matrix
```

---

## 4. Test Scenarios Covered

The test suite in [`tests/test_realtime_websocket.py`](tests/test_realtime_websocket.py) verifies:
1. **Normal Tick Flow**: Validates `{ type, timestamp, source, payload }` envelope and `source: "mock"` tag.
2. **Reconnect-After-Drop**: Verifies server cleans up dropped sockets and re-synchronizes on client reconnect.
3. **Duplicate-Subscribe Prevention**: Client subscribing to same channel/symbol multiple times never receives duplicate events.
4. **Unmount / Disconnect Cleanup**: Disconnecting a client immediately purges all tracking structures.
5. **Strict Provenance Gating**: Proves mock output is NEVER delivered when feed is configured for live mode (and vice versa).
6. **Structured Envelopes**: All 5 event types (`market_tick`, `position_update`, `pnl_update`, `order_status`, `strategy_status`) verified.
7. **Fail-Closed LIVE Mode**: Constructing LIVE provider without explicit config or client throws `LiveFeedNotConfiguredError`.
8. **Valid LIVE Mode**: Allowed only when explicitly configured with valid client.
9. **Unknown Mode Fails Closed**: Unrecognized mode strings throw `InvalidFeedModeError` instead of falling back.
10. **Inbound Client Actions**: Subscribe, unsubscribe, and ping/heartbeat commands parsed and executed dynamically.
