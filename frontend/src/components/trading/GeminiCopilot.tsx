import { useState, useRef, useEffect } from 'react'
import { Sparkles, Trash2, X, Send, Bot, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

interface GeminiCopilotProps {
  isOpen: boolean
  onClose: () => void
  symbol?: string
  exchange?: string
  timeframe?: string
  ltp?: string | number
}

interface Message {
  role: 'user' | 'assistant'
  content: string
}

export function GeminiCopilot({
  isOpen,
  onClose,
  symbol = 'BHEL',
  exchange = 'BSE',
  timeframe = '1m',
  ltp = '416.90',
}: GeminiCopilotProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: `### ✨ Welcome to OpenAlgo Quantitative Copilot!
Connected directly to **${symbol} (${exchange})** on **${timeframe}** with live **Dhan Data API** feeds.
Select a prompt below or ask any quantitative query.`,
    },
  ])
  const [input, setInput] = useState('')
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const quickPrompts = [
    { label: '⚡ Trend & Momentum', prompt: 'Analyze Trend & Momentum for the current chart.' },
    { label: '🎯 Support & Resistance', prompt: 'Identify Key Support & Resistance zones and pivot levels.' },
    { label: '📊 RSI & EMA Confluence', prompt: 'Calculate RSI (14) and EMA 9/21/50/200 confluence.' },
    { label: '🕯️ Candlestick & Vol', prompt: 'Detect Candlestick and Volume breakout patterns.' },
    { label: '📈 Options OI & PCR', prompt: 'Analyze Options OI shifts and Put-Call Ratio (PCR).' },
  ]

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isAnalyzing])

  const handleSend = async (queryText?: string) => {
    const text = (queryText || input).trim()
    if (!text || isAnalyzing) return

    setInput('')
    const newMessages: Message[] = [...messages, { role: 'user', content: text }]
    setMessages(newMessages)
    setIsAnalyzing(true)

    try {
      const payload = {
        message: text,
        symbol: symbol.toUpperCase(),
        exchange: exchange === 'BSE' ? 'BSE_EQ' : 'NSE_EQ',
        timeframe: timeframe.replace('m', ''),
        current_ltp: typeof ltp === 'number' ? ltp : parseFloat(ltp) || 416.90,
        history: newMessages.slice(-6),
      }

      const res = await fetch('/api/chat/trading-assistant', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      const data = await res.json()
      if (res.ok && data.status === 'success') {
        setMessages((prev) => [...prev, { role: 'assistant', content: data.response }])
      } else {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: `⚠️ **Notice**: ${data.message || 'Unable to compute market analysis.'}` },
        ])
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '⚠️ **Connection Error**: Could not reach Gemini AI Assistant endpoint.' },
      ])
    } finally {
      setIsAnalyzing(false)
    }
  }

  if (!isOpen) return null

  return (
    <aside className="flex h-full w-[400px] shrink-0 flex-col border-l border-border bg-[#090f20] transition-all duration-300">
      {/* Header */}
      <header className="flex h-[44px] items-center justify-between border-b border-border/70 px-3 bg-card/30">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-purple-500/20 text-purple-400 border border-purple-500/30">
            <Sparkles className="h-3.5 w-3.5" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-bold text-foreground">Gemini Copilot</span>
              <span className="rounded-full bg-purple-500/10 px-1.5 py-0.2 text-[9px] font-semibold text-purple-400 border border-purple-500/20">
                2.5 Flash
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-muted-foreground hover:text-foreground"
            onClick={() => setMessages([])}
            title="Clear Conversation"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-muted-foreground hover:text-foreground"
            onClick={onClose}
            title="Collapse Copilot"
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      </header>

      {/* Metadata Strip */}
      <div className="flex items-center justify-between border-b border-border/50 bg-black/30 px-3 py-1.5 text-[11px]">
        <div className="flex items-center gap-1">
          <span className="text-muted-foreground">Symbol:</span>
          <span className="font-mono font-bold text-sky-400">{symbol}</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-muted-foreground">Exch:</span>
          <span className="font-mono text-foreground">{exchange}</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-muted-foreground">TF:</span>
          <span className="font-mono text-foreground">{timeframe}</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-muted-foreground">LTP:</span>
          <span className="font-mono font-bold text-emerald-400">₹{ltp}</span>
        </div>
      </div>

      {/* Quick Prompts Bar */}
      <div className="flex gap-1.5 overflow-x-auto border-b border-border/40 p-2 scrollbar-none">
        {quickPrompts.map((qp, idx) => (
          <button
            key={idx}
            type="button"
            className="whitespace-nowrap rounded-full border border-border/60 bg-accent/30 px-2.5 py-1 text-[10px] font-medium text-muted-foreground hover:border-sky-500/50 hover:bg-sky-500/10 hover:text-sky-400 transition-colors"
            onClick={() => handleSend(qp.prompt)}
          >
            {qp.label}
          </button>
        ))}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.map((m, idx) => (
          <div
            key={idx}
            className={cn(
              'flex gap-2 text-xs',
              m.role === 'user' ? 'flex-row-reverse' : 'flex-row'
            )}
          >
            <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/60 border border-border/60 text-[10px]">
              {m.role === 'user' ? <User className="h-3 w-3" /> : <Bot className="h-3 w-3 text-purple-400" />}
            </div>
            <div
              className={cn(
                'max-w-[88%] rounded-lg p-2.5 leading-relaxed whitespace-pre-wrap',
                m.role === 'user'
                  ? 'bg-sky-500/20 text-foreground border border-sky-500/30'
                  : 'bg-accent/40 text-foreground border border-border/60'
              )}
            >
              {m.content}
            </div>
          </div>
        ))}

        {isAnalyzing && (
          <div className="flex gap-2 text-xs">
            <div className="flex h-5 w-5 items-center justify-center rounded-full bg-accent/60 border border-border/60 text-[10px]">
              <Sparkles className="h-3 w-3 text-purple-400 animate-spin" />
            </div>
            <div className="rounded-lg bg-accent/40 p-2.5 text-muted-foreground text-xs italic">
              Analyzing chart data & indicators with Gemini...
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Footer Input */}
      <footer className="border-t border-border/70 p-2 bg-black/40">
        <form
          className="flex items-center gap-1.5 rounded-full border border-border/80 bg-accent/20 px-2.5 py-1 focus-within:border-sky-500"
          onSubmit={(e) => {
            e.preventDefault()
            handleSend()
          }}
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask Gemini about active chart setup..."
            className="h-7 border-0 bg-transparent px-1 text-xs focus-visible:ring-0 placeholder:text-muted-foreground/60 shadow-none"
          />
          <Button
            type="submit"
            size="icon"
            className="h-6 w-6 rounded-full bg-gradient-to-r from-sky-500 to-indigo-500 text-white shrink-0 hover:opacity-90"
            disabled={!input.trim() || isAnalyzing}
          >
            <Send className="h-3 w-3" />
          </Button>
        </form>
      </footer>
    </aside>
  )
}
