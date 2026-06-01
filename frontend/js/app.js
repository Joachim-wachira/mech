/* ============================================================
   MECH PLATFORM — MAIN APPLICATION JAVASCRIPT
   Handles: Auth, WebSocket, Geolocation, UI interactions
   ============================================================ */

'use strict';

/* ── Config ─────────────────────────────────────────────────── */
const MECH_CONFIG = window.MechConfig || {
  API_BASE: 'http://localhost:5000',
  WS_URL:   'http://localhost:5000',
  APP_NAME: 'mech',
};

/* ── State ──────────────────────────────────────────────────── */
const State = {
  user: null,
  token: null,
  role: null,
  socket: null,
  conversations: [],
  currentConvId: null,
  location: null,
  availability: true,
  notifications: [],
  onlineUsers: new Set(),
};

/* ── Storage Helpers ─────────────────────────────────────────── */
const Storage = {
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch(e) {} },
  get(k)    { try { return JSON.parse(localStorage.getItem(k)); } catch(e) { return null; } },
  remove(k) { try { localStorage.removeItem(k); } catch(e) {} },
};

/* ── Auth ───────────────────────────────────────────────────── */
const Auth = {
  init() {
    State.token = Storage.get('mech_token');
    State.user  = Storage.get('mech_user');
    State.role  = Storage.get('mech_role');
  },

  save(token, user, role) {
    State.token = token; State.user = user; State.role = role;
    Storage.set('mech_token', token);
    Storage.set('mech_user', user);
    Storage.set('mech_role', role);
  },

  logout() {
    State.token = null; State.user = null; State.role = null;
    Storage.remove('mech_token');
    Storage.remove('mech_user');
    Storage.remove('mech_role');
    if (State.socket) State.socket.disconnect();
    window.location.href = 'index.html';
  },

  isLoggedIn() { return !!State.token; },

  headers() {
    return {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${State.token}`,
    };
  },
};

/* ── API ────────────────────────────────────────────────────── */
const API = {
  async post(endpoint, data) {
    try {
      const res = await fetch(`${MECH_CONFIG.API_BASE}${endpoint}`, {
        method: 'POST',
        headers: Auth.headers(),
        body: JSON.stringify(data),
      });
      return await res.json();
    } catch (e) {
      console.error('API POST error:', e);
      return { error: 'Network error' };
    }
  },

  async get(endpoint) {
    try {
      const res = await fetch(`${MECH_CONFIG.API_BASE}${endpoint}`, {
        headers: Auth.headers(),
      });
      return await res.json();
    } catch (e) {
      console.error('API GET error:', e);
      return { error: 'Network error' };
    }
  },

  async put(endpoint, data) {
    try {
      const res = await fetch(`${MECH_CONFIG.API_BASE}${endpoint}`, {
        method: 'PUT',
        headers: Auth.headers(),
        body: JSON.stringify(data),
      });
      return await res.json();
    } catch (e) {
      return { error: 'Network error' };
    }
  },
};

/* ── WebSocket ──────────────────────────────────────────────── */
const WS = {
  connect() {
    if (!State.token) return;
    if (typeof io === 'undefined') { console.warn('Socket.IO not loaded'); return; }

    State.socket = io(MECH_CONFIG.WS_URL, {
      auth: { token: State.token },
      transports: ['websocket', 'polling'],
    });

    State.socket.on('connect', () => {
      console.log('WS connected:', State.socket.id);
      State.socket.emit('user_online', { user_id: State.user?.id });
    });

    State.socket.on('disconnect', () => {
      console.log('WS disconnected');
    });

    State.socket.on('new_message', (data) => {
      WS.handleNewMessage(data);
    });

    State.socket.on('user_status', (data) => {
      WS.handleUserStatus(data);
    });

    State.socket.on('notification', (data) => {
      WS.handleNotification(data);
    });

    State.socket.on('job_request', (data) => {
      WS.handleJobRequest(data);
    });

    State.socket.on('call_event', (data) => {
      WS.handleCallEvent(data);
    });
  },

  handleNewMessage(data) {
    State.conversations = State.conversations.map(c => {
      if (c.id === data.conversation_id) {
        return { ...c, last_message: data.message, unread: (c.unread || 0) + 1 };
      }
      return c;
    });
    if (State.currentConvId === data.conversation_id) {
      UI.appendMessage(data);
    }
    UI.updateBadges();
    UI.showToast(`New message from ${data.sender_name}`);
  },

  handleUserStatus(data) {
    if (data.online) State.onlineUsers.add(data.user_id);
    else State.onlineUsers.delete(data.user_id);
    UI.updateOnlineStatus(data.user_id, data.online);
  },

  handleNotification(data) {
    State.notifications.unshift(data);
    UI.addNotification(data.message);
    UI.showToast(data.message);
  },

  handleJobRequest(data) {
    UI.showToast(`New job request from ${data.customer_name}`);
    UI.refreshJobRequests();
  },

  handleCallEvent(data) {
    UI.logCallEvent(data);
  },

  emit(event, data) {
    if (State.socket?.connected) {
      State.socket.emit(event, data);
    }
  },

  sendMessage(convId, message, type = 'text') {
    WS.emit('send_message', { conversation_id: convId, message, type });
  },

  initiateCall(targetUserId) {
    WS.emit('initiate_call', { target_user_id: targetUserId, caller_id: State.user?.id });
    UI.logCallEvent({ type: 'outgoing', target_id: targetUserId });
    UI.showToast('Calling...');
  },
};

/* ── Geolocation ────────────────────────────────────────────── */
const Geo = {
  detect(onSuccess, onError) {
    if (!navigator.geolocation) {
      if (onError) onError('Geolocation not supported');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        State.location = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        if (onSuccess) onSuccess(State.location);
      },
      (err) => {
        console.warn('Geo error:', err.message);
        if (onError) onError(err.message);
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  },

  detectAndFill(inputEl, btnEl) {
    if (btnEl) {
      btnEl.textContent = '📍 Detecting...';
      btnEl.disabled = true;
    }
    Geo.detect(
      (loc) => {
        Geo.reverseGeocode(loc, (addr) => {
          if (inputEl) inputEl.value = addr;
          if (btnEl) { btnEl.textContent = '📍 DETECT MY LOCATION'; btnEl.disabled = false; }
        });
      },
      () => {
        if (btnEl) { btnEl.textContent = '📍 DETECT MY LOCATION'; btnEl.disabled = false; }
        UI.showToast('Could not detect location');
      }
    );
  },

  reverseGeocode(loc, callback) {
    // Use nominatim for reverse geocoding (open source)
    fetch(`https://nominatim.openstreetmap.org/reverse?lat=${loc.lat}&lon=${loc.lng}&format=json`)
      .then(r => r.json())
      .then(d => callback(d.display_name || `${loc.lat.toFixed(4)}, ${loc.lng.toFixed(4)}`))
      .catch(() => callback(`${loc.lat.toFixed(4)}, ${loc.lng.toFixed(4)}`));
  },
};

/* ── UI Helpers ─────────────────────────────────────────────── */
const UI = {
  showToast(message, duration = 3000) {
    let toast = document.querySelector('.toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.className = 'toast';
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add('show');
    clearTimeout(UI._toastTimer);
    UI._toastTimer = setTimeout(() => toast.classList.remove('show'), duration);
  },

  setLoading(btn, loading, text = 'Submit') {
    if (!btn) return;
    btn.disabled = loading;
    btn.textContent = loading ? '⏳ Please wait...' : text;
  },

  appendMessage(data) {
    const area = document.querySelector('.messages-area');
    if (!area) return;
    const isSent = data.sender_id === State.user?.id;
    const div = document.createElement('div');
    div.className = `msg-bubble-wrapper ${isSent ? 'sent' : 'recv'}`;
    div.innerHTML = `
      <div class="msg-bubble ${isSent ? 'sent' : 'recv'}">
        ${UI.escapeHtml(data.message)}
        <div class="msg-time">${UI.formatTime(data.created_at)}</div>
      </div>`;
    area.appendChild(div);
    area.scrollTop = area.scrollHeight;
  },

  updateOnlineStatus(userId, online) {
    document.querySelectorAll(`[data-user-id="${userId}"] .status-dot`).forEach(dot => {
      dot.className = `status-dot ${online ? 'online' : 'offline'}`;
    });
  },

  addNotification(message) {
    const panel = document.querySelector('.notif-list');
    if (!panel) return;
    const item = document.createElement('div');
    item.className = 'notif-item';
    item.textContent = message;
    panel.prepend(item);
  },

  updateBadges() {
    const total = State.conversations.reduce((s, c) => s + (c.unread || 0), 0);
    document.querySelectorAll('.msg-badge-total').forEach(el => {
      el.textContent = total;
      el.style.display = total > 0 ? 'flex' : 'none';
    });
  },

  refreshJobRequests() {
    // Trigger dashboard refresh
    document.querySelectorAll('[data-refresh="jobs"]').forEach(el => {
      el.classList.add('pulse');
      setTimeout(() => el.classList.remove('pulse'), 600);
    });
  },

  logCallEvent(data) {
    console.log('Call event:', data);
  },

  escapeHtml(str) {
    const d = document.createElement('div');
    d.appendChild(document.createTextNode(str || ''));
    return d.innerHTML;
  },

  formatTime(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    return d.toLocaleTimeString('en-KE', { hour: '2-digit', minute: '2-digit' });
  },

  formatCurrency(amount) {
    return `KES ${Number(amount).toLocaleString('en-KE')}`;
  },
};

/* ── Registration Handlers ───────────────────────────────────── */
const Register = {
  async driver(form) {
    const data = {
      full_name: form.full_name?.value,
      phone: form.phone?.value,
      email: form.email?.value,
      location_lat: State.location?.lat,
      location_lng: State.location?.lng,
      location_text: form.location_text?.value,
      password: form.password?.value,
    };
    const res = await API.post('/api/auth/register/driver', data);
    return res;
  },

  async mechanic(form) {
    const data = {
      full_name: form.full_name?.value,
      business_name: form.business_name?.value,
      phone: form.phone?.value,
      email: form.email?.value,
      password: form.password?.value,
      location_text: form.location_text?.value,
      vehicle_brands: Register.getChecked('brand'),
      services: Register.getChecked('service'),
    };
    const res = await API.post('/api/auth/register/mechanic', data);
    return res;
  },

  async spareshop(form) {
    const data = {
      full_name: form.full_name?.value,
      business_name: form.business_name?.value,
      phone: form.phone?.value,
      email: form.email?.value,
      password: form.password?.value,
      location_text: form.location_text?.value,
      inventory_categories: Register.getChecked('category'),
      delivery_options: Register.getChecked('delivery'),
    };
    const res = await API.post('/api/auth/register/spareshop', data);
    return res;
  },

  getChecked(name) {
    return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`))
      .map(el => el.value);
  },

  async sendSms(phone) {
    return await API.post('/api/auth/send-sms', { phone });
  },

  async verifySms(phone, code) {
    return await API.post('/api/auth/verify-sms', { phone, code });
  },
};

/* ── Dashboard Handlers ──────────────────────────────────────── */
const Dashboard = {
  async loadNearby(role) {
    if (!State.location) return [];
    const res = await API.get(`/api/nearby/${role}?lat=${State.location.lat}&lng=${State.location.lng}`);
    return res.providers || [];
  },

  async toggleAvailability(available) {
    State.availability = available;
    await API.put('/api/profile/availability', { available });
    WS.emit('availability_change', { user_id: State.user?.id, available });
  },

  async reportIssue(description) {
    return await API.post('/api/issues', { description, user_id: State.user?.id });
  },

  async acceptJob(jobId) {
    return await API.post(`/api/jobs/${jobId}/accept`, {});
  },

  async declineJob(jobId) {
    return await API.post(`/api/jobs/${jobId}/decline`, {});
  },

  async confirmOrder(orderId) {
    return await API.post(`/api/orders/${orderId}/confirm`, {});
  },
};

/* ── Admin Handlers ──────────────────────────────────────────── */
const Admin = {
  async getStats() {
    return await API.get('/api/admin/stats');
  },

  async verifyUser(userId, approved) {
    return await API.post(`/api/admin/verify/${userId}`, { approved });
  },

  async suspendUser(userId, duration) {
    return await API.post('/api/admin/suspend', { user_id: userId, duration });
  },

  async deactivateUser(userId) {
    return await API.post('/api/admin/deactivate', { user_id: userId });
  },

  async sendNotification(message, target, role) {
    return await API.post('/api/admin/notify', { message, target, role });
  },

  async getConversationLogs() {
    return await API.get('/api/admin/conversations');
  },

  async getSystemStatus() {
    return await API.get('/api/admin/system-status');
  },
};

/* ── Page-Specific Init ──────────────────────────────────────── */
const Pages = {
  index() {
    // Role selection page
    document.querySelectorAll('[data-role]').forEach(btn => {
      btn.addEventListener('click', () => {
        const role = btn.dataset.role;
        window.location.href = `register_${role}.html`;
      });
    });
  },

  registerDriver() {
    const detectBtn = document.getElementById('detectLocBtn');
    const locationInput = document.getElementById('locationText');
    if (detectBtn) {
      detectBtn.addEventListener('click', () => Geo.detectAndFill(locationInput, detectBtn));
    }

    const form = document.getElementById('driverRegForm');
    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitBtn = form.querySelector('[type=submit]');
        UI.setLoading(submitBtn, true);
        const res = await Register.driver(form);
        UI.setLoading(submitBtn, false, 'Create Driver Account');
        if (res.token) {
          Auth.save(res.token, res.user, 'driver');
          window.location.href = 'dashboard_driver.html';
        } else {
          UI.showToast(res.error || 'Registration failed');
        }
      });
    }
  },

  registerMechanic() {
    Pages._initSmsVerify();

    const form = document.getElementById('mechRegForm');
    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitBtn = form.querySelector('[type=submit]');
        UI.setLoading(submitBtn, true);
        const res = await Register.mechanic(form);
        UI.setLoading(submitBtn, false, 'Create Service Provider Account');
        if (res.token) {
          Auth.save(res.token, res.user, 'mechanic');
          window.location.href = 'dashboard_mechanic.html';
        } else {
          UI.showToast(res.error || 'Registration failed');
        }
      });
    }

    Pages._initLocationDetect();
    Pages._initSpecSearch('brandSearch', '.brand-list');
  },

  registerSpareshop() {
    Pages._initSmsVerify();

    const form = document.getElementById('shopRegForm');
    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitBtn = form.querySelector('[type=submit]');
        UI.setLoading(submitBtn, true);
        const res = await Register.spareshop(form);
        UI.setLoading(submitBtn, false, 'Create Service Provider Account');
        if (res.token) {
          Auth.save(res.token, res.user, 'spareshop');
          window.location.href = 'dashboard_spareshop.html';
        } else {
          UI.showToast(res.error || 'Registration failed');
        }
      });
    }

    Pages._initLocationDetect();
    Pages._initSpecSearch('categorySearch', '.category-list');
  },

  dashboardDriver() {
    Auth.init();
    WS.connect();

    // Detect location and load nearby
    Geo.detect(async (loc) => {
      const mechanics = await Dashboard.loadNearby('mechanic');
      const shops = await Dashboard.loadNearby('spareshop');
      Pages._renderNearbyList(mechanics, 'mechanicList');
      Pages._renderNearbyList(shops, 'shopList');
    });

    // Report issue
    const reportBtn = document.getElementById('reportIssueBtn');
    if (reportBtn) {
      reportBtn.addEventListener('click', () => {
        const desc = prompt('Describe the issue:');
        if (desc) { Dashboard.reportIssue(desc); UI.showToast('Issue reported!'); }
      });
    }

    // Update dashboard
    const updateBtn = document.getElementById('updateDashBtn');
    if (updateBtn) {
      updateBtn.addEventListener('click', () => {
        UI.showToast('Dashboard updated!');
        location.reload();
      });
    }

    // Emergency call
    const emergBtn = document.getElementById('emergencyCallBtn');
    if (emergBtn) {
      emergBtn.addEventListener('click', () => {
        WS.emit('emergency_rescue', { user_id: State.user?.id, location: State.location });
        UI.showToast('🚨 Emergency rescue requested!');
      });
    }

    // Service toggles
    document.querySelectorAll('.chat-toggle').forEach(toggle => {
      toggle.addEventListener('click', function() {
        this.classList.toggle('on');
        this.classList.toggle('off');
      });
    });

    Pages._initDashNav();
  },

  dashboardMechanic() {
    Auth.init();
    WS.connect();
    Pages._initAvailability();
    Pages._initJobActions();
    Pages._initDashNav();
    Pages._pollDashboard();
  },

  dashboardSpareParts() {
    Auth.init();
    WS.connect();
    Pages._initAvailability();
    Pages._initOrderActions();
    Pages._initDashNav();
    Pages._pollDashboard();
  },

  dashboardAdmin() {
    Auth.init();
    WS.connect();
    Pages._initAdminActions();
    Pages._initSystemStatus();
    Pages._initDashNav();
  },

  chat() {
    Auth.init();
    WS.connect();
    Pages._initChatTabs();
    Pages._initMessageInput();
  },

  /* ── Private helpers ─── */
  _initSmsVerify() {
    const sendBtn  = document.getElementById('sendSmsBtn');
    const verifyBtn = document.getElementById('verifySmsBtn');
    const phoneInput = document.getElementById('phoneInput');
    const codeInput = document.getElementById('smsCode');

    if (sendBtn && phoneInput) {
      sendBtn.addEventListener('click', async () => {
        const phone = phoneInput.value.trim();
        if (!phone) { UI.showToast('Enter phone number'); return; }
        UI.setLoading(sendBtn, true);
        const res = await Register.sendSms(phone);
        UI.setLoading(sendBtn, false, 'Send SMS Code');
        UI.showToast(res.message || 'SMS sent!');
      });
    }

    if (verifyBtn && codeInput) {
      verifyBtn.addEventListener('click', async () => {
        const phone = phoneInput?.value.trim();
        const code = codeInput.value.trim();
        UI.setLoading(verifyBtn, true);
        const res = await Register.verifySms(phone, code);
        UI.setLoading(verifyBtn, false, 'Verify Code');
        if (res.verified) {
          verifyBtn.textContent = '✅ Verified';
          verifyBtn.style.background = '#16a34a';
          UI.showToast('Phone verified!');
        } else {
          UI.showToast(res.error || 'Verification failed');
        }
      });
    }
  },

  _initLocationDetect() {
    const detectBtn = document.getElementById('detectLocBtn');
    const locationInput = document.getElementById('locationText');
    if (detectBtn) {
      detectBtn.addEventListener('click', () => Geo.detectAndFill(locationInput, detectBtn));
    }
  },

  _initSpecSearch(inputId, listSelector) {
    const input = document.getElementById(inputId);
    const list  = document.querySelector(listSelector);
    if (!input || !list) return;
    input.addEventListener('input', () => {
      const q = input.value.toLowerCase();
      list.querySelectorAll('.spec-item').forEach(item => {
        item.style.display = item.textContent.toLowerCase().includes(q) ? '' : 'none';
      });
    });
  },

  _renderNearbyList(providers, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!providers.length) return;
    container.innerHTML = providers.map(p => `
      <div class="provider-item">
        <div class="provider-avatar">🔧</div>
        <div class="provider-info">
          <div class="provider-type">${p.role || 'Mechanic'}</div>
          <div class="provider-name">${UI.escapeHtml(p.name)}</div>
          <div class="provider-dist">${p.distance ? p.distance.toFixed(1) + ' km' : 'nearby'}</div>
        </div>
        <div class="provider-actions">
          <button class="action-icon-btn" onclick="WS.initiateCall(${p.id})">📞</button>
          <button class="action-icon-btn" onclick="window.location.href='chat.html?user=${p.id}'">💬</button>
        </div>
      </div>`).join('');
  },

  _initAvailability() {
    const toggle = document.getElementById('availabilityToggle');
    const statusEl = document.getElementById('availStatusValue');
    const switchBtn = document.getElementById('switchAvailBtn');

    if (toggle) {
      toggle.addEventListener('change', async () => {
        const available = toggle.checked;
        await Dashboard.toggleAvailability(available);
        if (statusEl) statusEl.textContent = available ? 'AVAILABLE' : 'UNAVAILABLE';
        if (switchBtn) {
          switchBtn.textContent = available ? 'Switch to: Unavailable' : 'Switch to: Available';
          switchBtn.style.background = available ? '#ef4444' : '#16a34a';
        }
        const widget = document.querySelector('.avail-status');
        if (widget) widget.style.background = available ? '#16a34a' : '#6b7280';
      });
    }

    if (switchBtn) {
      switchBtn.addEventListener('click', () => {
        if (toggle) { toggle.checked = !toggle.checked; toggle.dispatchEvent(new Event('change')); }
      });
    }
  },

  _initJobActions() {
    document.querySelectorAll('[data-accept-job]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const jobId = btn.dataset.acceptJob;
        const res = await Dashboard.acceptJob(jobId);
        UI.showToast(res.message || 'Job accepted!');
      });
    });

    document.querySelectorAll('[data-decline-job]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const jobId = btn.dataset.declineJob;
        const res = await Dashboard.declineJob(jobId);
        UI.showToast(res.message || 'Job declined');
      });
    });
  },

  _initOrderActions() {
    document.querySelectorAll('[data-confirm-order]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const orderId = btn.dataset.confirmOrder;
        const res = await Dashboard.confirmOrder(orderId);
        UI.showToast(res.message || 'Order confirmed!');
      });
    });
  },

  _initAdminActions() {
    // Verify buttons
    document.querySelectorAll('[data-verify]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const userId = btn.dataset.verify;
        const approved = btn.dataset.action === 'approve';
        const res = await Admin.verifyUser(userId, approved);
        UI.showToast(res.message || (approved ? 'User approved' : 'User declined'));
        btn.closest('.verify-item')?.remove();
      });
    });

    // User actions
    const deactivateBtn = document.getElementById('deactivateBtn');
    const suspendBtn    = document.getElementById('suspendBtn');
    const userIdInput   = document.getElementById('actionUserId');

    if (deactivateBtn) {
      deactivateBtn.addEventListener('click', async () => {
        const uid = userIdInput?.value.trim();
        if (!uid) { UI.showToast('Enter user ID'); return; }
        if (!confirm(`Deactivate user ${uid}?`)) return;
        const res = await Admin.deactivateUser(uid);
        UI.showToast(res.message || 'User deactivated');
      });
    }

    if (suspendBtn) {
      suspendBtn.addEventListener('click', async () => {
        const uid = userIdInput?.value.trim();
        if (!uid) { UI.showToast('Enter user ID'); return; }
        const dur = prompt('Suspend duration (hours):');
        if (!dur) return;
        const res = await Admin.suspendUser(uid, parseInt(dur));
        UI.showToast(res.message || 'User suspended');
      });
    }

    // Send notification
    const notifBtn = document.getElementById('sendNotifBtn');
    if (notifBtn) {
      notifBtn.addEventListener('click', async () => {
        const msg = document.getElementById('notifMessage')?.value.trim();
        const target = document.getElementById('notifTarget')?.value;
        const role = document.getElementById('notifRole')?.value;
        if (!msg) { UI.showToast('Enter notification message'); return; }
        const res = await Admin.sendNotification(msg, target, role);
        UI.showToast(res.message || 'Notification sent!');
      });
    }

    // View chat logs
    document.querySelectorAll('[data-view-chat]').forEach(btn => {
      btn.addEventListener('click', () => {
        const convId = btn.dataset.viewChat;
        window.location.href = `chat.html?conv=${convId}&admin=1`;
      });
    });

    // Search users
    const userSearch = document.getElementById('userSearch');
    if (userSearch) {
      userSearch.addEventListener('input', () => {
        const q = userSearch.value.toLowerCase();
        document.querySelectorAll('.user-mgmt-item').forEach(item => {
          item.style.display = item.textContent.toLowerCase().includes(q) ? '' : 'none';
        });
      });
    }
  },

  _initSystemStatus() {
    const refresh = async () => {
      const res = await Admin.getSystemStatus();
      if (res.statuses) {
        res.statuses.forEach(s => {
          const el = document.querySelector(`[data-service="${s.name}"] .status-ok`);
          if (el) el.textContent = s.ok ? 'OK' : 'DOWN';
        });
      }
    };
    refresh();
    setInterval(refresh, 30000);
  },

  _initDashNav() {
    document.querySelectorAll('.dash-nav-tab, .nav-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const target = tab.dataset.target;
        if (target) window.location.href = target;
        document.querySelectorAll('.dash-nav-tab, .nav-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
      });
    });
  },

  _initChatTabs() {
    document.querySelectorAll('.nav-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const page = tab.dataset.page;
        if (page) {
          document.querySelectorAll('.chat-page-section').forEach(s => s.style.display = 'none');
          const section = document.getElementById(`page-${page}`);
          if (section) section.style.display = 'flex';
          document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
          tab.classList.add('active');
        }
      });
    });
  },

  _initMessageInput() {
    const input = document.querySelector('.msg-input');
    const sendBtn = document.querySelector('.msg-send-btn');
    const area = document.querySelector('.messages-area');

    const send = () => {
      const msg = input?.value.trim();
      if (!msg) return;
      const convId = State.currentConvId || new URLSearchParams(location.search).get('conv');
      WS.sendMessage(convId, msg);
      UI.appendMessage({ sender_id: State.user?.id, message: msg, created_at: new Date().toISOString() });
      if (input) input.value = '';
    };

    if (sendBtn) sendBtn.addEventListener('click', send);
    if (input) input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });

    // Voice note (simulated)
    const micBtn = document.querySelector('.msg-mic-btn');
    if (micBtn) {
      let recording = false;
      micBtn.addEventListener('click', () => {
        recording = !recording;
        micBtn.textContent = recording ? '⏹️' : '🎤';
        micBtn.style.color = recording ? 'red' : '';
        if (!recording) UI.showToast('Voice note recorded');
      });
    }

    // Scroll to bottom
    if (area) area.scrollTop = area.scrollHeight;
  },

  _pollDashboard() {
    setInterval(async () => {
      // Lightweight ping to keep data fresh
      if (State.token) {
        const res = await API.get('/api/dashboard/ping');
        if (res.notifications) {
          res.notifications.forEach(n => UI.addNotification(n));
        }
      }
    }, 30000);
  },
};

/* ── Toggle password visibility ─────────────────────────────── */
document.querySelectorAll('.toggle-password').forEach(btn => {
  btn.addEventListener('click', () => {
    const input = btn.previousElementSibling || document.getElementById(btn.dataset.target);
    if (input) {
      input.type = input.type === 'password' ? 'text' : 'password';
      btn.textContent = input.type === 'password' ? '👁' : '🙈';
    }
  });
});

/* ── Auto-init based on page ─────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  Auth.init();

  // Page-enter animation
  document.body.classList.add('page-enter');

  // Determine page
  const path = window.location.pathname.split('/').pop() || 'index.html';
  const pageMap = {
    'index.html':              Pages.index,
    'register_driver.html':    Pages.registerDriver,
    'register_mechanic.html':  Pages.registerMechanic,
    'register_spareshop.html': Pages.registerSpareParts || Pages.registerMechanic,
    'dashboard_driver.html':   Pages.dashboardDriver,
    'dashboard_mechanic.html': Pages.dashboardMechanic,
    'dashboard_spareshop.html':Pages.dashboardSpareParts,
    'dashboard_admin.html':    Pages.dashboardAdmin,
    'chat.html':               Pages.chat,
  };

  const initFn = pageMap[path];
  if (initFn) initFn.call(Pages);

  // Global: password toggle
  document.querySelectorAll('[data-toggle-pw]').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = document.getElementById(btn.dataset.togglePw);
      if (input) input.type = input.type === 'password' ? 'text' : 'password';
    });
  });


// Expose for inline handlers
window.MechApp = { Auth, API, WS, Geo, UI, Dashboard, Admin, Pages, State };

/* ============================================================
   SERVICE WORKER REGISTRATION
   Registers /service-worker.js when the browser supports it.
   The SW handles offline caching, asset pre-fetching, and
   (optionally) push notifications.
   ============================================================ */
(function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) {
    console.info('[SW] Service workers not supported in this browser.');
    return;
  }

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/service-worker.js', { scope: '/' })
      .then((registration) => {
        console.log('[SW] Registered — scope:', registration.scope);

        // Listen for updates and prompt user to refresh
        registration.addEventListener('updatefound', () => {
          const newWorker = registration.installing;
          if (!newWorker) return;
          newWorker.addEventListener('statechange', () => {
            if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
              // A new SW is installed; show a toast so the user can refresh
              UI.showToast('🔄 App updated — refresh to get the latest version', 6000);
            }
          });
        });
      })
      .catch((err) => {
        console.warn('[SW] Registration failed:', err);
      });

    // Detect when a new SW takes control (page was refreshed after update)
    let refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!refreshing) {
        refreshing = true;
        window.location.reload();
      }
    });
  });
})();

/* ============================================================
   ADMIN ROUTE GUARD
   - dashboard_admin.html is blocked for non-admin users.
   - On the index page, the admin link is only shown if the
     current JWT resolves to role === 'admin'.
   - Any user who navigates to dashboard_admin.html without
     an admin token is redirected back to index.html.
   ============================================================ */
(function adminGuard() {
  const path = window.location.pathname.split('/').pop();

  // ── Guard: block direct navigation to admin dashboard ────────
  if (path === 'dashboard_admin.html') {
    Auth.init();
    if (!Auth.isLoggedIn()) {
      window.location.replace('index.html');
      return;
    }
    // Verify role from stored user object
    const storedUser = Storage.get('mech_user');
    if (!storedUser || storedUser.role !== 'admin') {
      console.warn('[Guard] Non-admin attempted to access admin dashboard. Redirecting.');
      window.location.replace('index.html');
      return;
    }
    // Double-check by verifying token with the backend (async)
    fetch(`${MECH_CONFIG.API_BASE}/api/auth/me`, { headers: Auth.headers() })
      .then(r => r.json())
      .then(data => {
        if (!data.user || data.user.role !== 'admin') {
          window.location.replace('index.html');
        }
      })
      .catch(() => {
        // Network down — allow cached admin in; SW will serve cached page
        console.warn('[Guard] Could not verify admin token (offline). Allowing cached session.');
      });
    return;
  }

  // ── Index page: show admin link only for logged-in admins ─────
  if (path === 'index.html' || path === '') {
    Auth.init();
    if (Auth.isLoggedIn()) {
      const storedUser = Storage.get('mech_user');
      if (storedUser && storedUser.role === 'admin') {
        const wrap = document.getElementById('adminLinkWrap');
        if (wrap) wrap.style.display = 'block';
      }
    }
  }
})();

