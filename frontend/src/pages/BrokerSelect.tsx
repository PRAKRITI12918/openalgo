import { AlertCircle, Check, Eye, EyeOff, KeyRound, Loader2, Lock, ShieldCheck, User } from 'lucide-react'
import { useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuthStore } from '@/stores/authStore'

export default function BrokerSelect() {
  const { user } = useAuthStore()

  // 3 direct Dhan login fields
  const [dhanClientId, setDhanClientId] = useState<string>('')
  const [pin, setPin] = useState<string>('')
  const [totp, setTotp] = useState<string>('')
  const [showPin, setShowPin] = useState<boolean>(false)

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMsg(null)

    const trimmedClientId = dhanClientId.trim()
    const trimmedPin = pin.trim()
    const trimmedTotp = totp.trim()

    if (!trimmedClientId) {
      setError('Please enter your Dhan Client ID.')
      return
    }

    if (!trimmedPin) {
      setError('Please enter your Dhan PIN.')
      return
    }

    if (!trimmedTotp) {
      setError('Please enter your 6-digit TOTP from your authenticator app.')
      return
    }

    setIsSubmitting(true)

    try {
      // 1. Make request to generate access token
      // We invoke the endpoint with dhanClientId, pin, totp
      const response = await fetch('/api/dhan/generate-token', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          dhanClientId: trimmedClientId,
          pin: trimmedPin,
          totp: trimmedTotp,
        }),
      })

      const data = await response.json()

      if (!response.ok || data.status === 'error' || !data.accessToken) {
        const errorMsg =
          data.message ||
          data.errorMessage ||
          'Authentication failed. Please verify your Client ID, PIN, and TOTP.'
        setError(errorMsg)
        setIsSubmitting(false)
        return
      }

      const accessToken = data.accessToken

      // 2. Securely store retrieved token and client ID in browser localStorage
      localStorage.setItem('access-token', accessToken)
      localStorage.setItem('dhan_access_token', accessToken)
      localStorage.setItem('dhan_client_id', trimmedClientId)

      setSuccessMsg('Dhan account authenticated successfully! Redirecting to dashboard...')

      // 3. Redirect to dashboard
      setTimeout(() => {
        window.location.href = data.redirect_url || '/dashboard'
      }, 700)
    } catch (err: any) {
      setError(
        err?.message || 'Unable to connect to Dhan authentication service. Please check your network connection.'
      )
      setIsSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center py-10 px-4 bg-background selection:bg-primary/20">
      <div className="container max-w-5xl">
        <div className="flex flex-col lg:flex-row items-center justify-center gap-8 lg:gap-12">
          
          {/* Information / Branding Sidebar */}
          <div className="w-full lg:w-5/12 max-w-md space-y-6 text-center lg:text-left">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-primary/10 border border-primary/20 text-primary text-xs font-semibold uppercase tracking-wider">
              <ShieldCheck className="h-4 w-4" /> Dhan Direct Authentication
            </div>
            
            <h1 className="text-3xl lg:text-4xl font-extrabold tracking-tight text-foreground">
              Connect Your <span className="bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-transparent">Dhan</span> Account
            </h1>

            <p className="text-muted-foreground text-sm leading-relaxed">
              Authenticate directly with your Dhan credentials to unlock high-speed algorithmic execution, real-time quotes, and option analytics.
            </p>

            <div className="p-4 rounded-xl bg-card border border-border/60 shadow-sm space-y-3 text-left">
              <div className="flex items-start gap-3">
                <div className="p-2 rounded-lg bg-blue-500/10 text-blue-600 dark:text-blue-400 mt-0.5">
                  <KeyRound className="h-4 w-4" />
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-foreground">Zero API Secret Setup</h4>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    No complicated developer app setup. Log in directly with your Client ID, 6-digit PIN, and TOTP.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 mt-0.5">
                  <ShieldCheck className="h-4 w-4" />
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-foreground">Encrypted & Secure</h4>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Session tokens are securely persisted in your browser and automatically attached to all API calls.
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Direct Dhan Login Form Card */}
          <Card className="w-full lg:w-7/12 max-w-md shadow-2xl border-border/80 backdrop-blur-sm bg-card/95">
            <CardHeader className="text-center pb-3">
              <div className="flex justify-center mb-2">
                <div className="h-12 w-12 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center text-white font-bold text-xl shadow-md">
                  D
                </div>
              </div>
              <CardTitle className="text-2xl font-bold tracking-tight">Dhan Login</CardTitle>
              <CardDescription>
                Welcome back{user?.username ? `, ${user.username}` : ''}! Enter your Dhan credentials to proceed.
              </CardDescription>
            </CardHeader>

            <CardContent className="pt-2">
              {error && (
                <Alert variant="destructive" className="mb-4 animate-in fade-in-50">
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle className="font-semibold text-sm">Authentication Failed</AlertTitle>
                  <AlertDescription className="text-xs mt-1">{error}</AlertDescription>
                </Alert>
              )}

              {successMsg && (
                <Alert className="mb-4 border-emerald-500/50 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 animate-in fade-in-50">
                  <Check className="h-4 w-4 text-emerald-500" />
                  <AlertTitle className="font-semibold text-sm">Success</AlertTitle>
                  <AlertDescription className="text-xs mt-1">{successMsg}</AlertDescription>
                </Alert>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                {/* 1. Client ID Field */}
                <div className="space-y-1.5">
                  <Label htmlFor="dhanClientId" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                    <User className="h-3.5 w-3.5 text-primary" /> Client ID
                  </Label>
                  <Input
                    id="dhanClientId"
                    name="dhanClientId"
                    type="text"
                    placeholder="Enter Dhan Client ID (e.g. 1113284554)"
                    value={dhanClientId}
                    onChange={(e) => setDhanClientId(e.target.value)}
                    disabled={isSubmitting}
                    autoComplete="username"
                    required
                    className="h-11 font-mono text-sm"
                  />
                  <p className="text-[11px] text-muted-foreground">
                    Your 10-digit Dhan Client ID.
                  </p>
                </div>

                {/* 2. PIN Field */}
                <div className="space-y-1.5">
                  <Label htmlFor="pin" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                    <Lock className="h-3.5 w-3.5 text-primary" /> Dhan PIN
                  </Label>
                  <div className="relative">
                    <Input
                      id="pin"
                      name="pin"
                      type={showPin ? 'text' : 'password'}
                      placeholder="Enter 6-digit Dhan PIN"
                      value={pin}
                      onChange={(e) => setPin(e.target.value)}
                      disabled={isSubmitting}
                      autoComplete="current-password"
                      maxLength={6}
                      required
                      className="h-11 pr-10 font-mono text-sm tracking-widest"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPin(!showPin)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors p-1"
                      tabIndex={-1}
                      title={showPin ? 'Hide PIN' : 'Show PIN'}
                    >
                      {showPin ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    Your confidential 6-digit trading account PIN.
                  </p>
                </div>

                {/* 3. TOTP Field */}
                <div className="space-y-1.5">
                  <Label htmlFor="totp" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                    <KeyRound className="h-3.5 w-3.5 text-primary" /> Authenticator TOTP
                  </Label>
                  <Input
                    id="totp"
                    name="totp"
                    type="text"
                    inputMode="numeric"
                    placeholder="Enter 6-digit TOTP code"
                    value={totp}
                    onChange={(e) => setTotp(e.target.value)}
                    disabled={isSubmitting}
                    maxLength={6}
                    autoComplete="one-time-code"
                    required
                    className="h-11 font-mono text-sm tracking-widest"
                  />
                  <p className="text-[11px] text-muted-foreground">
                    Time-based OTP from Google Authenticator, Authy, or your 2FA app.
                  </p>
                </div>

                {/* Primary Action Button */}
                <div className="pt-2">
                  <Button
                    type="submit"
                    disabled={isSubmitting}
                    className="w-full h-11 text-sm font-semibold bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white shadow-lg shadow-blue-500/25 transition-all"
                  >
                    {isSubmitting ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Generating Access Token...
                      </>
                    ) : (
                      'Connect Account'
                    )}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

        </div>
      </div>
    </div>
  )
}
