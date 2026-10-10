/**
 * broker.js - OpenAlgo Multi-Broker Connection Controller
 * 
 * Features:
 * - Dynamic broker selection (Dhan, Zerodha, Angel, Fyers, Upstox, etc.)
 * - Isolated account tracking & one-click account switching
 * - Dhan direct TOTP authentication (exact Client ID / PIN / TOTP)
 * - Zerodha Kite Connect OAuth & Request Token exchange
 * - Connected Accounts live sidebar & active session status
 * - Global access-token header injection for outgoing requests
 */

(function () {
  'use strict';

  // Global request header injection for outgoing fetch requests
  function getStoredAccessToken() {
    try {
      return localStorage.getItem('access-token') || localStorage.getItem('dhan_access_token') || '';
    } catch (e) {
      return '';
    }
  }

  if (typeof window !== 'undefined' && window.fetch) {
    const originalFetch = window.fetch.bind(window);
    window.fetch = async function (input, init) {
      const token = getStoredAccessToken();
      if (token) {
        init = init || {};
        const headers = new Headers(init.headers || {});
        if (!headers.has('access-token')) {
          headers.set('access-token', token);
        }
        init.headers = headers;
      }
      return originalFetch(input, init);
    };
  }

  // State
  let currentBroker = 'dhan';
  let connectedAccounts = [];
  let activeAccount = null;

  // DOM Elements
  const brokerTiles = document.querySelectorAll('.broker-tile');
  const currentAvatar = document.getElementById('current-avatar');
  const currentBrokerTitle = document.getElementById('current-broker-title');
  const currentBrokerSubtitle = document.getElementById('current-broker-subtitle');

  const dhanForm = document.getElementById('dhan-auth-form');
  const zerodhaForm = document.getElementById('zerodha-auth-form');
  const genericForm = document.getElementById('generic-auth-form');

  const dhanClientIdInput = document.getElementById('dhanClientId');
  const pinInput = document.getElementById('pin');
  const totpInput = document.getElementById('totp');
  const btnTogglePin = document.getElementById('btn-toggle-pin');
  const btnSubmitDhan = document.getElementById('btn-submit-dhan');
  const dhanSpinner = document.getElementById('dhan-spinner');
  const dhanBtnText = document.getElementById('dhan-btn-text');

  const kiteApiKeyInput = document.getElementById('kiteApiKey');
  const kiteApiSecretInput = document.getElementById('kiteApiSecret');
  const kiteRequestTokenInput = document.getElementById('kiteRequestToken');
  const btnToggleKiteSecret = document.getElementById('btn-toggle-kite-secret');
  const btnSubmitZerodhaOAuth = document.getElementById('btn-submit-zerodha-oauth');
  const btnSubmitZerodhaToken = document.getElementById('btn-submit-zerodha-token');
  const zerodhaSpinner = document.getElementById('zerodha-spinner');
  const zerodhaBtnText = document.getElementById('zerodha-btn-text');

  const statusBanner = document.getElementById('status-message-banner');
  const statusText = document.getElementById('status-banner-text');

  const connectedAccountsContainer = document.getElementById('connected-accounts-container');
  const accountsCountBadge = document.getElementById('accounts-count-badge');
  const activeSessionIndicator = document.getElementById('active-session-indicator');
  const activeSessionText = document.getElementById('active-session-text');

  // Show status banner
  function showStatus(message, type) {
    if (!statusBanner || !statusText) return;
    statusBanner.className = `status-banner ${type}`;
    statusText.textContent = message;
    statusBanner.classList.remove('hidden');
    statusBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function hideStatus() {
    if (!statusBanner) return;
    statusBanner.classList.add('hidden');
  }

  // Toggle Password / PIN visibility
  if (btnTogglePin && pinInput) {
    btnTogglePin.addEventListener('click', function () {
      pinInput.type = pinInput.type === 'password' ? 'text' : 'password';
    });
  }
  if (btnToggleKiteSecret && kiteApiSecretInput) {
    btnToggleKiteSecret.addEventListener('click', function () {
      kiteApiSecretInput.type = kiteApiSecretInput.type === 'password' ? 'text' : 'password';
    });
  }

  // Broker selection handler
  brokerTiles.forEach(function (tile) {
    tile.addEventListener('click', function () {
      const broker = tile.getAttribute('data-broker');
      selectBroker(broker);
    });
  });

  function selectBroker(broker) {
    currentBroker = broker;
    hideStatus();

    // Update tile selection UI
    brokerTiles.forEach(function (t) {
      if (t.getAttribute('data-broker') === broker) {
        t.classList.add('selected');
      } else {
        t.classList.remove('selected');
      }
    });

    // Update Avatar & Title
    if (broker === 'dhan') {
      if (currentAvatar) {
        currentAvatar.textContent = 'D';
        currentAvatar.className = 'active-broker-avatar';
        currentAvatar.style.background = 'linear-gradient(135deg, #2563eb, #4f46e5)';
      }
      if (currentBrokerTitle) currentBrokerTitle.textContent = 'Dhan Direct Authentication';
      if (currentBrokerSubtitle) currentBrokerSubtitle.textContent = 'Direct Client ID, PIN, and TOTP authentication';
      if (dhanForm) dhanForm.classList.remove('hidden');
      if (zerodhaForm) zerodhaForm.classList.add('hidden');
      if (genericForm) genericForm.classList.add('hidden');
    } else if (broker === 'zerodha') {
      if (currentAvatar) {
        currentAvatar.textContent = 'Z';
        currentAvatar.className = 'active-broker-avatar';
        currentAvatar.style.background = 'linear-gradient(135deg, #ea580c, #dc2626)';
      }
      if (currentBrokerTitle) currentBrokerTitle.textContent = 'Zerodha Kite Connect';
      if (currentBrokerSubtitle) currentBrokerSubtitle.textContent = 'Kite Connect API Key & Secret OAuth Login';
      if (dhanForm) dhanForm.classList.add('hidden');
      if (zerodhaForm) zerodhaForm.classList.remove('hidden');
      if (genericForm) genericForm.classList.add('hidden');
    } else {
      // Generic broker
      if (currentAvatar) {
        currentAvatar.textContent = broker.substring(0, 2).toUpperCase();
        currentAvatar.className = 'active-broker-avatar';
        currentAvatar.style.background = 'linear-gradient(135deg, #4f46e5, #3b82f6)';
      }
      if (currentBrokerTitle) currentBrokerTitle.textContent = `${broker.toUpperCase()} Authentication`;
      if (currentBrokerSubtitle) currentBrokerSubtitle.textContent = `Connect your ${broker.toUpperCase()} broker account`;
      if (dhanForm) dhanForm.classList.add('hidden');
      if (zerodhaForm) zerodhaForm.classList.add('hidden');
      if (genericForm) genericForm.classList.remove('hidden');
      loadGenericBrokerFields(broker);
    }
  }

  // Load Connected Accounts
  async function loadConnectedAccounts() {
    try {
      const res = await fetch('/api/accounts', { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      if (data.status !== 'success') return;

      connectedAccounts = data.accounts || [];
      activeAccount = data.active_account || null;

      renderConnectedAccounts();
    } catch (e) {
      console.error('Error loading connected accounts:', e);
    }
  }

  function renderConnectedAccounts() {
    if (!connectedAccountsContainer) return;
    if (accountsCountBadge) accountsCountBadge.textContent = connectedAccounts.length;

    if (activeAccount && activeSessionIndicator && activeSessionText) {
      activeSessionText.textContent = `Active: ${activeAccount.broker_name} (${activeAccount.client_id_masked})`;
      activeSessionIndicator.classList.remove('hidden');
    }

    if (connectedAccounts.length === 0) {
      connectedAccountsContainer.innerHTML = `
        <div style="padding:16px 10px;text-align:center;color:var(--text-subtle);font-size:12px;">
          No accounts connected yet. Choose a broker on the right to link your first account.
        </div>
      `;
      return;
    }

    connectedAccountsContainer.innerHTML = connectedAccounts.map(function (acc) {
      const brokerLower = acc.broker.toLowerCase();
      const initial = brokerLower === 'flattrade' ? 'FL' : acc.broker_name.charAt(0);
      const isActive = acc.is_active;

      return `
        <div class="account-item ${isActive ? 'active' : ''}" id="acc-card-${acc.account_id}">
          <div class="acc-info">
            <div class="acc-icon ${brokerLower}">${initial}</div>
            <div class="acc-names">
              <span class="acc-broker-name">${acc.broker_name}</span>
              <span class="acc-client-id">${acc.client_id_masked}</span>
            </div>
          </div>
          <div class="acc-actions">
            ${isActive ? `
              <span class="active-pill">
                <span class="active-pill-dot"></span> Active
              </span>
            ` : `
              <button type="button" class="btn-switch" data-account-id="${acc.account_id}">
                Switch
              </button>
            `}
          </div>
        </div>
      `;
    }).join('');

    // Attach switch event listeners
    connectedAccountsContainer.querySelectorAll('.btn-switch').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const accId = btn.getAttribute('data-account-id');
        handleAccountSwitch(accId);
      });
    });
  }

  // Handle Account Switching
  async function handleAccountSwitch(accountId) {
    try {
      showStatus('Switching active account...', 'info');
      const res = await fetch('/api/accounts/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ account_id: accountId }),
      });

      const data = await res.json();
      if (res.ok && data.status === 'success') {
        showStatus(data.message || 'Switched active account successfully!', 'success');
        await loadConnectedAccounts();
      } else {
        showStatus(data.message || 'Failed to switch account.', 'error');
      }
    } catch (err) {
      showStatus(err.message || 'Error switching account.', 'error');
    }
  }

  // DHAN AUTH SUBMIT
  if (dhanForm) {
    // Pre-fill client ID from localStorage if available
    try {
      const savedClientId = localStorage.getItem('dhan_client_id') || '';
      if (savedClientId && dhanClientIdInput) dhanClientIdInput.value = savedClientId;
    } catch (e) {}

    dhanForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      hideStatus();

      const clientId = (dhanClientIdInput ? dhanClientIdInput.value : '').trim();
      const pin = (pinInput ? pinInput.value : '').trim();
      const totp = (totpInput ? totpInput.value : '').trim();

      if (!clientId) return showStatus('Please enter your Dhan Client ID.', 'error');
      if (!pin) return showStatus('Please enter your 6-digit Dhan PIN.', 'error');
      if (!totp) return showStatus('Please enter your 6-digit Authenticator TOTP.', 'error');

      // Loading state
      if (btnSubmitDhan) btnSubmitDhan.disabled = true;
      if (dhanSpinner) dhanSpinner.classList.remove('hidden');
      if (dhanBtnText) dhanBtnText.textContent = 'Authenticating Dhan Account...';

      try {
        const response = await fetch('/api/dhan/generate-token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            dhanClientId: clientId,
            pin: pin,
            totp: totp,
          }),
        });

        const data = await response.json();

        if (!response.ok || data.status === 'error' || !data.accessToken) {
          const errMsg = data.message || data.errorMessage || 'Authentication failed. Please verify Client ID, PIN, and TOTP.';
          showStatus(errMsg, 'error');
          resetDhanButton();
          return;
        }

        const accessToken = data.accessToken;
        localStorage.setItem('access-token', accessToken);
        localStorage.setItem('dhan_access_token', accessToken);
        localStorage.setItem('dhan_client_id', clientId);

        showStatus('Dhan account connected and activated! Redirecting...', 'success');
        await loadConnectedAccounts();

        setTimeout(function () {
          window.location.href = data.redirect_url || '/dashboard';
        }, 700);

      } catch (err) {
        showStatus(err.message || 'Network error connecting to Dhan.', 'error');
        resetDhanButton();
      }
    });
  }

  function resetDhanButton() {
    if (btnSubmitDhan) btnSubmitDhan.disabled = false;
    if (dhanSpinner) dhanSpinner.classList.add('hidden');
    if (dhanBtnText) dhanBtnText.textContent = 'Connect Dhan Account';
  }

  // ZERODHA KITE AUTH SUBMIT
  if (btnSubmitZerodhaOAuth) {
    btnSubmitZerodhaOAuth.addEventListener('click', async function () {
      hideStatus();
      const apiKey = (kiteApiKeyInput ? kiteApiKeyInput.value : '').trim();
      const apiSecret = (kiteApiSecretInput ? kiteApiSecretInput.value : '').trim();

      if (!apiKey) return showStatus('Please enter your Kite Connect API Key.', 'error');

      if (btnSubmitZerodhaOAuth) btnSubmitZerodhaOAuth.disabled = true;
      if (zerodhaSpinner) zerodhaSpinner.classList.remove('hidden');
      if (zerodhaBtnText) zerodhaBtnText.textContent = 'Preparing Kite OAuth...';

      try {
        const response = await fetch('/api/accounts/connect-zerodha', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            api_key: apiKey,
            api_secret: apiSecret,
          }),
        });

        const data = await response.json();
        if (data.status === 'oauth_redirect' && data.login_url) {
          showStatus('Redirecting to Kite Connect authorization...', 'info');
          // Save in localStorage so user returns with key stored
          localStorage.setItem('kite_api_key', apiKey);
          window.location.href = data.login_url;
        } else {
          showStatus(data.message || 'Error generating Kite login URL', 'error');
          resetZerodhaButton();
        }
      } catch (err) {
        showStatus(err.message || 'Error communicating with server.', 'error');
        resetZerodhaButton();
      }
    });
  }

  if (btnSubmitZerodhaToken) {
    btnSubmitZerodhaToken.addEventListener('click', async function () {
      hideStatus();
      const apiKey = (kiteApiKeyInput ? kiteApiKeyInput.value : '').trim();
      const apiSecret = (kiteApiSecretInput ? kiteApiSecretInput.value : '').trim();
      const requestToken = (kiteRequestTokenInput ? kiteRequestTokenInput.value : '').trim();

      if (!apiKey) return showStatus('Please enter your Kite Connect API Key.', 'error');
      if (!apiSecret) return showStatus('Please enter your Kite Connect API Secret.', 'error');
      if (!requestToken) return showStatus('Please paste your Kite Request Token.', 'error');

      btnSubmitZerodhaToken.disabled = true;
      showStatus('Exchanging Kite Request Token...', 'info');

      try {
        const response = await fetch('/api/accounts/connect-zerodha', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            api_key: apiKey,
            api_secret: apiSecret,
            request_token: requestToken,
          }),
        });

        const data = await response.json();
        if (response.ok && data.status === 'success') {
          showStatus('Zerodha Kite account connected successfully! Redirecting...', 'success');
          await loadConnectedAccounts();
          setTimeout(function () {
            window.location.href = data.redirect_url || '/dashboard';
          }, 800);
        } else {
          showStatus(data.message || 'Failed to exchange Kite token.', 'error');
          btnSubmitZerodhaToken.disabled = false;
        }
      } catch (err) {
        showStatus(err.message || 'Error communicating with server.', 'error');
        btnSubmitZerodhaToken.disabled = false;
      }
    });
  }

  function resetZerodhaButton() {
    if (btnSubmitZerodhaOAuth) btnSubmitZerodhaOAuth.disabled = false;
    if (zerodhaSpinner) zerodhaSpinner.classList.add('hidden');
    if (zerodhaBtnText) zerodhaBtnText.textContent = 'Authorize with Kite Connect';
  }

  // GENERIC BROKER HANDLER
  async function loadGenericBrokerFields(brokerId) {
    const container = document.getElementById('generic-fields-container');
    if (!container) return;

    container.innerHTML = '<div style="color:var(--text-subtle);font-size:12px;">Loading broker schema...</div>';

    try {
      const res = await fetch('/api/accounts/installed-brokers');
      const data = await res.json();
      const brokerInfo = (data.brokers || []).find(b => b.broker_id === brokerId);

      if (!brokerInfo || !brokerInfo.fields || brokerInfo.fields.length === 0) {
        container.innerHTML = `
          <div style="color:var(--text-muted);font-size:13px;padding:12px;background:var(--bg-app);border-radius:6px;">
            Broker integration not configured for automated UI auth. Please use OpenAlgo configuration or CLI.
          </div>
        `;
        return;
      }

      container.innerHTML = brokerInfo.fields.map(field => `
        <div class="field-group">
          <label class="field-label" for="gen_${field.name}">
            <span>${field.label} ${field.required ? '<span class="req-star">*</span>' : ''}</span>
          </label>
          <div class="input-container">
            <input 
              type="${field.type === 'password' ? 'password' : 'text'}" 
              id="gen_${field.name}" 
              name="${field.name}" 
              class="form-input" 
              placeholder="${field.placeholder || ''}" 
              ${field.required ? 'required' : ''}
            />
          </div>
          ${field.description ? `<span class="field-hint">${field.description}</span>` : ''}
        </div>
      `).join('');

    } catch (e) {
      container.innerHTML = '<div style="color:var(--error-text);font-size:12px;">Error loading broker schema.</div>';
    }
  }

  // Check URL query parameters (e.g. if returning from Kite redirect with request_token)
  function checkUrlParams() {
    try {
      const params = new URLSearchParams(window.location.search);
      const requestToken = params.get('request_token');
      const action = params.get('action');
      const status = params.get('status');

      if (requestToken) {
        selectBroker('zerodha');
        if (kiteRequestTokenInput) kiteRequestTokenInput.value = requestToken;
        // Check if we have kite_api_key in localStorage
        const savedKey = localStorage.getItem('kite_api_key');
        if (savedKey && kiteApiKeyInput) kiteApiKeyInput.value = savedKey;
        showStatus('Kite request token captured from URL! Click "Exchange Request Token Directly" to finish connecting.', 'info');
      }
    } catch (e) {}
  }

  // Initial Boot
  loadConnectedAccounts();
  checkUrlParams();

})();
