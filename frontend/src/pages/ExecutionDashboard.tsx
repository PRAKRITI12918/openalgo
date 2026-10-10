/**
 * Phase 3: Modular Quantitative Trading Terminal & Execution Dashboard.
 * Connects directly to Phase 2 FastAPI backend (http://localhost:8000 / ws://localhost:8000).
 * Dense, institutional trader HUD layout with real-time streaming MTM, options Greeks,
 * multi-account broker management, positions table, multi-leg margin safety sequencing,
 * and risk circuit-breakers.
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
import { OpenPositionsPanel } from '@/components/dashboard/OpenPositionsPanel'
import { AccountSwitcherModal } from '@/components/dashboard/AccountSwitcherModal'
import { BrokerSettingsModal } from '@/components/dashboard/BrokerSettingsModal'
import { SimulateSignalModal } from '@/components/dashboard/SimulateSignalModal'
import { SquareOffModal } from '@/components/dashboard/SquareOffModal'
import { ExecutionPipelineVisualizer } from '@/components/orders/ExecutionPipelineVisualizer'
import { LiveOrderBook } from '@/components/orders/LiveOrderBook'
import { useExecutionWebSocket } from '@/hooks/useExecutionWebSocket'
import { useExecutionStore } from '@/stores/executionStore'

export default function ExecutionDashboard() {
  // Activate dual WebSockets (/ws/market-feed and /ws/executions)
  const { isFullyConnected, marketConnected, executionConnected } =
    useExecutionWebSocket()

  const { refreshAllData } = useExecutionStore()

  const [squareOffOpen, setSquareOffOpen] = useState(false)
  const [simulateSignalOpen, setSimulateSignalOpen] = useState(false)
  const [brokerSettingsOpen, setBrokerSettingsOpen] = useState(false)
  const [accountSwitcherOpen, setAccountSwitcherOpen] = useState(false)

  // Initial sync with backend API on mount
  useEffect(() => {
    refreshAllData()
  }, [refreshAllData])

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col font-sans selection:bg-emerald-500/30 selection:text-emerald-300">
      {/* 1. Global Navigation & Command Bar (with Mock Banner & Multi-Account Switcher) */}
      <GlobalCommandBar
        onOpenSquareOff={() => setSquareOffOpen(true)}
        onOpenSimulateSignal={() => setSimulateSignalOpen(true)}
        onOpenBrokerSettings={() => setBrokerSettingsOpen(true)}
        onOpenAccountSwitcher={() => setAccountSwitcherOpen(true)}
      />

      {/* 2. Main Trader HUD Body */}
      <main className="flex-1 p-3 sm:p-4 md:p-5 flex flex-col gap-4 max-w-[1700px] w-full mx-auto">
        {/* Top Grid: Active Strategies & Pending Approvals (Left) vs Market Watch + MTM Curve (Right) */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Left: Active Strategy Containers & Approval Gate (7 Columns) */}
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

        {/* Middle Section: Open Positions Panel (Account-Scoped Table) */}
        <OpenPositionsPanel />

        {/* Execution Sequencing Pipeline Visualizer */}
        <ExecutionPipelineVisualizer />

        {/* Bottom Section: Real-Time Tabular Order Book */}
        <LiveOrderBook />
      </main>

      {/* 3. Interactive Modals */}
      <AccountSwitcherModal
        open={accountSwitcherOpen}
        onOpenChange={setAccountSwitcherOpen}
        onConnectNewAccount={() => {
          setAccountSwitcherOpen(false)
          setBrokerSettingsOpen(true)
        }}
      />
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
