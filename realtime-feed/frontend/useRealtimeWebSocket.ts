/**
 * High-Performance Real-Time WebSocket Hook for Dashboard Feeds.
 *
 * Implements:
 * 1. Clean connect/disconnect lifecycle (intentional navigation vs network drop)
 * 2. Exponential backoff reconnection with random jitter
 * 3. Prevention of duplicate subscriptions (idempotent client-side registry)
 * 4. Automatic resubscription on reconnect
 * 5. Clean up on unmount (no leaked listeners or dangling connections)
 * 6. High-frequency tick throttling (buffered in ref, flushed at 50ms intervals)
 * 7. Structural MOCK provenance indicator (never displayed as real data)
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  ConnectionStatus,
  FeedSource,
  MarketTickPayload,
  OrderStatusPayload,
  PnlUpdatePayload,
  PositionUpdatePayload,
  RealtimeEnvelope,
  StrategyStatusPayload,
} from './types'

export interface UseRealtimeWebSocketOptions {
  url?: string
  autoConnect?: boolean
  initialChannels?: string[]
  initialSymbols?: string[]
  throttleMs?: number // Default: 50ms flush interval for tick renders
  onTick?: (tick: MarketTickPayload) => void
  onPosition?: (position: PositionUpdatePayload) => void
  onPnl?: (pnl: PnlUpdatePayload) => void
  onOrder?: (order: OrderStatusPayload) => void
  onStrategy?: (strategy: StrategyStatusPayload) => void
}

const DEFAULT_WS_URL =
  (typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss://' : 'ws://') +
  (typeof window !== 'undefined' ? window.location.host : 'localhost:8000') +
  '/ws/realtime'

export function useRealtimeWebSocket(options: UseRealtimeWebSocketOptions = {}) {
  const {
    url = DEFAULT_WS_URL,
    autoConnect = true,
    initialChannels = ['market_tick', 'positions', 'pnl', 'orders', 'strategies'],
    initialSymbols = ['NIFTY', 'BANKNIFTY'],
    throttleMs = 50,
    onTick,
    onPosition,
    onPnl,
    onOrder,
    onStrategy,
  } = options

  const [status, setStatus] = useState<ConnectionStatus>('DISCONNECTED')
  const [feedSource, setFeedSource] = useState<FeedSource>('mock')
  const [isMock, setIsMock] = useState<boolean>(true)

  // Throttled live ticks map: symbol -> MarketTickPayload
  const [ticks, setTicks] = useState<Record<string, MarketTickPayload>>({})
  const [positions, setPositions] = useState<Record<string, PositionUpdatePayload>>({})
  const [pnl, setPnl] = useState<PnlUpdatePayload | null>(null)
  const [recentOrders, setRecentOrders] = useState<OrderStatusPayload[]>([])
  const [strategies, setStrategies] = useState<Record<string, StrategyStatusPayload>>({})

  // Keep latest callbacks in refs to prevent reconnect cycles when caller passes inline functions
  const onTickRef = useRef(onTick)
  const onPositionRef = useRef(onPosition)
  const onPnlRef = useRef(onPnl)
  const onOrderRef = useRef(onOrder)
  const onStrategyRef = useRef(onStrategy)

  useEffect(() => {
    onTickRef.current = onTick
    onPositionRef.current = onPosition
    onPnlRef.current = onPnl
    onOrderRef.current = onOrder
    onStrategyRef.current = onStrategy
  })

  // WebSocket reference
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptRef = useRef<number>(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const shouldReconnectRef = useRef<boolean>(autoConnect)

  // Subscription Registry (Set guarantees zero duplicates)
  const subscribedChannelsRef = useRef<Set<string>>(new Set(initialChannels))
  const subscribedSymbolsRef = useRef<Set<string>>(new Set(initialSymbols.map(s => s.toUpperCase())))

  // Throttling buffer for high-frequency ticks
  const tickBufferRef = useRef<Map<string, MarketTickPayload>>(new Map())
  const throttleTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Flush buffered ticks to state at fixed interval to avoid excessive re-renders
  const flushTickBuffer = useCallback(() => {
    if (tickBufferRef.current.size > 0) {
      setTicks((prev) => {
        const next = { ...prev }
        tickBufferRef.current.forEach((val, key) => {
          next[key] = val
        })
        tickBufferRef.current.clear()
        return next
      })
    }
  }, [])

  // Start throttling flush interval
  useEffect(() => {
    throttleTimerRef.current = setInterval(flushTickBuffer, throttleMs)
    return () => {
      if (throttleTimerRef.current) {
        clearInterval(throttleTimerRef.current)
        throttleTimerRef.current = null
      }
    }
  }, [flushTickBuffer, throttleMs])

  // Send raw JSON message safely
  const sendMessage = useCallback((msg: Record<string, unknown>) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
      return true
    }
    return false
  }, [])

  // Subscribe action: idempotent, prevents duplicate deliveries
  const subscribe = useCallback(
    (channel: string, symbols?: string[]) => {
      const cleanChannel = channel.toLowerCase()
      subscribedChannelsRef.current.add(cleanChannel)

      if (symbols && symbols.length > 0) {
        const cleanSyms = symbols.map(s => s.toUpperCase())
        cleanSyms.forEach(s => subscribedSymbolsRef.current.add(s))
        sendMessage({
          action: 'subscribe',
          channel: cleanChannel,
          symbols: cleanSyms,
        })
      } else {
        sendMessage({
          action: 'subscribe',
          channel: cleanChannel,
        })
      }
    },
    [sendMessage]
  )

  // Unsubscribe action
  const unsubscribe = useCallback(
    (channel: string, symbols?: string[]) => {
      const cleanChannel = channel.toLowerCase()
      if (symbols && symbols.length > 0) {
        const cleanSyms = symbols.map(s => s.toUpperCase())
        cleanSyms.forEach(s => subscribedSymbolsRef.current.delete(s))
        sendMessage({
          action: 'unsubscribe',
          channel: cleanChannel,
          symbols: cleanSyms,
        })
      } else {
        subscribedChannelsRef.current.delete(cleanChannel)
        sendMessage({
          action: 'unsubscribe',
          channel: cleanChannel,
        })
      }
    },
    [sendMessage]
  )

  // Core connection handler
  const connect = useCallback(() => {
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return
    }

    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }

    setStatus(reconnectAttemptRef.current > 0 ? 'RECONNECTING' : 'CONNECTING')

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        setStatus('CONNECTED')
        reconnectAttemptRef.current = 0

        // Synchronize all registered subscriptions immediately upon connection
        subscribedChannelsRef.current.forEach((ch) => {
          const syms = ch === 'market_tick' ? Array.from(subscribedSymbolsRef.current) : undefined
          sendMessage({
            action: 'subscribe',
            channel: ch,
            symbols: syms,
          })
        })
      }

      ws.onmessage = (event) => {
        try {
          const envelope: RealtimeEnvelope = JSON.parse(event.data)
          if (!envelope || !envelope.type) return

          // Update provenance tracking
          if (envelope.source) {
            setFeedSource(envelope.source)
            setIsMock(envelope.source === 'mock')
          }

          // Dispatch by envelope.type without special casing
          switch (envelope.type) {
            case 'market_tick': {
              const payload = envelope.payload as MarketTickPayload
              const sym = payload.symbol || envelope.symbol
              if (sym) {
                // Buffer tick to avoid rendering on every raw tick
                tickBufferRef.current.set(sym, payload)
              }
              onTickRef.current?.(payload)
              break
            }

            case 'position_update': {
              const payload = envelope.payload as PositionUpdatePayload
              if (payload.symbol) {
                setPositions(prev => ({ ...prev, [payload.symbol]: payload }))
              }
              onPositionRef.current?.(payload)
              break
            }

            case 'pnl_update': {
              const payload = envelope.payload as PnlUpdatePayload
              setPnl(payload)
              onPnlRef.current?.(payload)
              break
            }

            case 'order_status': {
              const payload = envelope.payload as OrderStatusPayload
              setRecentOrders(prev => [payload, ...prev.slice(0, 49)])
              onOrderRef.current?.(payload)
              break
            }

            case 'strategy_status': {
              const payload = envelope.payload as StrategyStatusPayload
              if (payload.strategy_id) {
                setStrategies(prev => ({ ...prev, [payload.strategy_id]: payload }))
              }
              onStrategyRef.current?.(payload)
              break
            }

            case 'subscription_ack': {
              const ack = envelope.payload as { is_mock?: boolean }
              if (typeof ack.is_mock === 'boolean') {
                setIsMock(ack.is_mock)
                setFeedSource(ack.is_mock ? 'mock' : 'live')
              }
              break
            }

            default:
              break
          }
        } catch {
          // Ignore malformed JSON frame
        }
      }

      ws.onclose = () => {
        setStatus('DISCONNECTED')
        wsRef.current = null

        if (shouldReconnectRef.current) {
          // Exponential backoff with jitter: 1s, 2s, 4s, 8s, max 15s + 0-500ms jitter
          const attempt = reconnectAttemptRef.current
          const delayMs = Math.min(15000, 1000 * Math.pow(2, attempt)) + Math.floor(Math.random() * 500)
          reconnectAttemptRef.current += 1
          reconnectTimerRef.current = setTimeout(connect, delayMs)
        }
      }

      ws.onerror = () => {
        ws.close()
      }
    } catch {
      setStatus('DISCONNECTED')
      if (shouldReconnectRef.current) {
        reconnectTimerRef.current = setTimeout(connect, 3000)
      }
    }
  }, [url, sendMessage])

  // Disconnect cleanly (intentional unmount or navigation)
  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setStatus('DISCONNECTED')
  }, [])

  // Auto-connect on mount and clean up on unmount
  useEffect(() => {
    if (autoConnect) {
      shouldReconnectRef.current = true
      connect()
    }

    return () => {
      // Clean up on unmount: close socket and cancel timers
      shouldReconnectRef.current = false
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [autoConnect, connect])

  return {
    status,
    isConnected: status === 'CONNECTED',
    isConnecting: status === 'CONNECTING' || status === 'RECONNECTING',
    isMock,
    feedSource,
    ticks,
    positions,
    pnl,
    recentOrders,
    strategies,
    subscribe,
    unsubscribe,
    connect,
    disconnect,
  }
}
