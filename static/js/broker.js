/**
 * broker.js - Direct Dhan Authentication Controller for OpenAlgo
 * 
 * Features:
 * - Direct Client ID, PIN, and TOTP authentication
 * - Token capture and localStorage persistence
 * - Global access-token request header injection
 * - Real-time error handling & alerts
 */

(function () {
  'use strict';

  // Helper to get stored access token
  function getStoredAccessToken() {
    try {
      return localStorage.getItem('access-token') || localStorage.getItem('dhan_access_token') || '';
    } catch (e) {
      return '';
    }
  }

  // Global request header injection for outgoing fetch requests
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

  // DOM Elements
  const form = document.getElementById('dhan-auth-form');
  const clientIdInput = document.getElementById('dhanClientId');
  const pinInput = document.getElementById('pin');
  const totpInput = document.getElementById('totp');
  const btnTogglePin = document.getElementById('btn-toggle-pin');
  const btnSubmit = document.getElementById('btn-save-connect');
  const saveSpinner = document.getElementById('save-spinner');
  const saveBtnText = document.getElementById('save-btn-text');
  const statusBanner = document.getElementById('status-message-banner');
  const statusText = document.getElementById('status-banner-text');

  // Hydrate saved client ID if available
  try {
    const savedClientId = localStorage.getItem('dhan_client_id') || '';
    if (savedClientId && clientIdInput) {
      clientIdInput.value = savedClientId;
    }
  } catch (e) {}

  // Toggle PIN visibility
  if (btnTogglePin && pinInput) {
    btnTogglePin.addEventListener('click', function () {
      const isPassword = pinInput.type === 'password';
      pinInput.type = isPassword ? 'text' : 'password';
    });
  }

  // Show status banner
  function showStatus(message, type) {
    if (!statusBanner || !statusText) return;
    statusBanner.className = `status-banner ${type}`;
    statusText.textContent = message;
    statusBanner.classList.remove('hidden');
  }

  function hideStatus() {
    if (!statusBanner) return;
    statusBanner.classList.add('hidden');
  }

  // Form submit handler
  if (form) {
    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      hideStatus();

      const clientId = (clientIdInput ? clientIdInput.value : '').trim();
      const pin = (pinInput ? pinInput.value : '').trim();
      const totp = (totpInput ? totpInput.value : '').trim();

      if (!clientId) {
        showStatus('Please enter your Dhan Client ID.', 'error');
        return;
      }

      if (!pin) {
        showStatus('Please enter your 6-digit Dhan PIN.', 'error');
        return;
      }

      if (!totp) {
        showStatus('Please enter your 6-digit Authenticator TOTP.', 'error');
        return;
      }

      // UI Loading state
      if (btnSubmit) btnSubmit.disabled = true;
      if (saveSpinner) saveSpinner.classList.remove('hidden');
      if (saveBtnText) saveBtnText.textContent = 'Generating Access Token...';

      try {
        // Send request to OpenAlgo backend token generator
        const response = await fetch('/api/dhan/generate-token', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          credentials: 'include',
          body: JSON.stringify({
            dhanClientId: clientId,
            pin: pin,
            totp: totp,
          }),
        });

        const data = await response.json();

        if (!response.ok || data.status === 'error' || !data.accessToken) {
          const errMsg = data.message || data.errorMessage || 'Authentication failed. Please verify your credentials.';
          showStatus(errMsg, 'error');
          resetButton();
          return;
        }

        const accessToken = data.accessToken;

        // Securely store token in browser localStorage
        localStorage.setItem('access-token', accessToken);
        localStorage.setItem('dhan_access_token', accessToken);
        localStorage.setItem('dhan_client_id', clientId);

        showStatus('Authenticated successfully! Redirecting to dashboard...', 'success');

        setTimeout(function () {
          window.location.href = data.redirect_url || '/dashboard';
        }, 700);

      } catch (err) {
        showStatus(err.message || 'Network error connecting to authentication service.', 'error');
        resetButton();
      }
    });
  }

  function resetButton() {
    if (btnSubmit) btnSubmit.disabled = false;
    if (saveSpinner) saveSpinner.classList.add('hidden');
    if (saveBtnText) saveBtnText.textContent = 'Connect Account';
  }

})();
