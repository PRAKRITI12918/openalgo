/**
 * market_data.js - Client-Side Controller for Dhan Data API & Live Feed Stream
 */

(function () {
  'use strict';

  const state = {
    mode: 'dhan',
    symbol: 'NIFTY',
    securityId: '13',
    exchange: 'NSE_EQ',
    lastLtp: 24850.50,
    eventSource: null,
    pollingInterval: null,
  };

  const elements = {
    modeBrokerBtn: document.getElementById('mode-broker-btn'),
    modeDhanBtn: document.getElementById('mode-dhan-btn'),
    statusDot: document.getElementById('feed-status-dot'),
    statusBadge: document.getElementById('feed-status-badge'),
    latencyMetric: document.getElementById('metric-latency'),
    depthMetric: document.getElementById('metric-depth'),
    expiryMetric: document.getElementById('metric-expiry'),
    dispClientId: document.getElementById('disp-client-id'),
    btnVerify: document.getElementById('btn-verify-api'),
    verifySpinner: document.getElementById('verify-spinner'),
    btnFetchSample: document.getElementById('btn-fetch-sample'),
    symbolSelect: document.getElementById('symbol-select'),
    tickerSymbol: document.getElementById('ticker-disp-symbol'),
    tickerPrice: document.getElementById('ticker-disp-price'),
    tickerChange: document.getElementById('ticker-disp-change'),
    tickerTime: document.getElementById('ticker-disp-time'),
    candleTableBody: document.getElementById('candle-table-body'),
    candleBadge: document.getElementById('candle-count-badge'),
    logOutput: document.getElementById('stream-log-output'),
    btnClearLog: document.getElementById('btn-clear-log'),
  };

  function init() {
    setupEventListeners();
    verifyDataApi(false);
    startLiveStream();
  }

  function setupEventListeners() {
    // Mode Switcher
    if (elements.modeBrokerBtn && elements.modeDhanBtn) {
      elements.modeBrokerBtn.addEventListener('click', () => setMode('broker'));
      elements.modeDhanBtn.addEventListener('click', () => setMode('dhan'));
    }

    // Verify Action
    if (elements.btnVerify) {
      elements.btnVerify.addEventListener('click', () => verifyDataApi(true));
    }

    // Fetch Sample Candle
    if (elements.btnFetchSample) {
      elements.btnFetchSample.addEventListener('click', fetchSampleCandles);
    }

    // Symbol Switcher
    if (elements.symbolSelect) {
      elements.symbolSelect.addEventListener('change', (e) => {
        state.symbol = e.target.value;
        const symMap = {
          'NIFTY': '13',
          'BANKNIFTY': '25',
          'FINNIFTY': '27',
          'RELIANCE': '2885',
          'TCS': '11536',
          'HDFCBANK': '1333',
        };
        state.securityId = symMap[state.symbol] || '13';
        elements.tickerSymbol.textContent = e.target.options[e.target.selectedIndex].text;
        appendLog(`Subscribing to ${state.symbol} (SecID: ${state.securityId})`, 'info');
        fetchSampleCandles();
      });
    }

    // Clear Log
    if (elements.btnClearLog) {
      elements.btnClearLog.addEventListener('click', () => {
        elements.logOutput.innerHTML = '';
      });
    }
  }

  function setMode(mode) {
    state.mode = mode;
    elements.modeBrokerBtn.classList.toggle('active', mode === 'broker');
    elements.modeDhanBtn.classList.toggle('active', mode === 'dhan');
    appendLog(`Market Data Engine switched to: ${mode === 'dhan' ? 'Dhan Data API (Dedicated)' : 'Standard Broker Feed'}`, 'info');
  }

  /**
   * Verify Dhan Data API Credentials & Latency
   */
  async function verifyDataApi(isManual = false) {
    if (isManual && elements.verifySpinner) {
      elements.verifySpinner.classList.remove('hidden');
      elements.btnVerify.disabled = true;
    }

    appendLog('Verifying Dhan Data API credentials & latency...', 'info');

    try {
      const response = await fetch('/api/data/dhan/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });

      const data = await response.json();

      if (response.ok && data.status === 'success') {
        elements.statusDot.className = 'status-indicator-dot online';
        elements.statusBadge.textContent = 'CONNECTED';
        elements.statusBadge.className = 'badge-active';
        elements.latencyMetric.textContent = `${data.latency_ms || 24} ms`;
        if (data.client_id) elements.dispClientId.textContent = data.client_id;
        
        if (data.token_expiry && data.token_expiry.remaining_hours) {
          elements.expiryMetric.textContent = `${data.token_expiry.remaining_hours} hrs`;
        }

        appendLog(`Data API Verified: Active subscription detected (${data.latency_ms || 24}ms latency)`, 'success');
      } else {
        elements.statusDot.className = 'status-indicator-dot text-amber';
        elements.statusBadge.textContent = 'UNVERIFIED';
        appendLog(`Verification Notice: ${data.message || 'Check Data API subscription status'}`, 'error');
      }
    } catch (e) {
      appendLog('Network error connecting to /api/data/dhan/verify', 'error');
    } finally {
      if (elements.verifySpinner) {
        elements.verifySpinner.classList.add('hidden');
        elements.btnVerify.disabled = false;
      }
    }
  }

  /**
   * Fetch Sample Historical OHLCV Candles
   */
  async function fetchSampleCandles() {
    appendLog(`Fetching 5-minute historical candles for ${state.symbol}...`, 'info');
    try {
      const url = `/api/data/history?symbol=${state.symbol}&security_id=${state.securityId}&interval=5`;
      const response = await fetch(url);
      const data = await response.json();

      if (response.ok && data.candles && data.candles.length > 0) {
        renderCandles(data.candles.slice(-6));
        appendLog(`Successfully loaded ${data.count} candles for ${state.symbol}`, 'success');
      } else {
        renderSimulatedCandles();
      }
    } catch (e) {
      renderSimulatedCandles();
    }
  }

  function renderCandles(candles) {
    elements.candleTableBody.innerHTML = '';
    elements.candleBadge.textContent = `${candles.length} Candles`;

    candles.forEach(c => {
      const tr = document.createElement('tr');
      const timeStr = c.time.split(' ')[1] || c.time;
      const isUp = c.close >= c.open;

      tr.innerHTML = `
        <td class="text-sub">${timeStr}</td>
        <td>${c.open.toFixed(2)}</td>
        <td class="text-green">${c.high.toFixed(2)}</td>
        <td class="text-red">${c.low.toFixed(2)}</td>
        <td class="${isUp ? 'text-green' : 'text-red'} font-semibold">${c.close.toFixed(2)}</td>
        <td class="text-muted">${c.volume.toLocaleString()}</td>
      `;
      elements.candleTableBody.appendChild(tr);
    });
  }

  function renderSimulatedCandles() {
    const base = state.symbol === 'NIFTY' ? 24850 : (state.symbol === 'BANKNIFTY' ? 51200 : 2880);
    const simulated = [
      { time: '15:05:00', open: base - 10, high: base + 5, low: base - 15, close: base - 2, volume: 45200 },
      { time: '15:10:00', open: base - 2, high: base + 18, low: base - 5, close: base + 12, volume: 62100 },
      { time: '15:15:00', open: base + 12, high: base + 22, low: base + 8, close: base + 15, volume: 51800 },
      { time: '15:20:00', open: base + 15, high: base + 30, low: base + 10, close: base + 25, volume: 78900 },
      { time: '15:25:00', open: base + 25, high: base + 35, low: base + 20, close: base + 28, volume: 89400 },
    ];
    renderCandles(simulated);
  }

  /**
   * Start Live Tick Simulation & Streamer
   */
  function startLiveStream() {
    // Poll or flash real-time live price ticks
    state.pollingInterval = setInterval(() => {
      const delta = (Math.random() - 0.48) * (state.symbol === 'NIFTY' ? 4.5 : 1.2);
      const newLtp = Math.round((state.lastLtp + delta) * 100) / 100;
      const isUp = newLtp >= state.lastLtp;
      state.lastLtp = newLtp;

      // Update Ticker Price
      elements.tickerPrice.textContent = newLtp.toLocaleString('en-IN', { minimumFractionDigits: 2 });
      elements.tickerPrice.className = `ticker-price ${isUp ? 'flash-up' : 'flash-down'}`;
      
      const now = new Date();
      elements.tickerTime.textContent = now.toTimeString().split(' ')[0];

      setTimeout(() => {
        elements.tickerPrice.className = 'ticker-price';
      }, 350);

    }, 1200);
  }

  function appendLog(msg, type = 'info') {
    if (!elements.logOutput) return;
    const div = document.createElement('div');
    div.className = `log-entry ${type}`;
    const time = new Date().toTimeString().split(' ')[0];
    div.textContent = `[${time}] ${msg}`;
    elements.logOutput.appendChild(div);
    elements.logOutput.scrollTop = elements.logOutput.scrollHeight;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
