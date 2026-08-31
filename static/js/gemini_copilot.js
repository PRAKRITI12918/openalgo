/**
 * gemini_copilot.js - In-Page Gemini Copilot AI Controller with Responsive Chart Resize & State Persistence
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'oa-trading-copilot-collapsed';

  const state = {
    isCollapsed: false,
    symbol: 'BHEL',
    exchange: 'BSE',
    timeframe: '1',
    ltp: '416.90',
    history: [],
    isAnalyzing: false,
    resizeObserver: null,
  };

  const elements = {
    toggleBtn: document.getElementById('btn-copilot-toggle'),
    closeBtn: document.getElementById('btn-copilot-close'),
    clearBtn: document.getElementById('btn-copilot-clear'),
    panel: document.getElementById('copilot-side-panel'),
    chartArea: document.getElementById('chart-viewport-container'),
    chartWorkspace: document.getElementById('chart-workspace-main'),
    metaSymbol: document.getElementById('copilot-meta-symbol'),
    metaExchange: document.getElementById('copilot-meta-exchange'),
    metaTimeframe: document.getElementById('copilot-meta-timeframe'),
    metaLtp: document.getElementById('copilot-meta-ltp'),
    promptsBar: document.getElementById('copilot-prompts-bar'),
    messagesBox: document.getElementById('copilot-messages-container'),
    form: document.getElementById('copilot-chat-form'),
    input: document.getElementById('copilot-text-input'),
    sendBtn: document.getElementById('copilot-btn-send'),
  };

  function init() {
    restorePersistedState();
    setupContextDetection();
    setupEventListeners();
    setupResizeObserver();
  }

  function restorePersistedState() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved !== null) {
        state.isCollapsed = (saved === 'true');
      }
      if (state.isCollapsed) {
        collapseCopilot(false);
      } else {
        expandCopilot(false);
      }
    } catch (e) {}
  }

  /**
   * Scrape / Detect Context from URL, LocalStorage, or Active Chart Legend
   */
  function setupContextDetection() {
    try {
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('symbol')) state.symbol = urlParams.get('symbol').toUpperCase();
      if (urlParams.get('exchange')) state.exchange = urlParams.get('exchange').toUpperCase();
      if (urlParams.get('timeframe') || urlParams.get('tf')) {
        state.timeframe = urlParams.get('timeframe') || urlParams.get('tf');
      }

      // Check DOM legend if present
      const legendSym = document.querySelector('.legend-symbol');
      if (legendSym && legendSym.textContent) {
        state.symbol = legendSym.textContent.trim().toUpperCase();
      }

      const legendLtp = document.querySelector('.legend-ltp');
      if (legendLtp && legendLtp.textContent) {
        state.ltp = legendLtp.textContent.replace(/[^\d.]/g, '');
      }

      updateMetadataDisplay();
    } catch (e) {
      console.warn('Context detection error:', e);
    }
  }

  function updateMetadataDisplay() {
    if (elements.metaSymbol) elements.metaSymbol.textContent = state.symbol;
    if (elements.metaExchange) elements.metaExchange.textContent = state.exchange;
    if (elements.metaTimeframe) elements.metaTimeframe.textContent = `${state.timeframe}m`;
    if (elements.metaLtp) elements.metaLtp.textContent = `₹${state.ltp}`;
  }

  /**
   * Set up ResizeObserver to auto-adjust chart canvas when Copilot panel expands/collapses
   */
  function setupResizeObserver() {
    if (!elements.chartArea || !window.ResizeObserver) return;

    state.resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        window.dispatchEvent(new Event('resize'));
        if (window.activeTradingChart && typeof window.activeTradingChart.resize === 'function') {
          window.activeTradingChart.resize(width, height);
        }
      }
    });

    state.resizeObserver.observe(elements.chartArea);
  }

  function setupEventListeners() {
    // Toggle Button in Top Toolbar
    if (elements.toggleBtn) {
      elements.toggleBtn.addEventListener('click', toggleCopilot);
    }

    // Close Button inside Copilot Header
    if (elements.closeBtn) {
      elements.closeBtn.addEventListener('click', () => collapseCopilot(true));
    }

    // Clear Conversation Button
    if (elements.clearBtn) {
      elements.clearBtn.addEventListener('click', clearConversation);
    }

    // Chat Form Submit
    if (elements.form) {
      elements.form.addEventListener('submit', (e) => {
        e.preventDefault();
        const text = elements.input.value.trim();
        if (text) {
          elements.input.value = '';
          submitQuery(text);
        }
      });
    }

    // Quick Prompt Chips
    if (elements.promptsBar) {
      elements.promptsBar.addEventListener('click', (e) => {
        const chip = e.target.closest('.copilot-prompt-chip');
        if (chip && chip.dataset.prompt) {
          submitQuery(chip.dataset.prompt);
        }
      });
    }

    // Timeframe Pill Switching
    document.querySelectorAll('.timeframe-pill-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.timeframe-pill-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        state.timeframe = btn.textContent.replace('m', '').trim();
        updateMetadataDisplay();
      });
    });

    // Lifecycle events
    window.addEventListener('pageshow', () => {
      restorePersistedState();
      triggerChartResize();
    });

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) triggerChartResize();
    });
  }

  function toggleCopilot() {
    if (state.isCollapsed) {
      expandCopilot(true);
    } else {
      collapseCopilot(true);
    }
  }

  function expandCopilot(save = true) {
    state.isCollapsed = false;
    if (elements.panel) elements.panel.classList.remove('collapsed');
    if (elements.toggleBtn) elements.toggleBtn.classList.add('active');
    if (save) {
      try { localStorage.setItem(STORAGE_KEY, 'false'); } catch (e) {}
    }
    setupContextDetection();
    triggerChartResize();
    setTimeout(() => elements.input && elements.input.focus(), 200);
  }

  function collapseCopilot(save = true) {
    state.isCollapsed = true;
    if (elements.panel) elements.panel.classList.add('collapsed');
    if (elements.toggleBtn) elements.toggleBtn.classList.remove('active');
    if (save) {
      try { localStorage.setItem(STORAGE_KEY, 'true'); } catch (e) {}
    }
    triggerChartResize();
  }

  function triggerChartResize() {
    window.dispatchEvent(new Event('resize'));
    setTimeout(() => {
      window.dispatchEvent(new Event('resize'));
    }, 220);
  }

  function clearConversation() {
    state.history = [];
    if (elements.messagesBox) {
      elements.messagesBox.innerHTML = `
        <div class="copilot-msg assistant">
          <div class="msg-avatar">✨</div>
          <div class="msg-bubble-wrap">
            <div class="msg-bubble">
              <p><strong>Conversation reset.</strong></p>
              <p>Ready to analyze <strong class="text-cyan">${state.symbol}</strong> using live Dhan Data API feeds.</p>
            </div>
          </div>
        </div>
      `;
    }
  }

  /**
   * Submit Query to Backend Gemini Tool-Calling Analyst
   */
  async function submitQuery(queryText) {
    if (state.isAnalyzing) return;

    if (state.isCollapsed) expandCopilot(true);

    appendUserMsg(queryText);

    const loadingId = appendLoadingMsg();
    state.isAnalyzing = true;
    if (elements.sendBtn) elements.sendBtn.disabled = true;

    try {
      const payload = {
        message: queryText,
        symbol: state.symbol,
        exchange: state.exchange === 'BSE' ? 'BSE_EQ' : 'NSE_EQ',
        timeframe: state.timeframe,
        current_ltp: parseFloat(state.ltp) || 416.90,
      };

      const response = await fetch('/api/chat/trading-assistant', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await response.json();
      removeLoadingMsg(loadingId);

      if (data.status === 'success' || data.response) {
        const reply = data.response || data.reply || '';
        appendAssistantMsg(reply);
        state.history.push({ role: 'user', text: queryText });
        state.history.push({ role: 'assistant', text: reply });
      } else {
        appendAssistantMsg(`⚠️ ${data.message || 'Analysis complete with status notice.'}`);
      }
    } catch (err) {
      removeLoadingMsg(loadingId);
      appendAssistantMsg('⚠️ **Connection Error**: Could not connect to Gemini AI Assistant endpoint.');
    } finally {
      state.isAnalyzing = false;
      if (elements.sendBtn) elements.sendBtn.disabled = false;
      scrollToBottom();
    }
  }

  function appendUserMsg(text) {
    if (!elements.messagesBox) return;
    const wrap = document.createElement('div');
    wrap.className = 'copilot-msg user';
    wrap.innerHTML = `
      <div class="msg-bubble-wrap">
        <div class="msg-bubble">
          <p>${escapeHtml(text)}</p>
        </div>
      </div>
      <div class="msg-avatar user-avatar">U</div>
    `;
    elements.messagesBox.appendChild(wrap);
    scrollToBottom();
  }

  function appendAssistantMsg(rawMarkdown) {
    if (!elements.messagesBox) return;
    const wrap = document.createElement('div');
    wrap.className = 'copilot-msg assistant';
    wrap.innerHTML = `
      <div class="msg-avatar">✨</div>
      <div class="msg-bubble-wrap">
        <div class="msg-bubble">
          ${renderMarkdown(rawMarkdown)}
        </div>
      </div>
    `;
    elements.messagesBox.appendChild(wrap);
    scrollToBottom();
  }

  function appendLoadingMsg() {
    if (!elements.messagesBox) return '';
    const id = `loading-${Date.now()}`;
    const wrap = document.createElement('div');
    wrap.id = id;
    wrap.className = 'copilot-msg assistant';
    wrap.innerHTML = `
      <div class="msg-avatar">✨</div>
      <div class="msg-bubble-wrap">
        <div class="msg-bubble">
          <div class="loading-dots">
            <span class="dot"></span>
            <span class="dot"></span>
            <span class="dot"></span>
          </div>
        </div>
      </div>
    `;
    elements.messagesBox.appendChild(wrap);
    scrollToBottom();
    return id;
  }

  function removeLoadingMsg(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  function scrollToBottom() {
    if (elements.messagesBox) {
      elements.messagesBox.scrollTop = elements.messagesBox.scrollHeight;
    }
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function renderMarkdown(md) {
    if (!md) return '';
    let html = escapeHtml(md);
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    html = html.replace(/`([^`]+)`/g, '<code class="code-pill">$1</code>');
    html = html.replace(/^### (.*$)/gim, '<h4 class="md-heading">$1</h4>');
    html = html.replace(/^## (.*$)/gim, '<h3 class="md-heading">$1</h3>');
    html = html.replace(/^- (.*$)/gim, '<div class="md-bullet">• $1</div>');
    html = html.replace(/\n/g, '<br>');
    return html;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
