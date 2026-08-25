/**
 * Phase 3: Modular Quantitative Trading Terminal & Execution Dashboard.
 * Connects directly to Phase 2 FastAPI backend (http://localhost:8000 / ws://localhost:8000).
 * Dense, institutional trader HUD layout with real-time streaming MTM, options Greeks,
 * multi-leg margin safety sequencing, and risk circuit-breakers.
 */

import {
  Activity,
  AlertCircle,
  BarChart3,
  Cpu,
  Layers,
  Radio,
  RefreshCw,
  Shield,
  Sparkles,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { GlobalCommandBar } from '@/components/dashboard/GlobalCommandBar'
import { IntradayMtmChart } from '@/components/dashboard/IntradayMtmChart'
import { MarketWatchGreeksPanel } from '@/components/dashboard/MarketWatchGreeksPanel'
import { StrategyCardsView } from '@/components/dashboard/StrategyCardsView'
import { BrokerSettingsModal } from '@/components/dashboard/BrokerSettingsModal'
import { SimulateSignalModal } from '@/components/dashboard/SimulateSignalModal'
import { SquareOffModal } from '@/components/dashboard/SquareOffModal'
import { ExecutionPipelineVisualizer } from '@/components/orders/ExecutionPipelineVisualizer'
import { LiveOrderBook } from '@/components/orders/LiveOrderBook'
import { useExecutionWebSocket } from '@/hooks/useExecutionWebSocket'
import { executionApi } from '@/services/executionApi'
import { useExecutionStore } from '@/stores/executionStore'

export default function ExecutionDashboard() {
  // Activate dual WebSockets (/ws/market-feed and /ws/executions)
  const { isFullyConnected, marketConnected, executionConnected } =
    useExecutionWebSocket()

  const { updateFunds, updatePositionsFromBroker } = useExecutionStore()

  const [squareOffOpen, setSquareOffOpen] = useState(false)
  const [simulateSignalOpen, setSimulateSignalOpen] = useState(false)
  const [brokerSettingsOpen, setBrokerSettingsOpen] = useState(false)

  // Initial sync with backend API on mount
  useEffect(() => {
    async function loadInitialData() {
      try {
        const [funds, positions] = await Promise.allSettled([
          executionApi.getFunds(),
          executionApi.getPositions(),
        ])

        if (funds.status === 'fulfilled' && funds.value.available_funds) {
          updateFunds(
            funds.value.available_funds,
            funds.value.utilized_margin,
            funds.value.total_funds
          )
        }
        if (positions.status === 'fulfilled' && positions.value) {
          updatePositionsFromBroker(positions.value)
        }
      } catch {
        // Backend optional fallback
      }
    }

    loadInitialData()
  }, [updateFunds, updatePositionsFromBroker])

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col font-sans selection:bg-emerald-500/30 selection:text-emerald-300">
      {/* 1. Global Navigation & Command Bar */}
      <GlobalCommandBar
        onOpenSquareOff={() => setSquareOffOpen(true)}
        onOpenSimulateSignal={() => setSimulateSignalOpen(true)}
        onOpenBrokerSettings={() => setBrokerSettingsOpen(true)}
      />

      {/* 2. Main Trader HUD Body */}
      <main className="flex-1 p-3 sm:p-4 md:p-5 flex flex-col gap-4 max-w-[1700px] w-full mx-auto">
        {/* Top Grid: Active Strategies (Left) & Market Watch + MTM Chart (Right) */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Left: Active Strategy Containers & Approvals (7 Columns) */}
          <div className="lg:col-span-7 flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Cpu className="w-4 h-4 text-emerald-400" />
                <h2 className="font-mono font-bold text-sm text-zinc-100 uppercase tracking-wider">
                  Active Strategy Containers (AOS Multi-Leg Engine)
                </h2>
              </div>
            </div>

            <StrategyCardsView />
          </div>

          {/* Right: Live Market Watch, Greeks & MTM Curve (5 Columns) */}
          <div className="lg:col-span-5 flex flex-col gap-4">
            <MarketWatchGreeksPanel />
            <IntradayMtmChart />
          </div>
        </div>

        {/* Middle Section: 4-Step Margin-Safe Execution Pipeline Visualizer */}
        <ExecutionPipelineVisualizer />

        {/* Bottom Section: Real-Time Tabular Order Book */}
        <LiveOrderBook />
      </main>

      {/* 3. Interactive Modals */}
      <SquareOffModal
        open={squareOffOpen}
        onOpenChange={setSquareOffOpen}
      />
      <SimulateSignalModal
        open={simulateSignalOpen}
        onOpenChange={setSimulateSignalOpen}
      />
      <BrokerSettingsModal
        open={brokerSettingsOpen}
        onOpenChange={setBrokerSettingsOpen}
      />
    </div>
  )
}
