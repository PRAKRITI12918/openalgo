/**
 * global_copilot_widget.js - Persistent Gemini Quantitative Copilot Widget for OpenAlgo
 * 
 * Provides an institutional-grade, floating AI Assistant accessible across all OpenAlgo pages
 * (Dashboard, Orderbook, Tradebook, Positions, Strategy, Tools, etc.)
 */

(function () {
  'use strict';

  // Prevent duplicate initialization
  if (window.__OPENALGO_COPILOT_INITIALIZED__) return;
  window.__OPENALGO_COPILOT_INITIALIZED__ = true;

  const STORAGE_OPEN_KEY = 'oa-global-copilot-open';
  const STORAGE_TAB_KEY = 'oa-global-copilot-tab';

  let isOpen = false;
  let isLoading = false;
  let activeTab = 'copilot';

  // Create and inject styles
  function injectStyles() {
    if (document.getElementById('oa-copilot-styles')) return;

    const style = document.createElement('style');
    style.id = 'oa-copilot-styles';
    style.textContent = `
      /* Global Floating Copilot Widget Styles */
      .oa-copilot-fab {
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 9998;
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 18px;
        border-radius: 9999px;
        background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 50%, #2563eb 100%);
        color: #ffffff;
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 13px;
        font-weight: 700;
        letter-spacing: -0.01em;
        border: 1px solid rgba(255, 255, 255, 0.25);
        box-shadow: 0 8px 24px -4px rgba(124, 58, 237, 0.5), 0 2px 6px rgba(0, 0, 0, 0.2);
        cursor: pointer;
        transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
        user-select: none;
      }
      .oa-copilot-fab:hover {
        transform: translateY(-2px) scale(1.03);
        box-shadow: 0 12px 30px -4px rgba(124, 58, 237, 0.65), 0 4px 10px rgba(0, 0, 0, 0.3);
      }
      .oa-copilot-fab:active {
        transform: translateY(0) scale(0.98);
      }
      .oa-copilot-fab.hidden {
        display: none !important;
      }
      .oa-copilot-fab-pulse {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #4ade80;
        box-shadow: 0 0 10px #4ade80;
        animation: oa-pulse 2s infinite;
      }
      @keyframes oa-pulse {
        0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.7); }
        70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(74, 222, 128, 0); }
        100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(74, 222, 128, 0); }
      }

      /* Slide-Over Drawer */
      .oa-copilot-drawer {
        position: fixed;
        top: 0;
        right: 0;
        bottom: 0;
        width: 440px;
        max-width: 100vw;
        background: #090e1c;
        border-left: 1px solid rgba(255, 255, 255, 0.1);
        box-shadow: -10px 0 40px rgba(0, 0, 0, 0.6);
        z-index: 9999;
        display: flex;
        flex-direction: column;
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        color: #f8fafc;
        transform: translateX(100%);
        transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1);
      }
      .oa-copilot-drawer.open {
        transform: translateX(0);
      }

      /* Drawer Header */
      .oa-drawer-header {
        height: 52px;
        padding: 0 16px;
        background: #050813;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-shrink: 0;
      }
      .oa-drawer-title-group {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .oa-drawer-badge-icon {
        width: 28px;
        height: 28px;
        border-radius: 8px;
        background: linear-gradient(135deg, #9333ea, #6366f1);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
        box-shadow: 0 2px 8px rgba(147, 51, 234, 0.4);
      }
      .oa-drawer-title {
        font-size: 14px;
        font-weight: 800;
        color: #ffffff;
        letter-spacing: -0.01em;
      }
      .oa-model-tag {
        font-size: 10px;
        padding: 2px 6px;
        border-radius: 4px;
        background: rgba(168, 85, 247, 0.15);
        color: #c084fc;
        font-weight: 700;
        border: 1px solid rgba(168, 85, 247, 0.3);
      }

      .oa-drawer-actions {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .oa-icon-btn {
        width: 30px;
        height: 30px;
        border-radius: 6px;
        background: transparent;
        border: none;
        color: #94a3b8;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        font-size: 13px;
        transition: all 0.15s;
      }
      .oa-icon-btn:hover {
        background: rgba(255, 255, 255, 0.08);
        color: #ffffff;
      }

      /* Context Sub-Bar */
      .oa-copilot-context-bar {
        padding: 8px 16px;
        background: rgba(255, 255, 255, 0.02);
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        font-size: 11px;
        font-family: 'JetBrains Mono', monospace;
        display: flex;
        align-items: center;
        justify-content: space-between;
        color: #94a3b8;
        flex-shrink: 0;
      }
      .oa-ctx-val {
        color: #38bdf8;
        font-weight: 600;
      }
      .oa-ctx-broker {
        color: #4ade80;
        font-weight: 600;
      }

      /* Prompt Chips Bar */
      .oa-prompt-chips {
        padding: 8px 14px;
        display: flex;
        gap: 6px;
        overflow-x: auto;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        background: #070b16;
        flex-shrink: 0;
        scrollbar-width: thin;
      }
      .oa-chip-btn {
        padding: 5px 10px;
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 9999px;
        color: #cbd5e1;
        font-size: 11px;
        font-weight: 600;
        white-space: nowrap;
        cursor: pointer;
        transition: all 0.15s;
      }
      .oa-chip-btn:hover {
        background: rgba(192, 132, 252, 0.15);
        border-color: rgba(192, 132, 252, 0.4);
        color: #c084fc;
      }

      /* Chat Messages Scroll Area */
      .oa-chat-messages {
        flex: 1;
        padding: 16px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 12px;
        background: #090e1c;
      }

      .oa-msg-bubble {
        padding: 12px 14px;
        border-radius: 10px;
        font-size: 12.5px;
        line-height: 1.55;
        max-width: 92%;
        word-break: break-word;
      }
      .oa-msg-bubble.assistant {
        background: #111a2e;
        border: 1px solid rgba(255, 255, 255, 0.08);
        color: #e2e8f0;
        align-self: flex-start;
        border-top-left-radius: 2px;
      }
      .oa-msg-bubble.user {
        background: linear-gradient(135deg, #4f46e5, #2563eb);
        color: #ffffff;
        align-self: flex-end;
        border-top-right-radius: 2px;
        font-weight: 500;
      }

      /* Order Confirmation Card */
      .oa-order-card {
        margin-top: 10px;
        padding: 12px;
        border-radius: 8px;
        background: rgba(168, 85, 247, 0.12);
        border: 1px solid rgba(168, 85, 247, 0.35);
      }
      .oa-order-card-title {
        font-weight: 700;
        color: #e9d5ff;
        font-size: 12px;
        margin-bottom: 6px;
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .oa-order-card-body {
        font-size: 11.5px;
        color: #cbd5e1;
        line-height: 1.5;
        font-family: 'JetBrains Mono', monospace;
      }
      .oa-btn-confirm-order {
        margin-top: 10px;
        width: 100%;
        padding: 7px 12px;
        background: #22c55e;
        border: none;
        border-radius: 6px;
        color: #ffffff;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
        transition: background 0.15s;
      }
      .oa-btn-confirm-order:hover {
        background: #16a34a;
      }

      /* Chat Input Form */
      .oa-copilot-input-bar {
        padding: 12px 14px;
        background: #050813;
        border-top: 1px solid rgba(255, 255, 255, 0.08);
        display: flex;
        gap: 8px;
        flex-shrink: 0;
      }
      .oa-copilot-input {
        flex: 1;
        height: 38px;
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 8px;
        padding: 0 12px;
        color: #ffffff;
        font-size: 12.5px;
        font-family: inherit;
        outline: none;
        transition: border-color 0.15s;
      }
      .oa-copilot-input:focus {
        border-color: #c084fc;
        background: rgba(255, 255, 255, 0.08);
      }
      .oa-btn-send {
        width: 38px;
        height: 38px;
        border-radius: 8px;
        background: linear-gradient(135deg, #9333ea, #6366f1);
        border: none;
        color: #ffffff;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        font-weight: 700;
        transition: opacity 0.15s;
      }
      .oa-btn-send:hover {
        opacity: 0.9;
      }
      .oa-btn-send:disabled {
        opacity: 0.4;
        cursor: not-allowed;
      }
    `;
    document.head.appendChild(style);
  }

  // Create DOM Structure
  function createWidgetDOM() {
    if (document.getElementById('oa-global-copilot-container')) return;

    const container = document.createElement('div');
    container.id = 'oa-global-copilot-container';

    // 1. Floating Action Button (FAB)
    const fab = document.createElement('button');
    fab.id = 'oa-copilot-fab';
    fab.className = 'oa-copilot-fab';
    fab.setAttribute('aria-label', 'Open Gemini Copilot Chatbot');
    fab.innerHTML = `
      <span class="oa-copilot-fab-pulse"></span>
      <span>✨ Gemini Copilot</span>
    `;

    // 2. Slide-Over Drawer
    const drawer = document.createElement('aside');
    drawer.id = 'oa-copilot-drawer';
    drawer.className = 'oa-copilot-drawer';
    drawer.innerHTML = `
      <!-- Header -->
      <div class="oa-drawer-header">
        <div class="oa-drawer-title-group">
          <div class="oa-drawer-badge-icon">✨</div>
          <div class="oa-drawer-title">Gemini Copilot</div>
          <span class="oa-model-tag">2.5 Flash</span>
        </div>
        <div class="oa-drawer-actions">
          <button type="button" class="oa-icon-btn" id="oa-copilot-clear" title="Clear Conversation">🗑️</button>
          <button type="button" class="oa-icon-btn" id="oa-copilot-close" title="Close Copilot">✕</button>
        </div>
      </div>

      <!-- Context Sub-Bar -->
      <div class="oa-copilot-context-bar">
        <span>Page: <span class="oa-ctx-val" id="oa-ctx-page">Dashboard</span></span>
        <span>Broker: <span class="oa-ctx-broker" id="oa-ctx-broker">Dhan (1113284554)</span></span>
        <span>Feed: <span class="oa-ctx-val">Active</span></span>
      </div>

      <!-- Quick Analysis Chips -->
      <div class="oa-prompt-chips" id="oa-prompt-chips">
        <button type="button" class="oa-chip-btn" data-prompt="Summarize my account margin, available funds, and capital limits.">💳 Margin & Funds</button>
        <button type="button" class="oa-chip-btn" data-prompt="List all my active open positions and calculate total unrealized P&L.">📊 Active Positions</button>
        <button type="button" class="oa-chip-btn" data-prompt="Analyze BHEL trend, momentum, and technical confluence on 5m chart.">📈 Analyze BHEL</button>
        <button type="button" class="oa-chip-btn" data-prompt="Identify key support, resistance, and pivot levels for NIFTY.">🎯 Support & Resistance</button>
        <button type="button" class="oa-chip-btn" data-prompt="Evaluate Options OI, Max Pain, and Put-Call Ratio for current expiry.">📑 Options OI & PCR</button>
      </div>

      <!-- Messages Area -->
      <div class="oa-chat-messages" id="oa-chat-messages">
        <div class="oa-msg-bubble assistant">
          <p><strong>✨ Welcome to OpenAlgo Quantitative Copilot!</strong></p>
          <p style="margin-top: 4px;">I am integrated with your active workspace and live <strong>Dhan Market Data & Broker APIs</strong>.</p>
          <p style="margin-top: 4px; color: #94a3b8;">Click any quick analysis prompt above or ask any quantitative market query.</p>
        </div>
      </div>

      <!-- Input Form -->
      <form class="oa-copilot-input-bar" id="oa-copilot-form" onsubmit="return false;">
        <input type="text" class="oa-copilot-input" id="oa-copilot-input" placeholder="Ask Gemini about portfolio, chart, or trades..." autocomplete="off" />
        <button type="submit" class="oa-btn-send" id="oa-copilot-send" aria-label="Send query">➤</button>
      </form>
    `;

    container.appendChild(fab);
    container.appendChild(drawer);
    document.body.appendChild(container);

    attachEvents();
  }

  function updateContextLabels() {
    const pageLabel = document.getElementById('oa-ctx-page');
    if (pageLabel) {
      const path = window.location.pathname.replace('/', '') || 'Dashboard';
      pageLabel.textContent = path.charAt(0).toUpperCase() + path.slice(1);
    }
  }

  function openDrawer() {
    const drawer = document.getElementById('oa-copilot-drawer');
    const fab = document.getElementById('oa-copilot-fab');
    if (drawer) drawer.classList.add('open');
    if (fab) fab.classList.add('hidden');
    isOpen = true;
    updateContextLabels();
    try {
      localStorage.setItem(STORAGE_OPEN_KEY, 'true');
    } catch (e) {}
    const input = document.getElementById('oa-copilot-input');
    if (input) setTimeout(() => input.focus(), 150);
  }

  function closeDrawer() {
    const drawer = document.getElementById('oa-copilot-drawer');
    const fab = document.getElementById('oa-copilot-fab');
    if (drawer) drawer.classList.remove('open');
    if (fab) fab.classList.remove('hidden');
    isOpen = false;
    try {
      localStorage.setItem(STORAGE_OPEN_KEY, 'false');
    } catch (e) {}
  }

  function attachEvents() {
    const fab = document.getElementById('oa-copilot-fab');
    const closeBtn = document.getElementById('oa-copilot-close');
    const clearBtn = document.getElementById('oa-copilot-clear');
    const form = document.getElementById('oa-copilot-form');
    const input = document.getElementById('oa-copilot-input');
    const chipsBar = document.getElementById('oa-prompt-chips');

    if (fab) fab.addEventListener('click', openDrawer);
    if (closeBtn) closeBtn.addEventListener('click', closeDrawer);

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        const msgBox = document.getElementById('oa-chat-messages');
        if (msgBox) {
          msgBox.innerHTML = `
            <div class="oa-msg-bubble assistant">
              <p><strong>Chat Cleared.</strong> Ready for your next query.</p>
            </div>
          `;
        }
      });
    }

    if (chipsBar) {
      chipsBar.addEventListener('click', (e) => {
        const btn = e.target.closest('.oa-chip-btn');
        if (!btn) return;
        const prompt = btn.getAttribute('data-prompt');
        if (prompt) sendMessage(prompt);
      });
    }

    if (form) {
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        const text = input ? input.value.trim() : '';
        if (text) {
          input.value = '';
          sendMessage(text);
        }
      });
    }
  }

  async function sendMessage(promptText) {
    const msgBox = document.getElementById('oa-chat-messages');
    const sendBtn = document.getElementById('oa-copilot-send');
    if (!msgBox || isLoading) return;

    // Append user message
    const userMsg = document.createElement('div');
    userMsg.className = 'oa-msg-bubble user';
    userMsg.textContent = promptText;
    msgBox.appendChild(userMsg);
    msgBox.scrollTop = msgBox.scrollHeight;

    // Append loading placeholder
    const loadMsg = document.createElement('div');
    loadMsg.className = 'oa-msg-bubble assistant';
    loadMsg.innerHTML = '<em>Analyzing market feeds & portfolio state with Gemini...</em>';
    msgBox.appendChild(loadMsg);
    msgBox.scrollTop = msgBox.scrollHeight;

    isLoading = true;
    if (sendBtn) sendBtn.disabled = true;

    try {
      const payload = {
        session_id: 'global-copilot-session',
        message: promptText,
        active_symbol: 'BHEL',
        active_timeframe: '5m',
      };

      const res = await fetch('/api/copilot/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

      if (data.status === 'success' || data.response_text) {
        let replyHtml = (data.response_text || data.response || '')
          .replace(/\n/g, '<br>')
          .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

        if (data.order_confirmation) {
          const oc = data.order_confirmation;
          replyHtml += `
            <div class="oa-order-card">
              <div class="oa-order-card-title">🛡️ Confirm Order Execution</div>
              <div class="oa-order-card-body">
                Action: <strong>${oc.action}</strong> | Symbol: <strong>${oc.symbol}</strong><br>
                Qty: <strong>${oc.quantity}</strong> | Type: <strong>${oc.order_type}</strong> (~₹${oc.estimated_price})<br>
                Estimated Value: <strong>₹${Number(oc.estimated_cost).toLocaleString()}</strong>
              </div>
              <button type="button" class="oa-btn-confirm-order" onclick="window.__oaExecuteConfirmedOrder('${oc.token}')">
                Confirm & Place Order
              </button>
            </div>
          `;
        }

        loadMsg.innerHTML = replyHtml;
      } else {
        loadMsg.innerHTML = `<span style="color:#f87171;">Notice: ${data.message || 'Analysis complete.'}</span>`;
      }
    } catch (err) {
      loadMsg.innerHTML = `<span style="color:#f87171;">Error connecting to Gemini Assistant: ${err.message}</span>`;
    } finally {
      isLoading = false;
      if (sendBtn) sendBtn.disabled = false;
      msgBox.scrollTop = msgBox.scrollHeight;
    }
  }

  // Global order execution helper
  window.__oaExecuteConfirmedOrder = async function (token) {
    try {
      const res = await fetch('/api/copilot/execute-confirmed-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token }),
      });
      const data = await res.json();
      alert(data.status === 'SUCCESS' ? `✅ Order Placed Successfully!\nOrder ID: ${data.order_id}` : `❌ Execution Notice:\n${data.message}`);
    } catch (e) {
      alert('Error executing order: ' + e.message);
    }
  };

  // Initialize
  function init() {
    injectStyles();
    createWidgetDOM();

    try {
      const wasOpen = localStorage.getItem(STORAGE_OPEN_KEY) === 'true';
      if (wasOpen) openDrawer();
    } catch (e) {}

    // Listen for SPA navigation (popstate / hashchange / pushState)
    window.addEventListener('popstate', updateContextLabels);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
