import { BookOpen, Check, ExternalLink, Eye, EyeOff, Info, Loader2, Plus, RefreshCw, UserCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useAuthStore } from '@/stores/authStore'

// All supported brokers with their display names and auth types
const allBrokers = [
  { id: 'fivepaisa', name: '5 Paisa', authType: 'totp' },
  { id: 'fivepaisaxts', name: '5 Paisa (XTS)', authType: 'totp' },
  { id: 'aliceblue', name: 'Alice Blue', authType: 'totp' },
  { id: 'angel', name: 'Angel One', authType: 'totp' },
  { id: 'arrow', name: 'Arrow', authType: 'oauth' },
  { id: 'compositedge', name: 'CompositEdge', authType: 'oauth' },
  { id: 'dhan', name: 'Dhan', authType: 'oauth' },
  { id: 'deltaexchange', name: 'Delta Exchange', authType: 'totp' },
  { id: 'indmoney', name: 'IndMoney', authType: 'totp' },
  { id: 'dhan_sandbox', name: 'Dhan (Sandbox)', authType: 'totp' },
  { id: 'definedge', name: 'Definedge', authType: 'totp' },
  { id: 'firstock', name: 'Firstock', authType: 'totp' },
  { id: 'flattrade', name: 'Flattrade', authType: 'oauth' },
  { id: 'motilal', name: 'Motilal Oswal', authType: 'totp' },
  { id: 'fyers', name: 'Fyers', authType: 'oauth' },
  { id: 'groww', name: 'Groww', authType: 'totp' },
  { id: 'hdfcsecurities', name: 'HDFC Securities', authType: 'oauth' },
  { id: 'hdfcsky', name: 'HDFC Sky', authType: 'oauth' },
  { id: 'ibulls', name: 'Ibulls', authType: 'totp' },
  { id: 'iifl', name: 'IIFL', authType: 'totp' },
  { id: 'iiflcapital', name: 'IIFL Capital', authType: 'oauth' },
  { id: 'jainamxts', name: 'JainamXts', authType: 'totp' },
  { id: 'kotak', name: 'Kotak Securities', authType: 'totp' },
  { id: 'mstock', name: 'mStock by Mirae Asset', authType: 'totp' },
  { id: 'nubra', name: 'Nubra', authType: 'totp' },
  { id: 'paytm', name: 'Paytm Money', authType: 'oauth' },
  { id: 'pocketful', name: 'Pocketful', authType: 'oauth' },
  { id: 'rmoney', name: 'RMoney', authType: 'oauth' },
  { id: 'samco', name: 'Samco', authType: 'totp' },
  { id: 'shoonya', name: 'Shoonya', authType: 'totp' },
  { id: 'tradejini', name: 'Tradejini', authType: 'totp' },
  { id: 'tradesmart', name: 'TradeSmart', authType: 'oauth' },
  { id: 'upstox', name: 'Upstox', authType: 'oauth' },
  { id: 'wisdom', name: 'Wisdom Capital', authType: 'totp' },
  { id: 'zebu', name: 'Zebu', authType: 'totp' },
  { id: 'zerodha', name: 'Zerodha', authType: 'oauth' },
] as const

interface BrokerConfig {
  broker_name: string
  broker_api_key: string
  redirect_url: string
}

interface AccountProfile {
  name: string
  broker: string
  client_id: string
  api_key_masked: string
  redirect_url: string
  description: string
  is_active: boolean
}

// Helper function to get Flattrade API key
function getFlattradeApiKey(fullKey: string): string {
  if (!fullKey) return ''
  const parts = fullKey.split(':::')
  return parts.length > 1 ? parts[1] : fullKey
}

// Generate random state for OAuth
function generateRandomState(): string {
  const length = 16
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  let result = ''
  for (let i = 0; i < length; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  return result
}

// Get CSRF Token
async function getCSRFToken(): Promise<string> {
  try {
    const res = await fetch('/auth/csrf-token', { credentials: 'include' })
    const data = await res.json()
    return data.csrf_token || ''
  } catch {
    return ''
  }
}

export default function BrokerSelect() {
  const { user } = useAuthStore()
  const [selectedBroker, setSelectedBroker] = useState<string>('')
  const [apiKey, setApiKey] = useState<string>('')
  const [apiSecret, setApiSecret] = useState<string>('')
  const [profileName, setProfileName] = useState<string>('')
  const [showSecret, setShowSecret] = useState<boolean>(false)

  const [profiles, setProfiles] = useState<AccountProfile[]>([])
  const [selectedProfileName, setSelectedProfileName] = useState<string>('custom')
  const [activeProfile, setActiveProfile] = useState<string>('')

  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [brokerConfig, setBrokerConfig] = useState<BrokerConfig | null>(null)

  // Fetch initial config & saved profiles
  const loadData = async () => {
    try {
      const [cfgRes, profRes] = await Promise.all([
        fetch('/auth/broker-config', { credentials: 'include' }),
        fetch('/api/broker/profiles', { credentials: 'include' }),
      ])

      const cfgData = await cfgRes.json()
      if (cfgData.status === 'success') {
        setBrokerConfig(cfgData)
        setSelectedBroker(cfgData.broker_name || 'zerodha')
        if (cfgData.broker_api_key) {
          setApiKey(cfgData.broker_api_key)
        }
      }

      const profData = await profRes.json()
      if (profData.status === 'success' && profData.data) {
        const profileList = profData.data.profiles || []
        setProfiles(profileList)
        setActiveProfile(profData.data.active_profile || '')

        const currentActive = profileList.find((p: AccountProfile) => p.is_active || p.name === profData.data.active_profile)
        if (currentActive) {
          setSelectedProfileName(currentActive.name)
          setSelectedBroker(currentActive.broker)
          setApiKey(currentActive.api_key_masked)
          setApiSecret('************')
          setProfileName(currentActive.name)
        }
      }
    } catch {
      setError('Failed to load broker configuration')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  // Handle switching selected saved profile
  const handleProfileChange = (val: string) => {
    setSelectedProfileName(val)
    if (val === 'custom') {
      setProfileName('')
      setApiKey('')
      setApiSecret('')
    } else {
      const prof = profiles.find((p) => p.name === val)
      if (prof) {
        setSelectedBroker(prof.broker)
        setApiKey(prof.api_key_masked)
        setApiSecret('************')
        setProfileName(prof.name)
      }
    }
  }

  // Handle broker dropdown change
  const handleBrokerChange = (newBroker: string) => {
    setSelectedBroker(newBroker)
    setSelectedProfileName('custom')
    setApiKey('')
    setApiSecret('')
    setProfileName(`${newBroker}_main`)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMsg(null)

    if (!selectedBroker) {
      setError('Please select a broker')
      return
    }

    setIsSubmitting(true)

    try {
      const csrfToken = await getCSRFToken()

      // Case 1: Switching to an existing saved profile
      if (selectedProfileName !== 'custom' && selectedProfileName !== activeProfile) {
        const switchRes = await fetch('/api/broker/profiles/switch', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
          },
          credentials: 'include',
          body: JSON.stringify({ name: selectedProfileName, restart_server: false }),
        })
        const switchData = await switchRes.json()
        if (switchData.status !== 'success') {
          setError(switchData.message || 'Failed to switch profile')
          setIsSubmitting(false)
          return
        }
      } 
      // Case 2: Saving new or updated credentials
      else if (apiKey && apiSecret && apiSecret !== '************') {
        const pName = profileName.trim() || `${selectedBroker}_${Date.now().toString().slice(-4)}`
        const saveRes = await fetch('/api/broker/profiles/save', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
          },
          credentials: 'include',
          body: JSON.stringify({
            name: pName,
            broker: selectedBroker,
            api_key: apiKey,
            api_secret: apiSecret,
            make_active: true,
            restart_server: false,
          }),
        })
        const saveData = await saveRes.json()
        if (saveData.status !== 'success') {
          setError(saveData.message || 'Failed to save credentials')
          setIsSubmitting(false)
          return
        }
      }

      // Determine redirect URL
      const currentApiKey = (apiKey && apiKey !== '************') ? apiKey : (brokerConfig?.broker_api_key || '')
      const redirectUrl = `http://127.0.0.1:5000/${selectedBroker}/callback`
      let loginUrl = ''

      switch (selectedBroker) {
        case 'fivepaisa':
        case 'fivepaisaxts':
        case 'aliceblue':
        case 'angel':
        case 'mstock':
        case 'indmoney':
        case 'deltaexchange':
        case 'jainamxts':
        case 'dhan_sandbox':
        case 'definedge':
        case 'firstock':
        case 'samco':
        case 'motilal':
        case 'nubra':
        case 'groww':
        case 'ibulls':
        case 'iifl':
        case 'kotak':
        case 'rmoney':
        case 'shoonya':
        case 'tradejini':
        case 'tradesmart':
        case 'wisdom':
        case 'zebu':
          loginUrl = `/${selectedBroker}/callback`
          break

        case 'iiflcapital':
          loginUrl = '/iiflcapital/callback'
          break

        case 'dhan':
          loginUrl = '/dhan/initiate-oauth'
          break

        case 'compositedge':
          loginUrl = `https://xts.compositedge.com/interactive/thirdparty?appKey=${currentApiKey}&returnURL=${redirectUrl}`
          break

        case 'flattrade': {
          const flattradeApiKey = getFlattradeApiKey(currentApiKey)
          loginUrl = `https://auth.flattrade.in/?app_key=${flattradeApiKey}`
          break
        }

        case 'fyers':
          loginUrl = `https://api-t1.fyers.in/api/v3/generate-authcode?client_id=${currentApiKey}&redirect_uri=${redirectUrl}&response_type=code&state=2e9b44629ebb28226224d09db3ffb47c`
          break

        case 'upstox':
          loginUrl = `https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id=${currentApiKey}&redirect_uri=${redirectUrl}`
          break

        case 'zerodha':
          loginUrl = `https://kite.trade/connect/login?api_key=${currentApiKey}`
          break

        case 'arrow':
          loginUrl = `https://app.arrow.trade/app/login?appID=${currentApiKey}`
          break

        case 'hdfcsecurities':
          loginUrl = `https://developer.hdfcsec.com/oapi/v1/login?api_key=${currentApiKey}`
          break

        case 'hdfcsky':
          loginUrl = `https://developer.hdfcsky.com/oapi/v1/login?api_key=${currentApiKey}`
          break

        case 'paytm':
          loginUrl = `https://login.paytmmoney.com/merchant-login?apiKey=${currentApiKey}&state={default}`
          break

        case 'pocketful': {
          const state = generateRandomState()
          localStorage.setItem('pocketful_oauth_state', state)
          const scope = 'orders holdings'
          loginUrl = `https://trade.pocketful.in/oauth2/auth?client_id=${currentApiKey}&redirect_uri=${redirectUrl}&response_type=code&scope=${encodeURIComponent(scope)}&state=${encodeURIComponent(state)}`
          break
        }

        default:
          loginUrl = `/${selectedBroker}/callback`
          break
      }

      setSuccessMsg('Connecting to broker...')
      setTimeout(() => {
        window.location.href = loginUrl
      }, 300)

    } catch (err: any) {
      setError(err?.message || 'An error occurred while connecting')
      setIsSubmitting(false)
    }
  }

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    )
  }

  const selectedBrokerObj = allBrokers.find((b) => b.id === selectedBroker)

  return (
    <div className="min-h-screen flex items-center justify-center py-8 px-4">
      <div className="container max-w-6xl">
        <div className="flex flex-col lg:flex-row items-center justify-between gap-8 lg:gap-16">
          {/* Right side broker form - Shown first on mobile */}
          <Card className="w-full max-w-lg shadow-xl order-1 lg:order-2">
            <CardHeader className="text-center pb-4">
              <div className="flex justify-center mb-3">
                <img src="/logo.png" alt="OpenAlgo" className="h-16 w-16" />
              </div>
              <CardTitle className="text-2xl font-bold">Connect Your Trading Account</CardTitle>
              <CardDescription>
                Welcome, <span className="font-medium text-foreground">{user?.username}</span>!
              </CardDescription>
            </CardHeader>
            <CardContent>
              {error && (
                <Alert variant="destructive" className="mb-4">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              {successMsg && (
                <Alert className="mb-4 border-green-500/50 bg-green-500/10 text-green-700 dark:text-green-400">
                  <Check className="h-4 w-4 text-green-500" />
                  <AlertDescription>{successMsg}</AlertDescription>
                </Alert>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                {/* Saved Profiles Switcher */}
                {profiles.length > 0 && (
                  <div className="space-y-1.5 p-3 rounded-lg bg-muted/40 border border-border/50">
                    <div className="flex items-center justify-between">
                      <Label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                        <UserCheck className="h-3.5 w-3.5" /> Saved Account Profiles
                      </Label>
                      {activeProfile && (
                        <span className="text-[11px] font-medium text-green-600 dark:text-green-400 bg-green-500/10 px-2 py-0.5 rounded-full">
                          Active: {activeProfile}
                        </span>
                      )}
                    </div>
                    <Select
                      value={selectedProfileName}
                      onValueChange={handleProfileChange}
                      disabled={isSubmitting}
                    >
                      <SelectTrigger className="w-full h-9">
                        <SelectValue placeholder="Select Saved Account Profile" />
                      </SelectTrigger>
                      <SelectContent>
                        {profiles.map((p) => (
                          <SelectItem key={p.name} value={p.name}>
                            <div className="flex items-center justify-between w-full gap-2">
                              <span className="font-medium">{p.name}</span>
                              <span className="text-xs text-muted-foreground uppercase">({p.broker})</span>
                              {p.is_active && <span className="text-xs text-green-600 dark:text-green-400 ml-auto font-bold">• Active</span>}
                            </div>
                          </SelectItem>
                        ))}
                        <SelectItem value="custom">
                          <span className="text-primary font-medium flex items-center gap-1">
                            <Plus className="h-3.5 w-3.5" /> + Configure New Account / Broker
                          </span>
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {/* Broker Selection Dropdown */}
                <div className="space-y-1.5">
                  <Label htmlFor="broker-select" className="text-sm font-medium">
                    Login with your Broker
                  </Label>
                  <Select
                    value={selectedBroker}
                    onValueChange={handleBrokerChange}
                    disabled={isSubmitting}
                  >
                    <SelectTrigger id="broker-select" className="w-full h-10">
                      <SelectValue placeholder="Select a Broker" />
                    </SelectTrigger>
                    <SelectContent className="max-h-72">
                      {allBrokers.map((broker) => (
                        <SelectItem key={broker.id} value={broker.id}>
                          {broker.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* Broker Credentials Fields */}
                {selectedBroker && (
                  <div className="space-y-3 pt-2 border-t border-border/50">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                      {selectedBrokerObj?.name?.toUpperCase() || selectedBroker.toUpperCase()} Credentials
                    </h3>

                    {/* Profile Name (optional tag) */}
                    {selectedProfileName === 'custom' && (
                      <div className="space-y-1">
                        <Label htmlFor="profile-name" className="text-xs text-muted-foreground">
                          Account Profile Name (Optional)
                        </Label>
                        <Input
                          id="profile-name"
                          placeholder={`e.g. ${selectedBroker}_primary`}
                          value={profileName}
                          onChange={(e) => setProfileName(e.target.value)}
                          disabled={isSubmitting}
                          className="h-9 text-sm"
                        />
                      </div>
                    )}

                    {/* API Key */}
                    <div className="space-y-1">
                      <Label htmlFor="api-key" className="text-xs text-muted-foreground">
                        {selectedBroker === 'dhan' || selectedBroker === 'flattrade'
                          ? 'API Key (Format: client_id:::api_key)'
                          : selectedBroker === 'fivepaisa'
                          ? 'API Key (Format: User_Key:::User_ID:::client_id)'
                          : 'API Key / App ID'}
                      </Label>
                      <Input
                        id="api-key"
                        placeholder={
                          selectedBroker === 'dhan'
                            ? '1113284554:::a6cb4035'
                            : selectedBroker === 'zerodha'
                            ? 'Enter Kite API Key'
                            : 'Enter API Key'
                        }
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        disabled={isSubmitting}
                        className="h-9 text-sm"
                      />
                    </div>

                    {/* API Secret */}
                    <div className="space-y-1">
                      <Label htmlFor="api-secret" className="text-xs text-muted-foreground">
                        API Secret / App Secret
                      </Label>
                      <div className="relative">
                        <Input
                          id="api-secret"
                          type={showSecret ? 'text' : 'password'}
                          placeholder="Enter API Secret"
                          value={apiSecret}
                          onChange={(e) => setApiSecret(e.target.value)}
                          disabled={isSubmitting}
                          className="h-9 text-sm pr-9"
                        />
                        <button
                          type="button"
                          onClick={() => setShowSecret(!showSecret)}
                          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                          tabIndex={-1}
                        >
                          {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Broker Specific Notices */}
                {selectedBroker === 'zerodha' && (
                  <Alert className="border-amber-500/50 bg-amber-500/10 py-2">
                    <Info className="h-4 w-4 text-amber-500" />
                    <AlertDescription className="text-xs text-amber-700 dark:text-amber-400">
                      Zerodha requires an active Kite Connect data subscription for market data access.
                    </AlertDescription>
                  </Alert>
                )}

                {selectedBroker === 'dhan' && (
                  <Alert className="border-amber-500/50 bg-amber-500/10 py-2">
                    <Info className="h-4 w-4 text-amber-500" />
                    <AlertDescription className="text-xs text-amber-700 dark:text-amber-400">
                      Dhan requires an active Data API subscription for market data access.
                    </AlertDescription>
                  </Alert>
                )}

                {/* Action Button */}
                <Button
                  type="submit"
                  className="w-full h-10 mt-2 font-medium"
                  disabled={!selectedBroker || isSubmitting}
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Saving & Connecting...
                    </>
                  ) : (
                    <>
                      <ExternalLink className="mr-2 h-4 w-4" />
                      Save & Connect Account
                    </>
                  )}
                </Button>
              </form>
            </CardContent>
          </Card>

          {/* Left side content - Shown second on mobile */}
          <div className="flex-1 max-w-xl text-center lg:text-left order-2 lg:order-1">
            <h1 className="text-4xl lg:text-5xl font-bold mb-6">
              Connect Your <span className="text-primary">Broker</span>
            </h1>
            <p className="text-lg lg:text-xl mb-8 text-muted-foreground">
              Link or switch between your trading accounts to start executing algorithmic trades seamlessly through OpenAlgo.
            </p>

            <Alert className="mb-6">
              <BookOpen className="h-4 w-4" />
              <AlertTitle>Need Help?</AlertTitle>
              <AlertDescription>Check our documentation for broker setup guides and API keys.</AlertDescription>
            </Alert>

            <div className="flex justify-center lg:justify-start gap-4">
              <Button variant="outline" asChild>
                <a href="https://docs.openalgo.in" target="_blank" rel="noopener noreferrer">
                  <BookOpen className="mr-2 h-4 w-4" />
                  Documentation
                </a>
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
