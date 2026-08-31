import React, { useState, useEffect, useRef } from 'react';
import styles from './CopilotPanel.module.css';

const SESSION_STORAGE_KEY = 'oa_copilot_session_id';
const HISTORY_STORAGE_KEY = 'oa_copilot_chat_history';
const TOGGLE_STORAGE_KEY = 'copilot_sidebar_open';

export function CopilotPanel({
  isOpen = true,
  onClose,
  activeSymbol = 'BHEL',
  activeTimeframe = '5m',
}) {
  const [sessionId] = useState(() => {
    try {
      let id = localStorage.getItem(SESSION_STORAGE_KEY);
      if (!id) {
        id = 'sess_' + Math.random().toString(36).substring(2, 9);
        localStorage.setItem(SESSION_STORAGE_KEY, id);
      }
      return id;
    } catch {
      return 'sess_default';
    }
  });

  const [messages, setMessages] = useState(() => {
    try {
      const saved = localStorage.getItem(HISTORY_STORAGE_KEY);
      if (saved) return JSON.parse(saved);
    } catch {}
    return [
      {
        id: 'welcome',
        role: 'assistant',
        text: '### ✨ Welcome to Quantitative Copilot\n\nConnected to live **Dhan Market Data API** and **Gemini 2.5 Flash**.\n\nAsk any question regarding technical setups, key levels, or request trade intents with 2-step confirmation safety.',
        timestamp: new Date().toLocaleTimeString(),
      },
    ];
  });

  const [inputVal, setInputVal] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);

  // Sync message history to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(messages));
    } catch {}
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const handleSendMessage = async (queryText) => {
    const text = (queryText || inputVal).trim();
    if (!text || isLoading) return;

    const userMsg = {
      id: `user_${Date.now()}`,
      role: 'user',
      text,
      timestamp: new Date().toLocaleTimeString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputVal('');
    setIsLoading(true);

    try {
      const response = await fetch('/api/copilot/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message: text,
          active_symbol: activeSymbol,
          active_timeframe: activeTimeframe,
        }),
      });

      const data = await response.json();

      const assistantMsg = {
        id: `assistant_${Date.now()}`,
        role: 'assistant',
        text: data.response_text || data.message || 'Analysis complete.',
        dataPayload: data.data_payload,
        orderConfirmation: data.order_confirmation,
        timestamp: new Date().toLocaleTimeString(),
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err_${Date.now()}`,
          role: 'assistant',
          text: '⚠️ **Connection Error**: Could not reach Copilot API. Verify backend server is running.',
          timestamp: new Date().toLocaleTimeString(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleConfirmOrder = async (msgId, orderPayload) => {
    if (!orderPayload || !orderPayload.token) return;

    try {
      const res = await fetch('/api/copilot/execute-confirmed-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          token: orderPayload.token,
        }),
      });

      const result = await res.json();

      setMessages((prev) =>
        prev.map((msg) => {
          if (msg.id === msgId) {
            return {
              ...msg,
              orderConfirmation: null, // clear card
              executionResult: result,
            };
          }
          return msg;
        })
      );
    } catch (err) {
      alert('Error executing order: ' + err.message);
    }
  };

  const handleClearHistory = () => {
    const welcome = [
      {
        id: 'welcome_' + Date.now(),
        role: 'assistant',
        text: '### 🗑️ Chat Cleared\n\nReady for your next query on **' + activeSymbol + '**.',
        timestamp: new Date().toLocaleTimeString(),
      },
    ];
    setMessages(welcome);
    try {
      localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(welcome));
    } catch {}
  };

  const renderMarkdown = (md) => {
    if (!md) return '';
    let html = md
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.1);padding:1px 4px;border-radius:3px;">$1</code>')
      .replace(/^### (.*$)/gim, '<h4 style="margin:4px 0 6px;color:#f8fafc;font-size:13px;">$1</h4>')
      .replace(/^#### (.*$)/gim, '<h5 style="margin:4px 0 4px;color:#cbd5e1;font-size:12px;">$1</h5>')
      .replace(/^• (.*$)/gim, '<div style="margin-left:8px;margin-bottom:2px;">• $1</div>')
      .replace(/\n/g, '<br>');
    return html;
  };

  if (!isOpen) return null;

  return (
    <aside className={styles.copilotPanel}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.brandGroup}>
          <div className={styles.brandIcon}>✨</div>
          <span className={styles.titleText}>Quant Copilot</span>
          <span className={styles.symbolTag}>{activeSymbol}</span>
        </div>

        <div className={styles.headerActions}>
          <button
            className={styles.actionBtn}
            onClick={handleClearHistory}
            title="Clear Chat History"
          >
            🗑️
          </button>
          <button
            className={styles.actionBtn}
            onClick={onClose}
            title="Collapse Sidebar"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Quick Prompt Chips */}
      <div className={styles.chipsContainer}>
        <button
          className={styles.chip}
          onClick={() => handleSendMessage(`Summarize trend and momentum for ${activeSymbol}.`)}
        >
          ⚡ Summarize Trend
        </button>
        <button
          className={styles.chip}
          onClick={() => handleSendMessage('Check available account margin & funds.')}
        >
          💳 Check Margin
        </button>
        <button
          className={styles.chip}
          onClick={() => handleSendMessage('Show active open positions.')}
        >
          📊 Show Positions
        </button>
        <button
          className={styles.chip}
          onClick={() => handleSendMessage(`Identify key support & resistance for ${activeSymbol}.`)}
        >
          🎯 Support & Resistance
        </button>
      </div>

      {/* Message Stream */}
      <div className={styles.messageStream}>
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`${styles.bubble} ${
              msg.role === 'user' ? styles.bubbleUser : styles.bubbleAssistant
            }`}
          >
            <div
              dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.text) }}
            />

            {/* Render 2-Step Trade Confirmation Card */}
            {msg.orderConfirmation && (
              <div className={styles.tradeCard}>
                <div className={styles.tradeTitle}>
                  <span>🛡️</span>
                  <span>Confirm Order Execution</span>
                </div>
                <div className={styles.tradeDetails}>
                  <div>Action: <strong>{msg.orderConfirmation.action}</strong></div>
                  <div>Symbol: <strong>{msg.orderConfirmation.symbol}</strong> ({msg.orderConfirmation.exchange})</div>
                  <div>Quantity: <strong>{msg.orderConfirmation.quantity}</strong></div>
                  <div>Type: <strong>{msg.orderConfirmation.order_type}</strong> (~₹{msg.orderConfirmation.estimated_price})</div>
                  <div>Estimated Cost: <strong>₹{msg.orderConfirmation.estimated_cost?.toLocaleString()}</strong></div>
                  <div style={{ color: '#4ade80', marginTop: 4 }}>
                    ✅ {msg.orderConfirmation.risk_check_message}
                  </div>
                </div>
                <div className={styles.tradeActions}>
                  <button
                    className={styles.btnConfirm}
                    onClick={() => handleConfirmOrder(msg.id, msg.orderConfirmation)}
                  >
                    Confirm & Execute Order
                  </button>
                  <button
                    className={styles.btnCancel}
                    onClick={() =>
                      setMessages((prev) =>
                        prev.map((m) =>
                          m.id === msg.id ? { ...m, orderConfirmation: null } : m
                        )
                      )
                    }
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Render Execution Status after confirmation */}
            {msg.executionResult && (
              <div style={{
                marginTop: 8,
                padding: '8px 10px',
                borderRadius: 6,
                background: msg.executionResult.status === 'SUCCESS' ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
                border: '1px solid ' + (msg.executionResult.status === 'SUCCESS' ? 'rgba(34,197,94,0.4)' : 'rgba(239,68,68,0.4)'),
                color: msg.executionResult.status === 'SUCCESS' ? '#86efac' : '#fca5a5',
                fontSize: 11
              }}>
                <strong>{msg.executionResult.status === 'SUCCESS' ? '✅ Executed' : '❌ Execution Notice'}:</strong> {msg.executionResult.message}
                {msg.executionResult.order_id && <div>Order ID: <code>{msg.executionResult.order_id}</code></div>}
              </div>
            )}
          </div>
        ))}

        {isLoading && (
          <div className={`${styles.bubble} ${styles.bubbleAssistant}`}>
            <em style={{ color: '#c084fc' }}>Analyzing market data and generating reasoning...</em>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Bar */}
      <form
        className={styles.inputArea}
        onSubmit={(e) => {
          e.preventDefault();
          handleSendMessage();
        }}
      >
        <input
          type="text"
          className={styles.inputField}
          placeholder={`Ask Gemini about ${activeSymbol} or market setups...`}
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
        />
        <button
          type="submit"
          className={styles.sendBtn}
          disabled={isLoading || !inputVal.trim()}
        >
          ➤
        </button>
      </form>
    </aside>
  );
}

export default CopilotPanel;
