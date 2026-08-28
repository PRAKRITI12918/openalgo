/**
 * gemini_copilot.js - In-Page Gemini Copilot AI Controller with Responsive Chart Resize
 */

(function () {
  'use strict';

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
    setupContextDetection();
    setupEventListeners();
    setupResizeObserver();
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
        // Dispatch window resize event for TradingView / Lightweight-Charts canvas
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
      elements.closeBtn.addEventListener('click', collapseCopilot);
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
      btn.addEventListener('click', (e) => {
        document.querySelectorAll('.timeframe-pill-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        state.timeframe = btn.textContent.replace('m', '').trim();
        updateMetadataDisplay();
      });
    });
  }

  function toggleCopilot() {
    if (state.isCollapsed) {
      expandCopilot();
    } else {
      collapseCopilot();
    }
  }

  function expandCopilot() {
    state.isCollapsed = false;
    elements.panel.classList.remove('collapsed');
    if (elements.toggleBtn) elements.toggleBtn.classList.add('active');
    setupContextDetection();
    triggerChartResize();
    setTimeout(() => elements.input && elements.input.focus(), 200);
  }

  function collapseCopilot() {
    state.isCollapsed = true;
    elements.panel.classList.add('collapsed');
    if (elements.toggleBtn) elements.toggleBtn.classList.remove('active');
    triggerChartResize();
  }

  function triggerChartResize() {
    setTimeout(() => {
      window.dispatchEvent(new Event('resize'));
    }, 150);
  }

  function clearConversation() {
    state.history = [];
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

  /**
   * Submit Query to Backend Gemini Tool-Calling Analyst
   */
  async function submitQuery(queryText) {
    if (state.isAnalyzing) return;

    // Ensure panel is open
    if (state.isCollapsed) expandCopilot();

    appendUserMsg(queryText);
    state.history.push({ role: 'user', content: queryText });

    const typingId = showTypingIndicator();
    state.isAnalyzing = true;

    try {
      const payload = {
        message: queryText,
        symbol: state.symbol,
        exchange: state.exchange === 'BSE' ? 'BSE_EQ' : 'NSE_EQ',
        timeframe: state.timeframe,
        current_ltp: parseFloat(state.ltp) || 416.90,
        history: state.history.slice(-6)
      };

      const res = await fetch('/api/chat/trading-assistant', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      removeTypingIndicator(typingId);

      if (res.ok && data.status === 'success') {
        if (data.metrics && data.metrics.ltp) {
          state.ltp = data.metrics.ltp;
          updateMetadataDisplay();
        }
        appendAssistantMsg(data.response);
        state.history.push({ role: 'assistant', content: data.response });
      } else {
        appendAssistantMsg(`⚠️ **Notice**: ${data.message || 'Unable to compute market analysis.'}`);
      }

    } catch (err) {
      removeTypingIndicator(typingId);
      appendAssistantMsg('⚠️ **Connection Error**: Could not connect to Gemini AI Assistant endpoint.');
    } finally {
      state.isAnalyzing = false;
    }
  }

  function appendUserMsg(text) {
    const div = document.createElement('div');
    div.className = 'copilot-msg user';
    div.innerHTML = `
      <div class="msg-avatar">👤</div>
      <div class="msg-bubble-wrap">
        <div class="msg-bubble"><p>${escapeHtml(text)}</p></div>
      </div>
    `;
    elements.messagesBox.appendChild(div);
    scrollBottom();
  }

  function appendAssistantMsg(mdText) {
    const div = document.createElement('div');
    div.className = 'copilot-msg assistant';
    div.innerHTML = `
      <div class="msg-avatar">✨</div>
      <div class="msg-bubble-wrap">
        <div class="msg-bubble">${parseMarkdown(mdText)}</div>
      </div>
    `;
    elements.messagesBox.appendChild(div);
    scrollBottom();
  }

  function showTypingIndicator() {
    const id = `pip-${Date.now()}`;
    const div = document.createElement('div');
    div.id = id;
    div.className = 'copilot-msg assistant';
    div.innerHTML = `
      <div class="msg-avatar">✨</div>
      <div class="msg-bubble-wrap">
        <div class="msg-bubble">
          <div class="copilot-typing">
            <span class="typing-pip"></span>
            <span class="typing-pip"></span>
            <span class="typing-pip"></span>
          </div>
        </div>
      </div>
    `;
    elements.messagesBox.appendChild(div);
    scrollBottom();
    return id;
  }

  function removeTypingIndicator(id) {
    const elem = document.getElementById(id);
    if (elem) elem.remove();
  }

  function scrollBottom() {
    elements.messagesBox.scrollTop = elements.messagesBox.scrollHeight;
  }

  function parseMarkdown(md) {
    if (!md) return '';
    // Normalize line endings
    let text = md.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();

    // Protect backtick code spans
    const codeBlocks = [];
    text = text.replace(/`([^`]+)`/g, (match, code) => {
      codeBlocks.push(code);
      return `___CODE_${codeBlocks.length - 1}___`;
    });

    const lines = text.split('\n');
    const output = [];
    let inUl = false;
    let inOl = false;
    let inQuote = false;
    let quoteBuffer = [];

    function closeLists() {
      if (inUl) {
        output.push('</ul>');
        inUl = false;
      }
      if (inOl) {
        output.push('</ol>');
        inOl = false;
      }
    }

    function closeQuote() {
      if (inQuote) {
        output.push(`<blockquote>${formatInline(quoteBuffer.join('<br>'))}</blockquote>`);
        inQuote = false;
        quoteBuffer = [];
      }
    }

    function formatInline(str) {
      let s = str;
      // Bold
      s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      s = s.replace(/__(.+?)__/g, '<strong>$1</strong>');
      // Italic
      s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
      // Restore code spans
      s = s.replace(/___CODE_(\d+)___/g, (m, idx) => {
        const escaped = escapeHtml(codeBlocks[Number(idx)] || '');
        return `<code class="copilot-code">${escaped}</code>`;
      });
      return s;
    }

    for (let i = 0; i < lines.length; i++) {
      const rawLine = lines[i];
      const trimmed = rawLine.trim();

      if (!trimmed) {
        closeLists();
        closeQuote();
        continue;
      }

      // Horizontal Divider
      if (/^---+$|^===+$/.test(trimmed)) {
        closeLists();
        closeQuote();
        output.push('<hr class="copilot-hr">');
        continue;
      }

      // Blockquotes
      if (trimmed.startsWith('>')) {
        closeLists();
        inQuote = true;
        quoteBuffer.push(trimmed.replace(/^>\s*/, ''));
        continue;
      } else {
        closeQuote();
      }

      // Headings
      const h3Match = trimmed.match(/^###\s+(.*)/);
      if (h3Match) {
        closeLists();
        output.push(`<h3>${formatInline(h3Match[1])}</h3>`);
        continue;
      }
      const h2Match = trimmed.match(/^##\s+(.*)/);
      if (h2Match) {
        closeLists();
        output.push(`<h2>${formatInline(h2Match[1])}</h2>`);
        continue;
      }
      const h1Match = trimmed.match(/^#\s+(.*)/);
      if (h1Match) {
        closeLists();
        output.push(`<h1>${formatInline(h1Match[1])}</h1>`);
        continue;
      }

      // Unordered Lists (- item, * item, • item)
      const ulMatch = trimmed.match(/^[-*•]\s+(.*)/);
      if (ulMatch) {
        if (inOl) {
          output.push('</ol>');
          inOl = false;
        }
        if (!inUl) {
          output.push('<ul class="copilot-list">');
          inUl = true;
        }
        output.push(`<li>${formatInline(ulMatch[1])}</li>`);
        continue;
      }

      // Ordered Lists (1. item, 2. item)
      const olMatch = trimmed.match(/^\d+\.\s+(.*)/);
      if (olMatch) {
        if (inUl) {
          output.push('</ul>');
          inUl = false;
        }
        if (!inOl) {
          output.push('<ol class="copilot-olist">');
          inOl = true;
        }
        output.push(`<li>${formatInline(olMatch[1])}</li>`);
        continue;
      }

      // Regular Paragraph Line
      closeLists();
      output.push(`<p>${formatInline(trimmed)}</p>`);
    }

    closeLists();
    closeQuote();

    return output.join('\n');
  }

  function escapeHtml(str) {
    return str.replace(/[&<>"']/g, (m) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    })[m]);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
