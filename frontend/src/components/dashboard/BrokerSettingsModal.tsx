/**
 * Broker Auth & Settings Modal / Drawer.
 * Allows institutional traders to configure Broker Credentials, TOTP Seeds,
 * and Live vs. Sandbox execution mode securely on the client.
 */

import {
  Check,
  Eye,
  EyeOff,
  Key,
  Lock,
  Save,
  Shield,
  Sliders,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { useExecutionStore } from '@/stores/executionStore'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { showToast } from '@/utils/toast'

interface BrokerSettingsModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function BrokerSettingsModal({
  open,
  onOpenChange,
}: BrokerSettingsModalProps) {
  const { brokerCredentials, saveBrokerCredentials, setBrokerStatus } =
    useExecutionStore()

  const [broker, setBroker] = useState(brokerCredentials.broker)
  const [apiKey, setApiKey] = useState(brokerCredentials.apiKey)
  const [apiSecret, setApiSecret] = useState(brokerCredentials.apiSecret)
  const [clientId, setClientId] = useState(brokerCredentials.clientId)
  const [totpSeed, setTotpSeed] = useState(brokerCredentials.totpSeed)
  const [isSandbox, setIsSandbox] = useState(brokerCredentials.isSandbox)
  const [showSecret, setShowSecret] = useState(false)

  const handleSave = () => {
    saveBrokerCredentials({
      broker,
      apiKey,
      apiSecret,
      clientId,
      totpSeed,
      isSandbox,
    })
    setBrokerStatus('CONNECTED')
    showToast.success('Broker credentials saved locally')
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-zinc-950 border-zinc-800 text-zinc-100 max-w-lg font-mono">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-zinc-900 border border-zinc-800">
              <Key className="w-4 h-4 text-emerald-400" />
            </div>
            <div>
              <DialogTitle className="text-base font-bold">
                Broker Connection & Security Settings
              </DialogTitle>
              <DialogDescription className="text-xs text-zinc-400">
                Encrypted in local browser storage. Never sent to public repositories.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="flex flex-col gap-3.5 py-2 text-xs">
          {/* Broker Selection */}
          <div className="flex flex-col gap-1.5">
            <Label className="text-zinc-300">Broker Adapter Target</Label>
            <Select value={broker} onValueChange={setBroker}>
              <SelectTrigger className="bg-zinc-900 border-zinc-800 h-9 text-xs">
                <SelectValue placeholder="Select broker adapter" />
              </SelectTrigger>
              <SelectContent className="bg-zinc-900 border-zinc-800 text-zinc-100 text-xs">
                <SelectItem value="OpenAlgo Mock Broker">
                  OpenAlgo Mock Router (Simulated Latency & Slippage)
                </SelectItem>
                <SelectItem value="OpenAlgo Sandbox API">
                  OpenAlgo Sandbox REST API (Localhost:5000)
                </SelectItem>
                <SelectItem value="Zerodha Kite Connect">
                  Zerodha Kite Connect v3 (Live Adapter)
                </SelectItem>
                <SelectItem value="DhanHQ SuperFast">
                  DhanHQ v2 (Direct DMA API)
                </SelectItem>
                <SelectItem value="Flattrade REST">
                  Flattrade Broker Gateway
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Sandbox Toggle */}
          <div className="flex items-center justify-between p-2.5 rounded-lg bg-zinc-900/60 border border-zinc-800">
            <div className="flex flex-col">
              <span className="font-semibold text-zinc-200">
                Sandbox Execution Mode
              </span>
              <span className="text-[11px] text-zinc-400">
                Run with virtual fills and zero financial risk
              </span>
            </div>
            <Switch checked={isSandbox} onCheckedChange={setIsSandbox} />
          </div>

          {/* Client ID */}
          <div className="flex flex-col gap-1.5">
            <Label className="text-zinc-300">Client / User ID</Label>
            <Input
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              placeholder="e.g. XA9821 / DEMO_USER"
              className="bg-zinc-900 border-zinc-800 h-9 text-xs"
            />
          </div>

          {/* API Key */}
          <div className="flex flex-col gap-1.5">
            <Label className="text-zinc-300">API Key / Token</Label>
            <Input
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="e.g. oa_live_sec_••••••••"
              className="bg-zinc-900 border-zinc-800 h-9 text-xs"
            />
          </div>

          {/* API Secret */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <Label className="text-zinc-300">API Secret / Auth Token</Label>
              <button
                type="button"
                onClick={() => setShowSecret(!showSecret)}
                className="text-[10px] text-zinc-400 hover:text-zinc-200 flex items-center gap-1"
              >
                {showSecret ? (
                  <>
                    <EyeOff className="w-3 h-3" /> Hide
                  </>
                ) : (
                  <>
                    <Eye className="w-3 h-3" /> Show
                  </>
                )}
              </button>
            </div>
            <Input
              type={showSecret ? 'text' : 'password'}
              value={apiSecret}
              onChange={(e) => setApiSecret(e.target.value)}
              placeholder="API Secret key"
              className="bg-zinc-900 border-zinc-800 h-9 text-xs"
            />
          </div>

          {/* TOTP Seed */}
          <div className="flex flex-col gap-1.5">
            <Label className="text-zinc-300">TOTP Authenticator Seed (Optional)</Label>
            <Input
              value={totpSeed}
              onChange={(e) => setTotpSeed(e.target.value)}
              placeholder="Base32 TOTP secret for automated multi-factor authentication"
              className="bg-zinc-900 border-zinc-800 h-9 text-xs"
            />
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            size="sm"
            className="border-zinc-800 hover:bg-zinc-900 text-zinc-400 text-xs"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold"
            onClick={handleSave}
          >
            <Save className="w-3.5 h-3.5 mr-1.5" />
            Save & Connect
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
