import {
  ArrowRightLeft,
  BarChart3,
  BookOpen,
  Check,
  ChevronDown,
  Layers,
  LogOut,
  Menu,
  Moon,
  Newspaper,
  Settings,
  Sparkles,
  Sun,
  User,
  Wrench,
  FileBarChart,
  FileText,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { authApi } from '@/api/auth'
import { LogoutConfirmDialog } from '@/components/auth/LogoutConfirmDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import {
  isActiveRoute,
  mainNavItems,
  moreNavItems,
  reportsNavItems,
} from '@/config/navigation'
import { useProfileMenuItems } from '@/hooks/useProfileMenuItems'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useExecutionStore } from '@/stores/executionStore'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

export function Navbar() {
  const location = useLocation()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [showLogoutDialog, setShowLogoutDialog] = useState(false)

  const { mode, appMode, toggleMode, toggleAppMode, isTogglingMode } = useThemeStore()
  const { user, logout } = useAuthStore()
  const { activeAccount, connectedAccounts, switchAccount, isSwitchingAccount } = useExecutionStore()
  const filteredProfileMenuItems = useProfileMenuItems()

  const handleLogout = async () => {
    try {
      await authApi.logout()
      logout()
      navigate('/login')
      showToast.success('Logged out successfully')
    } catch {
      logout()
      navigate('/login')
    }
  }

  const handleModeToggle = async () => {
    const result = await toggleAppMode()
    if (result.success) {
      const newMode = useThemeStore.getState().appMode
      showToast.success(`Switched to ${newMode === 'live' ? 'Live' : 'Analyze'} mode`)

      if (newMode === 'analyzer') {
        setTimeout(() => {
          showToast.warning('Analyzer (Sandbox) mode is for testing purposes only', undefined, {
            duration: 10000,
          })
        }, 2000)
      }
    } else {
      showToast.error(result.message || 'Failed to toggle mode')
    }
  }

  const isActive = (href: string) => isActiveRoute(location.pathname, href)

  // Check if any child item in dropdown is active
  const isReportsActive = useMemo(
    () => reportsNavItems.some((item) => isActive(item.href)),
    [location.pathname]
  )

  const isMoreActive = useMemo(
    () => moreNavItems.some((item) => isActive(item.href)),
    [location.pathname]
  )

  // Broker display credentials
  const brokerName = useMemo(() => {
    if (activeAccount?.broker_display_name) return activeAccount.broker_display_name
    if (user?.broker) {
      return user.broker.charAt(0).toUpperCase() + user.broker.slice(1).toLowerCase()
    }
    return 'Dhan'
  }, [activeAccount?.broker_display_name, user?.broker])

  const maskedClientId = useMemo(() => {
    if (activeAccount?.masked_external_id) return activeAccount.masked_external_id
    const storedId = localStorage.getItem('dhan_client_id') || user?.username
    if (!storedId) return '••4554'
    const clean = storedId.trim().replace(/^[*•]+/, '')
    if (clean.length <= 4) return `••${clean}`
    return `••${clean.slice(-4)}`
  }, [activeAccount?.masked_external_id, user?.username])

  const handleAccountSwitch = async (accountId: string) => {
    if (accountId === activeAccount?.account_id) return
    const res = await switchAccount(accountId)
    if (res.success) {
      showToast.success(res.message || 'Switched active account')
    } else {
      showToast.error(res.message || 'Failed to switch account')
    }
  }

  return (
    <nav className="sticky top-0 z-50 h-[60px] w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 select-none">
      <div className="mx-auto flex h-full max-w-7xl items-center justify-between px-4 sm:px-6">
        {/* Left side: Logo & Primary Navigation */}
        <div className="flex items-center gap-6 xl:gap-8">
          {/* Mobile hamburger menu (visible < 1100px / xl) */}
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="xl:hidden -ml-2 h-9 w-9 text-muted-foreground hover:text-foreground"
                aria-label="Open mobile menu"
              >
                <Menu className="h-5 w-5" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-80 overflow-y-auto p-0">
              <SheetHeader className="sr-only">
                <SheetTitle>Navigation Menu</SheetTitle>
                <SheetDescription>Main navigation and quick links</SheetDescription>
              </SheetHeader>

              <div className="flex flex-col h-full py-4">
                {/* Drawer Logo Header */}
                <div className="px-5 pb-4 border-b border-border flex items-center justify-between">
                  <Link
                    to="/dashboard"
                    className="flex items-center gap-2.5"
                    onClick={() => setMobileOpen(false)}
                  >
                    <img src="/logo.png" alt="OpenAlgo" className="h-7 w-7 object-contain" />
                    <span className="font-bold text-base tracking-tight text-foreground">
                      OpenAlgo
                    </span>
                  </Link>
                  <Badge variant="outline" className="text-xs font-mono">
                    {brokerName}
                  </Badge>
                </div>

                <div className="flex-1 overflow-y-auto px-3 py-3 space-y-5">
                  {/* Main section */}
                  <div>
                    <div className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Main Navigation
                    </div>
                    <div className="space-y-0.5">
                      {mainNavItems.map((item) => {
                        const active = isActive(item.href)
                        const cls = cn(
                          'flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors min-h-[40px]',
                          active
                            ? 'bg-primary/10 text-primary font-semibold'
                            : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                        )
                        return item.external ? (
                          <a
                            key={item.href}
                            href={item.href}
                            onClick={() => setMobileOpen(false)}
                            className={cls}
                          >
                            {item.label}
                          </a>
                        ) : (
                          <Link
                            key={item.href}
                            to={item.href}
                            onClick={() => setMobileOpen(false)}
                            className={cls}
                          >
                            {item.label}
                          </Link>
                        )
                      })}
                    </div>
                  </div>

                  {/* Reports section */}
                  <div>
                    <div className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Reports
                    </div>
                    <div className="space-y-0.5">
                      {reportsNavItems.map((item) => {
                        const active = isActive(item.href)
                        return (
                          <Link
                            key={item.href}
                            to={item.href}
                            onClick={() => setMobileOpen(false)}
                            className={cn(
                              'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors min-h-[40px]',
                              active
                                ? 'bg-primary/10 text-primary font-semibold'
                                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                            )}
                          >
                            <item.icon className="h-4 w-4 text-muted-foreground" />
                            <span>{item.label}</span>
                          </Link>
                        )
                      })}
                    </div>
                  </div>

                  {/* More section */}
                  <div>
                    <div className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      More
                    </div>
                    <div className="space-y-0.5">
                      {moreNavItems.map((item) => {
                        const active = isActive(item.href)
                        return (
                          <Link
                            key={item.href}
                            to={item.href}
                            onClick={() => setMobileOpen(false)}
                            className={cn(
                              'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors min-h-[40px]',
                              active
                                ? 'bg-primary/10 text-primary font-semibold'
                                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                            )}
                          >
                            <item.icon className="h-4 w-4 text-muted-foreground" />
                            <span>{item.label}</span>
                          </Link>
                        )
                      })}
                    </div>
                  </div>

                  {/* Account / Quick Links */}
                  <div className="border-t border-border pt-3">
                    <div className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Account & Settings
                    </div>
                    <div className="space-y-0.5">
                      <Link
                        to="/profile"
                        onClick={() => setMobileOpen(false)}
                        className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground min-h-[40px]"
                      >
                        <User className="h-4 w-4 text-muted-foreground" />
                        <span>Profile / Portfolio</span>
                      </Link>
                      <Link
                        to="/admin"
                        onClick={() => setMobileOpen(false)}
                        className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground min-h-[40px]"
                      >
                        <Settings className="h-4 w-4 text-muted-foreground" />
                        <span>Settings</span>
                      </Link>
                      <a
                        href="https://docs.openalgo.in"
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={() => setMobileOpen(false)}
                        className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground min-h-[40px]"
                      >
                        <BookOpen className="h-4 w-4 text-muted-foreground" />
                        <span>Documentation</span>
                      </a>
                    </div>
                  </div>
                </div>

                {/* Mobile Drawer Footer: Mode Switch & Logout */}
                <div className="px-4 pt-3 border-t border-border flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleModeToggle}
                      disabled={isTogglingMode}
                      className={cn(
                        'text-xs font-semibold px-2.5 py-1 rounded-md border flex items-center gap-1.5 transition-colors',
                        appMode === 'live'
                          ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-400'
                          : 'border-amber-500/40 bg-amber-500/15 text-amber-400'
                      )}
                    >
                      <span
                        className={cn(
                          'h-1.5 w-1.5 rounded-full',
                          appMode === 'live' ? 'bg-emerald-400' : 'bg-amber-400'
                        )}
                      />
                      <span>{appMode === 'live' ? 'Live' : 'Paper'}</span>
                    </button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-foreground"
                      onClick={toggleMode}
                      disabled={appMode !== 'live'}
                      aria-label="Toggle theme"
                    >
                      {mode === 'light' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                    </Button>
                  </div>

                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive hover:bg-destructive/10 text-xs gap-1.5"
                    onClick={() => {
                      setMobileOpen(false)
                      setShowLogoutDialog(true)
                    }}
                  >
                    <LogOut className="h-3.5 w-3.5" />
                    <span>Logout</span>
                  </Button>
                </div>
              </div>
            </SheetContent>
          </Sheet>

          {/* Logo (Always visible and never overlaps) */}
          <Link
            to="/dashboard"
            className="flex items-center gap-2.5 shrink-0 focus-visible:outline-none"
          >
            <img src="/logo.png" alt="OpenAlgo Logo" className="h-7 w-7 shrink-0 object-contain" />
            <span className="font-bold text-base tracking-tight text-foreground whitespace-nowrap">
              OpenAlgo
            </span>
            <span className="rounded bg-red-600 px-1.5 py-0.5 text-[10px] font-mono font-bold text-white uppercase tracking-wider">
              NAV-TEST
            </span>
          </Link>

          {/* Desktop Navigation Items (Visible from 1100px / xl up) */}
          <div className="hidden xl:flex items-center gap-1">
            {/* 5 Main Text-Only Visible Items */}
            {mainNavItems.map((item) => {
              const active = isActive(item.href)
              const linkClasses = cn(
                'px-3 py-1.5 rounded-md text-sm font-medium transition-all relative',
                active
                  ? 'bg-primary/10 text-primary font-semibold after:absolute after:bottom-[-2px] after:left-3 after:right-3 after:h-[2px] after:bg-primary after:rounded-full'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              )

              return item.external ? (
                <a key={item.href} href={item.href} className={linkClasses}>
                  {item.label}
                </a>
              ) : (
                <Link key={item.href} to={item.href} className={linkClasses}>
                  {item.label}
                </Link>
              )
            })}

            {/* "Reports" Dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className={cn(
                    'flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-medium transition-all cursor-pointer focus-visible:outline-none',
                    isReportsActive
                      ? 'bg-primary/10 text-primary font-semibold'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  )}
                  aria-label="Reports menu"
                >
                  <span>Reports</span>
                  <ChevronDown className="h-3.5 w-3.5 text-muted-foreground transition-transform duration-200" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-48 rounded-lg shadow-lg border border-border">
                {reportsNavItems.map((item) => {
                  const active = isActive(item.href)
                  return (
                    <DropdownMenuItem
                      key={item.href}
                      onSelect={() => navigate(item.href)}
                      className={cn(
                        'cursor-pointer flex items-center gap-2.5 text-sm py-2',
                        active && 'bg-primary/10 text-primary font-medium'
                      )}
                    >
                      <item.icon className="h-4 w-4 text-muted-foreground" />
                      <span>{item.label}</span>
                    </DropdownMenuItem>
                  )
                })}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* "More" Dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className={cn(
                    'flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-medium transition-all cursor-pointer focus-visible:outline-none',
                    isMoreActive
                      ? 'bg-primary/10 text-primary font-semibold'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  )}
                  aria-label="More options menu"
                >
                  <span>More</span>
                  <ChevronDown className="h-3.5 w-3.5 text-muted-foreground transition-transform duration-200" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-52 rounded-lg shadow-lg border border-border">
                {moreNavItems.map((item) => {
                  const active = isActive(item.href)
                  return (
                    <DropdownMenuItem
                      key={item.href}
                      onSelect={() => navigate(item.href)}
                      className={cn(
                        'cursor-pointer flex items-center gap-2.5 text-sm py-2',
                        active && 'bg-primary/10 text-primary font-medium'
                      )}
                    >
                      <item.icon className="h-4 w-4 text-muted-foreground" />
                      <span>{item.label}</span>
                    </DropdownMenuItem>
                  )
                })}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {/* Right side controls */}
        <div className="flex items-center gap-2 sm:gap-3">
          {/* Broker Chip with Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex items-center gap-1.5 sm:gap-2 rounded-md border border-border/80 bg-background/80 hover:bg-muted/70 px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer focus-visible:outline-none"
                title={`Active broker: ${brokerName} (${maskedClientId})`}
                aria-label={`Broker ${brokerName} ${maskedClientId}`}
              >
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                </span>
                <span className="font-semibold text-foreground tracking-tight">{brokerName}</span>
                <span className="text-muted-foreground font-mono text-[11px] hidden sm:inline">
                  {maskedClientId}
                </span>
                <ChevronDown className="h-3 w-3 text-muted-foreground shrink-0" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64 rounded-lg shadow-lg border border-border p-1.5">
              <DropdownMenuLabel className="text-xs font-semibold px-2 py-1.5 text-muted-foreground uppercase tracking-wider">
                Active Broker Account
              </DropdownMenuLabel>
              <div className="px-2 py-1.5 rounded-md bg-muted/40 mb-1">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-foreground flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
                    {brokerName}
                  </span>
                  <Badge variant="outline" className="text-[10px] text-emerald-400 border-emerald-500/30">
                    Connected
                  </Badge>
                </div>
                <div className="text-xs font-mono text-muted-foreground mt-0.5">
                  Client ID: {maskedClientId}
                </div>
              </div>

              {/* Multi-broker account list (extensible) */}
              {connectedAccounts.length > 1 && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuLabel className="text-xs font-semibold px-2 py-1 text-muted-foreground uppercase tracking-wider">
                    Switch Connected Account
                  </DropdownMenuLabel>
                  <div className="space-y-0.5">
                    {connectedAccounts.map((acc) => {
                      const isCurrent = acc.account_id === activeAccount?.account_id
                      return (
                        <DropdownMenuItem
                          key={acc.account_id}
                          disabled={isSwitchingAccount}
                          onSelect={() => handleAccountSwitch(acc.account_id)}
                          className="flex items-center justify-between cursor-pointer py-1.5"
                        >
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium">{acc.broker_display_name}</span>
                            <span className="text-[11px] font-mono text-muted-foreground">
                              {acc.masked_external_id}
                            </span>
                          </div>
                          {isCurrent && <Check className="h-3.5 w-3.5 text-emerald-400" />}
                        </DropdownMenuItem>
                      )
                    })}
                  </div>
                </>
              )}

              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => navigate('/profile')}
                className="cursor-pointer text-xs py-2"
              >
                <ArrowRightLeft className="h-3.5 w-3.5 mr-2 text-muted-foreground" />
                <span>Manage broker accounts</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Live / Paper Switch (Two-state Segmented Control) */}
          <div
            className="inline-flex items-center rounded-md border border-border/80 bg-muted/40 p-0.5"
            role="radiogroup"
            aria-label="Trading environment switch"
          >
            {/* Live Option */}
            <button
              type="button"
              onClick={appMode === 'analyzer' ? handleModeToggle : undefined}
              disabled={isTogglingMode}
              className={cn(
                'flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-all cursor-pointer focus-visible:outline-none',
                appMode === 'live'
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-semibold shadow-xs'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'
              )}
              title="Live Trading Mode"
              aria-checked={appMode === 'live'}
              role="radio"
            >
              {isTogglingMode && appMode !== 'live' ? (
                <div className="h-2.5 w-2.5 animate-spin rounded-full border border-current border-t-transparent" />
              ) : (
                <span
                  className={cn(
                    'h-1.5 w-1.5 rounded-full transition-opacity',
                    appMode === 'live' ? 'bg-emerald-400' : 'bg-transparent'
                  )}
                />
              )}
              <span>Live</span>
            </button>

            {/* Paper Option */}
            <button
              type="button"
              onClick={appMode === 'live' ? handleModeToggle : undefined}
              disabled={isTogglingMode}
              className={cn(
                'flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-all cursor-pointer focus-visible:outline-none',
                appMode === 'analyzer'
                  ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30 font-semibold shadow-xs'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'
              )}
              title="Paper / Analyzer Sandbox Mode"
              aria-checked={appMode === 'analyzer'}
              role="radio"
            >
              {isTogglingMode && appMode === 'live' ? (
                <div className="h-2.5 w-2.5 animate-spin rounded-full border border-current border-t-transparent" />
              ) : (
                <span
                  className={cn(
                    'h-1.5 w-1.5 rounded-full transition-opacity',
                    appMode === 'analyzer' ? 'bg-amber-400' : 'bg-transparent'
                  )}
                />
              )}
              <span>Paper</span>
            </button>
          </div>

          {/* Theme Toggle (Sun / Moon) */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted/70"
            onClick={toggleMode}
            disabled={appMode !== 'live'}
            title={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
            aria-label="Toggle theme"
          >
            {mode === 'light' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>

          {/* Avatar Menu */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="h-8 w-8 rounded-full bg-primary/20 text-primary border border-primary/30 hover:bg-primary/30 transition-colors flex items-center justify-center font-semibold text-xs cursor-pointer focus-visible:outline-none"
                aria-label="Open user profile menu"
              >
                <span>{user?.username?.[0]?.toUpperCase() || 'O'}</span>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56 rounded-lg shadow-lg border border-border">
              <div className="px-3 py-2 border-b border-border/60">
                <p className="text-xs font-semibold text-foreground truncate">
                  {user?.username || 'Trader'}
                </p>
                <p className="text-[11px] text-muted-foreground capitalize">
                  {brokerName} Connected
                </p>
              </div>

              {/* Main Avatar Menu Items */}
              <DropdownMenuItem
                onSelect={() => navigate('/profile')}
                className="cursor-pointer flex items-center py-2"
              >
                <User className="h-4 w-4 mr-2.5 text-muted-foreground" />
                <span>Profile / Portfolio</span>
              </DropdownMenuItem>

              <DropdownMenuItem
                onSelect={() => navigate('/admin')}
                className="cursor-pointer flex items-center py-2"
              >
                <Settings className="h-4 w-4 mr-2.5 text-muted-foreground" />
                <span>Settings</span>
              </DropdownMenuItem>

              <DropdownMenuItem asChild className="cursor-pointer flex items-center py-2">
                <a
                  href="https://docs.openalgo.in"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center"
                >
                  <BookOpen className="h-4 w-4 mr-2.5 text-muted-foreground" />
                  <span>Documentation</span>
                </a>
              </DropdownMenuItem>

              <DropdownMenuSeparator />

              {/* Logout Option */}
              <DropdownMenuItem
                onSelect={() => setShowLogoutDialog(true)}
                className="cursor-pointer text-destructive focus:text-destructive flex items-center py-2"
              >
                <LogOut className="h-4 w-4 mr-2.5 text-destructive" />
                <span>Logout</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Confirmation Dialog on Logout */}
      <LogoutConfirmDialog
        open={showLogoutDialog}
        onOpenChange={setShowLogoutDialog}
        onConfirm={handleLogout}
      />
    </nav>
  )
}
