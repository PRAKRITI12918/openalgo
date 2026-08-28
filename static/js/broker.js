/**
 * broker.js - Client-Side State Manager for OpenAlgo Broker Connectivity
 * 
 * Features:
 * - Dynamic schema-driven UI generation for 35+ broker plugins
 * - Anti-gravity floating dropdown with real-time search & category filtering
 * - Credential masking, field validation, and password visibility toggles
 * - Async API integration for saving, hydrating, and connection testing
 */

(function () {
  'use strict';

  // State
  const state = {
    brokers: {},
    categories: ['All', 'Discount', 'Full-Service', 'XTS', 'Crypto'],
    selectedBrokerId: 'zerodha',
    selectedCategory: 'All',
    searchQuery: '',
    isDropdownOpen: false,
    savedCredentials: {},
    isSubmitting: false,
    isTesting: false
  };

  // DOM Elements
  const elements = {
    triggerBtn: document.getElementById('broker-dropdown-trigger'),
    popover: document.getElementById('broker-popover'),
    searchInput: document.getElementById('broker-search-input'),
    clearSearchBtn: document.getElementById('clear-search-btn'),
    chipsContainer: document.getElementById('category-chips-bar'),
    brokerListContainer: document.getElementById('broker-list-container'),
    triggerIcon: document.getElementById('trigger-broker-icon'),
    triggerName: document.getElementById('trigger-broker-name'),
    triggerCategory: document.getElementById('trigger-broker-category'),
    formTitle: document.getElementById('form-broker-title'),
    formTypeBadge: document.getElementById('form-broker-type-badge'),
    fieldsContainer: document.getElementById('dynamic-fields-container'),
    alertBox: document.getElementById('broker-alert-box'),
    alertText: document.getElementById('broker-alert-text'),
    docsLink: document.getElementById('btn-docs-link'),
    statusBanner: document.getElementById('status-message-banner'),
    statusText: document.getElementById('status-banner-text'),
    btnSave: document.getElementById('btn-save-connect'),
    btnTest: document.getElementById('btn-test-connection'),
    saveSpinner: document.getElementById('save-spinner'),
    saveBtnText: document.getElementById('save-btn-text'),
    credentialsForm: document.getElementById('broker-credentials-form')
  };

  /**
   * Initialize Application
   */
  async function init() {
    setupEventListeners();
    await loadBrokerSchema();
    await hydrateSavedCredentials();
  }

  /**
   * Fetch Schema from Backend API or Local JSON
   */
  async function loadBrokerSchema() {
    try {
      const response = await fetch('/api/brokers');
      if (response.ok) {
        const data = await response.json();
        if (data.brokers) {
          state.brokers = data.brokers;
          if (data.categories) state.categories = data.categories;
        }
      }
    } catch (e) {
      console.warn('Could not fetch schema from /api/brokers, using fallback schema', e);
    }

    renderCategoryChips();
    renderBrokerList();
    selectBroker(state.selectedBrokerId, false);
  }

  /**
   * Hydrate existing credentials from environment
   */
  async function hydrateSavedCredentials() {
    try {
      const response = await fetch('/api/broker/credentials');
      if (response.ok) {
        const json = await response.json();
        if (json.status === 'success' && json.data) {
          state.savedCredentials = json.data;
          if (json.data.current_broker && state.brokers[json.data.current_broker]) {
            selectBroker(json.data.current_broker, false);
          }
        }
      }
    } catch (e) {
      console.log('No prior session credentials to hydrate');
    }
  }

  /**
   * Render Category Filter Chips
   */
  function renderCategoryChips() {
    if (!elements.chipsContainer) return;
    elements.chipsContainer.innerHTML = '';

    state.categories.forEach(cat => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `category-chip ${cat === state.selectedCategory ? 'active' : ''}`;
      btn.textContent = cat;
      btn.dataset.category = cat;
      btn.addEventListener('click', () => {
        state.selectedCategory = cat;
        renderCategoryChips();
        renderBrokerList();
      });
      elements.chipsContainer.appendChild(btn);
    });
  }

  /**
   * Render Broker List with Real-time Search & Filter
   */
  function renderBrokerList() {
    if (!elements.brokerListContainer) return;
    elements.brokerListContainer.innerHTML = '';

    const query = state.searchQuery.toLowerCase().trim();
    const brokerEntries = Object.values(state.brokers);

    const filtered = brokerEntries.filter(broker => {
      const matchesCategory = state.selectedCategory === 'All' || broker.category === state.selectedCategory;
      const matchesQuery = !query ||
        broker.name.toLowerCase().includes(query) ||
        broker.broker_id.toLowerCase().includes(query) ||
        broker.category.toLowerCase().includes(query);
      return matchesCategory && matchesQuery;
    });

    if (filtered.length === 0) {
      elements.brokerListContainer.innerHTML = `<div class="no-results-msg">No brokers found matching "${query}"</div>`;
      return;
    }

    filtered.forEach(broker => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = `broker-item ${broker.broker_id === state.selectedBrokerId ? 'selected' : ''}`;
      item.dataset.brokerId = broker.broker_id;

      const initial = broker.name.charAt(0).toUpperCase();

      item.innerHTML = `
        <div class="broker-item-left">
          <div class="broker-item-avatar">${initial}</div>
          <div class="broker-item-details">
            <span class="broker-item-name">${broker.name}</span>
            <span class="broker-item-sub">${broker.category}</span>
          </div>
        </div>
        <div class="broker-item-right">
          ${broker.badge ? `<span class="broker-badge">${broker.badge}</span>` : ''}
          <svg class="broker-check-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        </div>
      `;

      item.addEventListener('click', () => {
        selectBroker(broker.broker_id);
        closeDropdown();
      });

      elements.brokerListContainer.appendChild(item);
    });
  }

  /**
   * Handle Broker Selection & Dynamic Form Rendering
   */
  function selectBroker(brokerId, resetForm = true) {
    const broker = state.brokers[brokerId];
    if (!broker) return;

    state.selectedBrokerId = brokerId;

    // Update Dropdown Trigger UI
    if (elements.triggerIcon) elements.triggerIcon.textContent = broker.name.charAt(0).toUpperCase();
    if (elements.triggerName) elements.triggerName.textContent = broker.name;
    if (elements.triggerCategory) elements.triggerCategory.textContent = `${broker.category} Broker`;

    // Update Form Header
    if (elements.formTitle) elements.formTitle.textContent = `${broker.name.toUpperCase()} Credentials`;
    if (elements.formTypeBadge) elements.formTypeBadge.textContent = broker.auth_type ? broker.auth_type.toUpperCase() : 'DIRECT';

    // Update Alert Box
    if (broker.alert_notice) {
      elements.alertBox.style.display = 'flex';
      elements.alertText.textContent = broker.alert_notice;
    } else {
      elements.alertBox.style.display = 'none';
    }

    // Update Documentation Link
    if (elements.docsLink) {
      elements.docsLink.href = broker.docs_url || `https://docs.openalgo.in/connect-brokers/brokers/${brokerId}`;
    }

    // Render Dynamic Fields
    renderDynamicFields(broker, resetForm);
    renderBrokerList();
    hideStatusBanner();
  }

  /**
   * Render Dynamic Input Fields from Broker Schema
   */
  function renderDynamicFields(broker, resetForm) {
    if (!elements.fieldsContainer) return;
    elements.fieldsContainer.innerHTML = '';

    const fields = broker.fields || [
      { name: 'broker_api_key', label: 'API Key', type: 'text', placeholder: 'Enter API Key', required: true },
      { name: 'broker_api_secret', label: 'API Secret', type: 'password', placeholder: 'Enter API Secret', required: true }
    ];

    fields.forEach((field, index) => {
      const group = document.createElement('div');
      group.className = 'form-field-group';

      const label = document.createElement('label');
      label.className = 'field-label';
      label.htmlFor = `input_${field.name}`;
      label.textContent = field.label + (field.required ? ' *' : '');

      const inputWrapper = document.createElement('div');
      inputWrapper.className = 'input-with-action';

      const input = document.createElement('input');
      input.id = `input_${field.name}`;
      input.name = field.name;
      input.type = field.type || 'text';
      input.className = `form-input ${field.type === 'password' ? 'password-input' : ''}`;
      input.placeholder = field.placeholder || '';
      input.required = Boolean(field.required);
      if (field.validation) input.dataset.validation = field.validation;

      // Hydrate saved value if available and not resetting
      if (!resetForm && state.savedCredentials[field.name]) {
        input.value = state.savedCredentials[field.name];
      }

      inputWrapper.appendChild(input);

      // Add Password Toggle Button if field is password
      if (field.type === 'password') {
        const toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.className = 'toggle-pwd-btn';
        toggleBtn.title = 'Show/Hide secret';
        toggleBtn.innerHTML = `
          <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"></path>
            <circle cx="12" cy="12" r="3"></circle>
          </svg>
        `;

        toggleBtn.addEventListener('click', () => {
          if (input.type === 'password') {
            input.type = 'text';
            toggleBtn.innerHTML = `
              <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"></path>
                <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"></path>
                <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"></path>
                <line x1="2" y1="2" x2="22" y2="22"></line>
              </svg>
            `;
          } else {
            input.type = 'password';
            toggleBtn.innerHTML = `
              <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"></path>
                <circle cx="12" cy="12" r="3"></circle>
              </svg>
            `;
          }
        });

        inputWrapper.appendChild(toggleBtn);
      }

      group.appendChild(label);
      group.appendChild(inputWrapper);

      if (field.description) {
        const hint = document.createElement('span');
        hint.className = 'field-hint';
        hint.textContent = field.description;
        group.appendChild(hint);
      }

      elements.fieldsContainer.appendChild(group);
    });
  }

  /**
   * Event Listeners Setup
   */
  function setupEventListeners() {
    // Dropdown Toggle
    if (elements.triggerBtn) {
      elements.triggerBtn.addEventListener('click', toggleDropdown);
    }

    // Click Outside Popover
    document.addEventListener('click', (e) => {
      if (state.isDropdownOpen && !e.target.closest('#custom-select-container')) {
        closeDropdown();
      }
    });

    // Escape Key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && state.isDropdownOpen) {
        closeDropdown();
      }
    });

    // Instant Search Input
    if (elements.searchInput) {
      elements.searchInput.addEventListener('input', (e) => {
        state.searchQuery = e.target.value;
        elements.clearSearchBtn.classList.toggle('show', Boolean(state.searchQuery));
        renderBrokerList();
      });
    }

    // Clear Search
    if (elements.clearSearchBtn) {
      elements.clearSearchBtn.addEventListener('click', () => {
        elements.searchInput.value = '';
        state.searchQuery = '';
        elements.clearSearchBtn.classList.remove('show');
        renderBrokerList();
        elements.searchInput.focus();
      });
    }

    // Form Save & Connect Action
    if (elements.btnSave) {
      elements.btnSave.addEventListener('click', handleSaveAndConnect);
    }

    // Test Connection Action
    if (elements.btnTest) {
      elements.btnTest.addEventListener('click', handleTestConnection);
    }
  }

  function toggleDropdown() {
    if (state.isDropdownOpen) {
      closeDropdown();
    } else {
      openDropdown();
    }
  }

  function openDropdown() {
    state.isDropdownOpen = true;
    elements.popover.classList.add('open');
    elements.triggerBtn.classList.add('active');
    elements.triggerBtn.setAttribute('aria-expanded', 'true');
    setTimeout(() => elements.searchInput && elements.searchInput.focus(), 50);
  }

  function closeDropdown() {
    state.isDropdownOpen = false;
    elements.popover.classList.remove('open');
    elements.triggerBtn.classList.remove('active');
    elements.triggerBtn.setAttribute('aria-expanded', 'false');
  }

  /**
   * Collect Form Credentials Data
   */
  function collectFormData() {
    const data = { broker_id: state.selectedBrokerId };
    const inputs = elements.fieldsContainer.querySelectorAll('input');
    inputs.forEach(input => {
      data[input.name] = input.value.trim();
    });
    return data;
  }

  /**
   * Validate Form Data
   */
  function validateForm(data) {
    const broker = state.brokers[state.selectedBrokerId];
    if (!broker) return { valid: false, message: 'Invalid broker selection' };

    const fields = broker.fields || [];
    for (const field of fields) {
      const val = data[field.name] || '';
      if (field.required && !val) {
        return { valid: false, message: `Please enter ${field.label}` };
      }
      if (field.validation && val && val !== '************') {
        const regex = new RegExp(field.validation);
        if (!regex.test(val)) {
          return { valid: false, message: `Invalid format for ${field.label}` };
        }
      }
    }
    return { valid: true };
  }

  /**
   * Save & Connect Handler
   */
  async function handleSaveAndConnect(e) {
    if (e) e.preventDefault();
    if (state.isSubmitting) return;

    const data = collectFormData();
    const validation = validateForm(data);

    if (!validation.valid) {
      showStatusBanner(validation.message, 'error');
      return;
    }

    state.isSubmitting = true;
    elements.saveSpinner.classList.remove('hidden');
    elements.saveBtnText.textContent = 'Saving & Connecting...';
    elements.btnSave.disabled = true;

    try {
      // Dispatch to Backend Save Route
      const res = await fetch('/api/broker/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });

      const result = await res.json();

      if (res.ok && result.status === 'success') {
        showStatusBanner('Credentials saved! Redirecting to broker authentication...', 'success');
        
        const redirectUrl = result.auth_url || `/${state.selectedBrokerId}/callback`;
        setTimeout(() => {
          window.location.href = redirectUrl;
        }, 600);
      } else {
        showStatusBanner(result.message || 'Failed to save credentials', 'error');
        state.isSubmitting = false;
        elements.saveSpinner.classList.add('hidden');
        elements.saveBtnText.textContent = 'Save & Connect Account';
        elements.btnSave.disabled = false;
      }
    } catch (err) {
      showStatusBanner('Network error while saving credentials', 'error');
      state.isSubmitting = false;
      elements.saveSpinner.classList.add('hidden');
      elements.saveBtnText.textContent = 'Save & Connect Account';
      elements.btnSave.disabled = false;
    }
  }

  /**
   * Test Connection Handler
   */
  async function handleTestConnection() {
    if (state.isTesting) return;

    const data = collectFormData();
    state.isTesting = true;
    elements.btnTest.disabled = true;
    showStatusBanner('Verifying broker credentials & connectivity...', 'success');

    try {
      const res = await fetch('/api/broker/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });

      const result = await res.json();

      if (res.ok && result.status === 'success') {
        showStatusBanner(`Connection Verified: ${result.message || 'Broker endpoint is healthy'}`, 'success');
      } else {
        showStatusBanner(`Connection Test Failed: ${result.message || 'Invalid API keys'}`, 'error');
      }
    } catch (err) {
      showStatusBanner('Unable to reach OpenAlgo verification service', 'error');
    } finally {
      state.isTesting = false;
      elements.btnTest.disabled = false;
    }
  }

  function showStatusBanner(msg, type) {
    if (!elements.statusBanner) return;
    elements.statusBanner.className = `status-banner ${type}`;
    elements.statusText.textContent = msg;
    elements.statusBanner.classList.remove('hidden');
  }

  function hideStatusBanner() {
    if (elements.statusBanner) {
      elements.statusBanner.classList.add('hidden');
    }
  }

  // Self-execute on DOM Ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
