/* ============================================================
   MECH PLATFORM — MAIN APPLICATION JAVASCRIPT
   ============================================================ */
'use strict';

const MECH_CONFIG = window.MechConfig || {
  API_BASE: 'https://mech-backend-h7nk.onrender.com',
  WS_URL:   'wss://mech-backend-h7nk.onrender.com',
  APP_NAME: 'mech',
};

/* ── State ── */
const State = {
  user: null, token: null, role: null, socket: null,
  conversations: [], currentConvId: null,
  location: null, availability: true,
  notifications: [], onlineUsers: new Set(),
};

/* ── Storage ── */
const Storage = {
  set(k,v){ try{ localStorage.setItem(k,JSON.stringify(v)); }catch(e){} },
  get(k)  { try{ return JSON.parse(localStorage.getItem(k)); }catch(e){ return null; } },
  remove(k){ try{ localStorage.removeItem(k); }catch(e){} },
};

/* ── Auth ── */
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
    ['mech_token','mech_user','mech_role'].forEach(k => Storage.remove(k));
    if (State.socket) State.socket.disconnect();
    window.location.href = 'index.html';
  },
  isLoggedIn() { return !!State.token; },
  headers() {
    return { 'Content-Type':'application/json', 'Authorization':`Bearer ${State.token}` };
  },
};

/* ── API ── */
const API = {
  async request(method, endpoint, data) {
    try {
      const opts = { method, headers: Auth.headers() };
      if (data) opts.body = JSON.stringify(data);
      const res = await fetch(`${MECH_CONFIG.API_BASE}${endpoint}`, opts);
      return await res.json();
    } catch(e) { console.error('API error:', e); return { error: 'Network error' }; }
  },
  get(ep)       { return API.request('GET',  ep); },
  post(ep, d)   { return API.request('POST', ep, d); },
  put(ep, d)    { return API.request('PUT',  ep, d); },
  delete(ep)    { return API.request('DELETE', ep); },
};

/* ── WebSocket ── */
const WS = {
  connect() {
    if (!State.token) return;
    if (typeof io === 'undefined') { console.warn('Socket.IO not loaded'); return; }
    State.socket = io(MECH_CONFIG.WS_URL, {
      auth: { token: State.token },
      transports: ['websocket','polling'],
    });
    State.socket.on('connect', () => {
      State.socket.emit('user_online', { user_id: State.user?.id });
    });
    State.socket.on('new_message',   d => WS.handleNewMessage(d));
    State.socket.on('user_status',   d => WS.handleUserStatus(d));
    State.socket.on('notification',  d => WS.handleNotification(d));
    State.socket.on('job_request',   d => WS.handleJobRequest(d));
    State.socket.on('call_event',    d => WS.handleCallEvent(d));
    State.socket.on('incoming_call', d => WS.handleCallEvent(d));
    State.socket.on('typing',        d => document.dispatchEvent(new CustomEvent('ws_typing', {detail:d})));
    State.socket.on('stop_typing',   d => document.dispatchEvent(new CustomEvent('ws_stop_typing', {detail:d})));
    State.socket.on('messages_read', d => document.dispatchEvent(new CustomEvent('ws_read', {detail:d})));
  },
  handleNewMessage(data) {
    State.conversations = State.conversations.map(c =>
      c.id === data.conversation_id
        ? { ...c, last_message: data.message, unread: (c.unread||0)+1 }
        : c
    );
    if (State.currentConvId === data.conversation_id) UI.appendMessage(data);
    UI.updateBadges();
    UI.showToast(`💬 New message from ${data.sender_name}`);
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
    UI.showToast(`🔧 New job request from ${data.customer_name}`);
    Pages._loadJobRequests && Pages._loadJobRequests();
  },
  handleCallEvent(data) {
    // Dispatch DOM event so chat.html can show incoming call overlay
    document.dispatchEvent(new CustomEvent('ws_incoming_call', { detail: data }));
  },
  emit(event, data) { if (State.socket?.connected) State.socket.emit(event, data); },
  sendMessage(convId, message, type='text') {
    WS.emit('send_message', { conversation_id: convId, message, type });
  },
  initiateCall(targetUserId) {
    WS.emit('initiate_call', { target_user_id: targetUserId, caller_id: State.user?.id });
    UI.showToast('📞 Calling...');
  },
};

/* ── Geolocation ── */
const Geo = {
  detect(onSuccess, onError) {
    if (!navigator.geolocation) { if (onError) onError('Not supported'); return; }
    navigator.geolocation.getCurrentPosition(
      pos => {
        State.location = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        if (onSuccess) onSuccess(State.location);
      },
      err => { if (onError) onError(err.message); },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  },
  reverseGeocode(loc, callback) {
    fetch(`https://nominatim.openstreetmap.org/reverse?lat=${loc.lat}&lon=${loc.lng}&format=json`)
      .then(r => r.json())
      .then(d => callback(d.display_name || `${loc.lat.toFixed(4)}, ${loc.lng.toFixed(4)}`))
      .catch(() => callback(`${loc.lat.toFixed(4)}, ${loc.lng.toFixed(4)}`));
  },
};

/* ── UI Helpers ── */
const UI = {
  showToast(message, duration=3000) {
    let t = document.querySelector('.toast');
    if (!t) { t = document.createElement('div'); t.className='toast'; document.body.appendChild(t); }
    t.textContent = message;
    t.classList.add('show');
    clearTimeout(UI._toastTimer);
    UI._toastTimer = setTimeout(() => t.classList.remove('show'), duration);
  },
  setLoading(btn, loading, text='Submit') {
    if (!btn) return;
    btn.disabled = loading;
    btn.textContent = loading ? '⏳ Please wait...' : text;
  },
  appendMessage(data) {
    const area = document.querySelector('.messages-area');
    if (!area) return;
    const isSent = data.sender_id === State.user?.id;
    const div = document.createElement('div');
    div.className = `msg-bubble-wrapper ${isSent?'sent':'recv'}`;
    div.innerHTML = `<div class="msg-bubble ${isSent?'sent':'recv'}">
      ${UI.escapeHtml(data.message||data.content||'')}
      <div class="msg-time">${UI.formatTime(data.created_at)}</div>
    </div>`;
    area.appendChild(div);
    area.scrollTop = area.scrollHeight;
  },
  updateOnlineStatus(userId, online) {
    document.querySelectorAll(`[data-user-id="${userId}"] .status-dot`).forEach(dot => {
      dot.className = `status-dot ${online?'online':'offline'}`;
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
    const total = State.conversations.reduce((s,c) => s+(c.unread||0), 0);
    document.querySelectorAll('.msg-badge-total').forEach(el => {
      el.textContent = total;
      el.style.display = total > 0 ? 'flex' : 'none';
    });
  },
  escapeHtml(str) {
    const d = document.createElement('div');
    d.appendChild(document.createTextNode(str||''));
    return d.innerHTML;
  },
  formatTime(ts) {
    if (!ts) return '';
    return new Date(ts).toLocaleTimeString('en-KE', { hour:'2-digit', minute:'2-digit' });
  },
  formatDate(ts) {
    if (!ts) return '';
    return new Date(ts).toLocaleDateString('en-KE', { day:'numeric', month:'short' });
  },
  showError(elId, msg) {
    const el = document.getElementById(elId);
    if (el) { el.textContent = msg; el.style.display = 'block'; }
  },
  hideError(elId) {
    const el = document.getElementById(elId);
    if (el) el.style.display = 'none';
  },
};

/* ── Pages ── */
const Pages = {

  /* ---------- index ---------- */
  index() {
    document.querySelectorAll('[data-role]').forEach(btn => {
      btn.addEventListener('click', () => {
        window.location.href = `register_${btn.dataset.role}.html`;
      });
    });
    // Show admin link only if logged-in admin
    if (Auth.isLoggedIn()) {
      const u = Storage.get('mech_user');
      if (u?.role === 'admin') {
        const wrap = document.getElementById('adminLinkWrap');
        if (wrap) wrap.style.display = 'block';
      }
    }
  },

  /* ---------- register driver ---------- */
  registerDriver() {
    let _lat = null, _lng = null;
    const detectBtn = document.getElementById('detectLocBtn');
    if (detectBtn) {
      detectBtn.addEventListener('click', function() {
        this.textContent = '⏳ Detecting...'; this.disabled = true;
        Geo.detect(loc => {
          _lat = loc.lat; _lng = loc.lng;
          Geo.reverseGeocode(loc, addr => {
            const inp = document.getElementById('locationText');
            if (inp) inp.value = addr;
            this.textContent = '📍 Location Detected ✓';
          });
        }, () => { this.textContent = '📍 DETECT MY LOCATION'; this.disabled = false; });
      });
    }
    const form = document.getElementById('driverRegForm');
    if (!form) return;
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const btn = form.querySelector('[type=submit]');
      UI.setLoading(btn, true);
      const fd = new FormData(form);
      const payload = Object.fromEntries(fd.entries());
      payload.terms_accepted = document.getElementById('termsAccept')?.checked || false;
      if (_lat !== null) { payload.location_lat = _lat; payload.location_lng = _lng; }
      const res = await API.post('/api/auth/register/driver', payload);
      UI.setLoading(btn, false, 'Create Account');
      if (res.token) {
        Auth.save(res.token, res.user, 'driver');
        window.location.href = 'dashboard_driver.html';
      } else {
        UI.showError('formError', res.error || 'Registration failed');
      }
    });
  },

  /* ---------- register mechanic ---------- */
  registerMechanic() {
    let _lat = null, _lng = null;
    const detectBtn = document.getElementById('detectLocBtn');
    if (detectBtn) {
      detectBtn.addEventListener('click', function() {
        this.textContent = '⏳'; this.disabled = true;
        Geo.detect(loc => {
          _lat = loc.lat; _lng = loc.lng;
          Geo.reverseGeocode(loc, addr => {
            const inp = document.getElementById('locationText');
            if (inp) inp.value = addr;
            this.textContent = '✓';
          });
        }, () => { this.textContent = '🔍'; this.disabled = false; });
      });
    }
    const searchInput = document.getElementById('brandSearch');
    if (searchInput) {
      searchInput.addEventListener('input', () => {
        const q = searchInput.value.toLowerCase();
        document.querySelectorAll('.brand-list .spec-item').forEach(item => {
          item.style.display = item.textContent.toLowerCase().includes(q) ? '' : 'none';
        });
      });
    }
    const form = document.getElementById('mechRegForm');
    if (!form) return;
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const btn = form.querySelector('[type=submit]');
      UI.setLoading(btn, true);
      const fd = new FormData(form);
      const payload = Object.fromEntries(fd.entries());
      payload.terms_accepted = document.getElementById('termsAccept')?.checked || false;
      payload.vehicle_brands = Array.from(document.querySelectorAll('input[name="brand"]:checked')).map(el => el.value);
      payload.services = Array.from(document.querySelectorAll('input[name="service"]:checked')).map(el => el.value);
      if (_lat !== null) { payload.location_lat = _lat; payload.location_lng = _lng; }
      const res = await API.post('/api/auth/register/mechanic', payload);
      UI.setLoading(btn, false, 'Create Account');
      if (res.token) {
        Auth.save(res.token, res.user, 'mechanic');
        window.location.href = 'dashboard_mechanic.html';
      } else {
        UI.showError('formError', res.error || 'Registration failed');
      }
    });
  },

  /* ---------- register spareshop ---------- */
  registerSpareshop() {
    let _lat = null, _lng = null;
    const detectBtn = document.getElementById('detectLocBtn');
    if (detectBtn) {
      detectBtn.addEventListener('click', function() {
        this.textContent = '⏳'; this.disabled = true;
        Geo.detect(loc => {
          _lat = loc.lat; _lng = loc.lng;
          Geo.reverseGeocode(loc, addr => {
            const inp = document.getElementById('locationText');
            if (inp) inp.value = addr;
            this.textContent = '✓';
          });
        }, () => { this.textContent = '🔍'; this.disabled = false; });
      });
    }
    const form = document.getElementById('shopRegForm');
    if (!form) return;
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const btn = form.querySelector('[type=submit]');
      UI.setLoading(btn, true);
      const fd = new FormData(form);
      const payload = Object.fromEntries(fd.entries());
      payload.terms_accepted = document.getElementById('termsAccept')?.checked || false;
      payload.inventory_categories = Array.from(document.querySelectorAll('input[name="category"]:checked')).map(el => el.value);
      payload.delivery_options = Array.from(document.querySelectorAll('input[name="delivery"]:checked')).map(el => el.value);
      if (_lat !== null) { payload.location_lat = _lat; payload.location_lng = _lng; }
      const res = await API.post('/api/auth/register/spareshop', payload);
      UI.setLoading(btn, false, 'Create Account');
      if (res.token) {
        Auth.save(res.token, res.user, 'spareshop');
        window.location.href = 'dashboard_spareshop.html';
      } else {
        UI.showError('formError', res.error || 'Registration failed');
      }
    });
  },

  /* ---------- driver dashboard ---------- */
  async dashboardDriver() {
    Auth.init();
    if (!Auth.isLoggedIn()) { window.location.href = 'login.html'; return; }
    WS.connect();
    Pages._initDashNav();
    Pages._initLogout();

    // Show user name
    const nameEl = document.getElementById('dashUserName');
    if (nameEl && State.user) nameEl.textContent = State.user.full_name || 'Driver';

    // Emergency button
    const emergBtn = document.getElementById('emergencyCallBtn');
    if (emergBtn) {
      emergBtn.addEventListener('click', () => {
        WS.emit('emergency_rescue', { user_id: State.user?.id, location: State.location });
        UI.showToast('🚨 Emergency rescue requested!');
      });
    }

    // Report issue
    document.getElementById('reportIssueBtn')?.addEventListener('click', async () => {
      const desc = prompt('Describe the issue:');
      if (!desc) return;
      await API.post('/api/issues', { description: desc });
      UI.showToast('✅ Issue reported!');
    });

    // Update dashboard
    document.getElementById('updateDashBtn')?.addEventListener('click', () => location.reload());

    // Load real nearby providers + real notifications
    Geo.detect(async loc => {
      await Pages._loadNearbyProviders(loc);
    }, () => {
      // No location — still load all available providers
      Pages._loadNearbyProviders(null);
    });

    await Pages._loadNotifications('driverNotifList');
    Pages._pollNotifications('driverNotifList');
  },

  async _loadNearbyProviders(loc) {
    const list = document.getElementById('providerList');
    if (!list) return;

    list.innerHTML = '<div style="padding:16px;text-align:center;color:#9ca3af;">🔍 Finding nearby providers...</div>';

    let mechanics = [], shops = [];
    try {
      const suffix = loc ? `?lat=${loc.lat}&lng=${loc.lng}` : '';
      const [mRes, sRes] = await Promise.all([
        API.get(`/api/nearby/mechanic${suffix}`),
        API.get(`/api/nearby/spareshop${suffix}`),
      ]);
      mechanics = mRes.providers || [];
      shops     = sRes.providers || [];
    } catch(e) {}

    const all = [...mechanics, ...shops];
    if (!all.length) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:#9ca3af;">No providers found nearby yet.<br>More will appear as mechanics and spare shops join.</div>';
      return;
    }

    list.innerHTML = all.map(p => {
      const icon   = p.role === 'mechanic' ? '🔧' : '🛒';
      const label  = p.role === 'mechanic' ? 'Mechanic' : 'Spare Shop';
      const dist   = p.distance != null ? `${p.distance.toFixed(1)} km away` : 'Nearby';
      const status = p.is_available ? '<span style="color:#16a34a;font-size:0.7rem;">● Available</span>' : '<span style="color:#9ca3af;font-size:0.7rem;">● Unavailable</span>';
      return `<div class="provider-item" data-user-id="${p.id}">
        <div class="provider-avatar">${icon}</div>
        <div class="provider-info">
          <div class="provider-type">${label} ${status}</div>
          <div class="provider-name">${UI.escapeHtml(p.full_name || p.business_name || 'Provider')}</div>
          <div class="provider-dist">${dist}</div>
        </div>
        <div class="provider-actions">
          <button class="action-icon-btn" title="Chat" onclick="Pages._startChat(${p.id})">💬</button>
          <button class="action-icon-btn" title="Call" onclick="WS.initiateCall(${p.id})">📞</button>
        </div>
      </div>`;
    }).join('');
  },

  async _startChat(userId) {
    // Create or fetch conversation with this user, then open chat
    const res = await API.post('/api/conversations/start', { participant_id: userId });
    if (res.conversation_id || res.id) {
      const convId = res.conversation_id || res.id;
      window.location.href = `chat.html?conv=${convId}`;
    } else {
      window.location.href = `chat.html?user=${userId}`;
    }
  },

  /* ---------- mechanic dashboard ---------- */
  async dashboardMechanic() {
    Auth.init();
    if (!Auth.isLoggedIn()) { window.location.href = 'login.html'; return; }
    WS.connect();
    Pages._initDashNav();
    Pages._initLogout();
    Pages._initAvailability();

    const nameEl = document.getElementById('dashUserName');
    if (nameEl && State.user) nameEl.textContent = State.user.full_name || 'Mechanic';

    document.getElementById('reportIssueBtn')?.addEventListener('click', async () => {
      const desc = prompt('Describe the issue:');
      if (!desc) return;
      await API.post('/api/issues', { description: desc });
      UI.showToast('✅ Issue reported!');
    });
    document.getElementById('updateDashBtn')?.addEventListener('click', () => location.reload());
    document.getElementById('updateDashBtn2')?.addEventListener('click', () => location.reload());

    await Pages._loadMechanicStats();
    await Pages._loadJobRequests();
    await Pages._loadMyRatings();
    await Pages._loadNotifications('mechNotifList');
    Pages._pollNotifications('mechNotifList');
  },

  async _loadMechanicStats() {
    const res = await API.get('/api/mechanic/stats');
    if (res.error) return;
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set('incomingJobsCount', res.incoming_jobs ?? '--');
    set('totalEarnings', res.total_earnings != null ? `KES ${Number(res.total_earnings).toLocaleString('en-KE')}` : 'KES 0');
    set('activeRepairs', res.active_repairs ?? '--');
  },

  async _loadJobRequests() {
    const res = await API.get('/api/jobs/incoming');
    const container = document.getElementById('jobRequestsList');
    if (!container || res.error) return;
    const jobs = res.jobs || [];
    if (!jobs.length) {
      container.innerHTML = '<div style="padding:12px;text-align:center;color:#9ca3af;font-size:0.82rem;">No incoming job requests yet.</div>';
      return;
    }
    container.innerHTML = jobs.map(j => `
      <div class="provider-item" style="margin-bottom:8px;">
        <div class="provider-avatar" style="font-size:1.1rem;">🚗</div>
        <div class="provider-info">
          <div class="provider-type">Driver</div>
          <div class="provider-name" style="font-size:0.85rem;">${UI.escapeHtml(j.driver_name || 'Driver')}</div>
          <div class="provider-dist">${j.distance ? j.distance.toFixed(1)+' km away' : 'Nearby'}</div>
        </div>
        <div style="display:flex;gap:6px;">
          <button class="btn btn-green" style="padding:5px 8px;font-size:0.72rem;" onclick="Pages._acceptJob(${j.id}, this)">✓</button>
          <button class="btn btn-red"   style="padding:5px 8px;font-size:0.72rem;" onclick="Pages._declineJob(${j.id}, this)">✗</button>
          <button class="btn btn-purple" style="padding:5px 8px;font-size:0.72rem;" onclick="Pages._startChat(${j.driver_id})">💬</button>
        </div>
      </div>`).join('');
  },

  async _acceptJob(jobId, btn) {
    const res = await API.post(`/api/jobs/${jobId}/accept`, {});
    UI.showToast(res.message || '✅ Job accepted!');
    btn.closest('.provider-item')?.remove();
  },

  async _declineJob(jobId, btn) {
    const res = await API.post(`/api/jobs/${jobId}/decline`, {});
    UI.showToast(res.message || 'Job declined');
    btn.closest('.provider-item')?.remove();
  },

  async _loadMyRatings() {
    const res = await API.get('/api/mechanic/my-ratings');
    if (res.error || !res.reviews) return;
    const countEl = document.getElementById('totalRatingCount');
    if (countEl) countEl.textContent = `${res.total_reviews || 0} reviews`;
    const list = document.getElementById('myRatingsList');
    if (!list) return;
    const reviews = res.reviews || [];
    if (!reviews.length) {
      list.innerHTML = '<div style="padding:8px;color:#9ca3af;font-size:0.78rem;">No reviews yet.</div>';
      return;
    }
    list.innerHTML = reviews.slice(0,5).map(r => `
      <div class="job-user-row" style="border-top:1px solid #f3f4f6;padding-top:8px;margin-top:4px;">
        <div style="width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,var(--magenta),var(--purple-light));display:flex;align-items:center;justify-content:center;font-size:0.85rem;flex-shrink:0;">🚗</div>
        <div style="flex:1;min-width:0;">
          <div style="font-size:0.78rem;font-weight:700;">${UI.escapeHtml(r.reviewer_name || 'Driver')}</div>
          <div style="color:#f59e0b;font-size:0.7rem;">${'★'.repeat(r.stars||0)}${'☆'.repeat(5-(r.stars||0))}</div>
          <div style="font-size:0.7rem;color:var(--text-muted);">"${UI.escapeHtml(r.comment || '')}"</div>
          <div style="font-size:0.65rem;color:#9ca3af;">${UI.formatDate(r.created_at)}</div>
        </div>
      </div>`).join('');
  },

  /* ---------- spareshop dashboard ---------- */
  async dashboardSpareParts() {
    Auth.init();
    if (!Auth.isLoggedIn()) { window.location.href = 'login.html'; return; }
    WS.connect();
    Pages._initDashNav();
    Pages._initLogout();
    Pages._initAvailability();

    const nameEl = document.getElementById('dashUserName');
    if (nameEl && State.user) nameEl.textContent = State.user.full_name || 'Spare Shop';

    document.getElementById('reportIssueBtn')?.addEventListener('click', async () => {
      const desc = prompt('Describe the issue:');
      if (!desc) return;
      await API.post('/api/issues', { description: desc });
      UI.showToast('✅ Issue reported!');
    });
    document.getElementById('updateDashBtn')?.addEventListener('click', () => location.reload());

    await Pages._loadShopStats();
    await Pages._loadOrderRequests();
    await Pages._loadNotifications('shopNotifList');
    Pages._pollNotifications('shopNotifList');
  },

  async _loadShopStats() {
    const res = await API.get('/api/spareshop/stats');
    if (res.error) return;
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set('sparesRequestedCount', res.spares_requested ?? '--');
    set('activeEarnings', res.total_earnings != null ? `KES ${Number(res.total_earnings).toLocaleString('en-KE')}` : 'KES 0');
  },

  async _loadOrderRequests() {
    const res = await API.get('/api/orders/incoming');
    const container = document.getElementById('orderRequestsList');
    if (!container || res.error) return;
    const orders = res.orders || [];
    if (!orders.length) {
      container.innerHTML = '<div style="padding:12px;text-align:center;color:#9ca3af;font-size:0.82rem;">No incoming orders yet.</div>';
      return;
    }
    container.innerHTML = orders.map(o => `
      <div class="provider-item" style="margin-bottom:8px;">
        <div style="font-size:1.4rem;">🚚</div>
        <div class="provider-info">
          <div class="provider-type">Driver</div>
          <div class="provider-name" style="font-size:0.85rem;">${UI.escapeHtml(o.customer_name || 'Customer')}</div>
          <div class="provider-dist">Part: ${UI.escapeHtml(o.part_name || 'Spare Part')}</div>
        </div>
        <div style="display:flex;gap:6px;">
          <button class="btn btn-green" style="padding:5px 8px;font-size:0.72rem;" onclick="Pages._confirmOrder(${o.id}, this)">✓</button>
          <button class="btn btn-purple" style="padding:5px 8px;font-size:0.72rem;" onclick="Pages._startChat(${o.customer_id})">💬</button>
        </div>
      </div>`).join('');
  },

  async _confirmOrder(orderId, btn) {
    const res = await API.post(`/api/orders/${orderId}/confirm`, {});
    UI.showToast(res.message || '✅ Order confirmed!');
    btn.closest('.provider-item')?.remove();
  },

  /* ---------- admin dashboard ---------- */
  async dashboardAdmin() {
    Auth.init();
    if (!Auth.isLoggedIn() || State.user?.role !== 'admin') {
      window.location.href = 'index.html'; return;
    }
    WS.connect();
    Pages._initDashNav();
    Pages._initLogout();
    Pages._initAdminActions();
    await Pages._loadAdminStats();
    Pages._initSystemStatus();
  },

  async _loadAdminStats() {
    const res = await API.get('/api/admin/stats');
    if (res.error) return;
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set('statTotalUsers',   res.total_users    ?? '--');
    set('statDrivers',      res.drivers        ?? '--');
    set('statMechanics',    res.mechanics      ?? '--');
    set('statShops',        res.spare_shops    ?? '--');
    set('statActiveToday',  res.active_today   ?? '--');
    set('statPendingVerify',res.pending_verify ?? '--');
  },

  async _loadAdminUsers(q='') {
    const res = await API.get(`/api/admin/users${q ? '?q='+encodeURIComponent(q) : ''}`);
    const users = res.users || [];
    const container = document.getElementById('userMgmtList');
    if (!container) return;
    if (!users.length) {
      container.innerHTML = '<div style="padding:12px;text-align:center;color:#9ca3af;font-size:0.82rem;">No users found.</div>';
      return;
    }
    container.innerHTML = users.map(u => `
      <div class="user-mgmt-item" style="display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid #f3f4f6;">
        <div style="width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,var(--magenta),var(--cyan-accent));display:flex;align-items:center;justify-content:center;font-size:0.9rem;flex-shrink:0;">
          ${u.role==='mechanic'?'🔧':u.role==='spareshop'?'🛒':'🚗'}
        </div>
        <div style="flex:1;min-width:0;">
          <div style="font-size:0.85rem;font-weight:800;">${UI.escapeHtml(u.full_name||'')}</div>
          <div style="font-size:0.72rem;color:#6b7280;">${UI.escapeHtml(u.email||'')} · ${u.role}</div>
          <div style="font-size:0.68rem;color:${u.is_active?'#16a34a':'#ef4444'};">${u.is_active?'Active':'Inactive'} · ${u.is_verified?'Verified':'Unverified'}</div>
        </div>
        <div style="display:flex;gap:4px;flex-shrink:0;">
          ${!u.is_verified?`<button onclick="Pages._verifyUser(${u.id},true,this)" style="padding:4px 8px;background:#16a34a;color:#fff;border:none;border-radius:6px;font-size:0.7rem;cursor:pointer;">✓ Verify</button>`:''}
          <button onclick="Pages._toggleUserActive(${u.id},${u.is_active},this)" style="padding:4px 8px;background:${u.is_active?'#ef4444':'#6b7280'};color:#fff;border:none;border-radius:6px;font-size:0.7rem;cursor:pointer;">${u.is_active?'Deactivate':'Activate'}</button>
        </div>
      </div>`).join('');
  },

  async _verifyUser(userId, approved, btn) {
    const res = await API.post(`/api/admin/verify/${userId}`, { approved });
    UI.showToast(res.message || (approved ? 'User verified' : 'User declined'));
    btn.closest('.user-mgmt-item')?.remove();
  },

  async _toggleUserActive(userId, currentlyActive, btn) {
    const res = await API.post('/api/admin/deactivate', { user_id: userId });
    UI.showToast(res.message || 'Done');
    Pages._loadAdminUsers();
  },

  _initAdminActions() {
    // Verify buttons (dynamic delegation)
    document.addEventListener('click', async e => {
      if (e.target.dataset.verify) {
        const uid = e.target.dataset.verify;
        const approved = e.target.dataset.action === 'approve';
        const res = await API.post(`/api/admin/verify/${uid}`, { approved });
        UI.showToast(res.message || (approved ? 'User approved' : 'User declined'));
        e.target.closest('.verify-item')?.remove();
      }
    });

    // User search — queries real API with debounce
    const userSearch = document.getElementById('userSearch');
    if (userSearch) {
      let searchTimer;
      userSearch.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => Pages._loadAdminUsers(userSearch.value.trim()), 400);
      });
      Pages._loadAdminUsers(); // initial load
    }

    // Deactivate/suspend
    const deactivateBtn = document.getElementById('deactivateBtn');
    const suspendBtn    = document.getElementById('suspendBtn');
    const userIdInput   = document.getElementById('actionUserId');
    deactivateBtn?.addEventListener('click', async () => {
      const uid = userIdInput?.value.trim();
      if (!uid || !confirm(`Deactivate user ${uid}?`)) return;
      const res = await API.post('/api/admin/deactivate', { user_id: uid });
      UI.showToast(res.message || 'User deactivated');
    });
    suspendBtn?.addEventListener('click', async () => {
      const uid = userIdInput?.value.trim();
      if (!uid) return;
      const dur = prompt('Suspend duration (hours):');
      if (!dur) return;
      const res = await API.post('/api/admin/suspend', { user_id: uid, duration: parseInt(dur) });
      UI.showToast(res.message || 'User suspended');
    });

    // Send notification
    document.getElementById('sendNotifBtn')?.addEventListener('click', async () => {
      const msg  = document.getElementById('notifMessage')?.value.trim();
      const target = document.getElementById('notifTarget')?.value;
      const role = document.getElementById('notifRole')?.value;
      if (!msg) { UI.showToast('Enter notification message'); return; }
      const res = await API.post('/api/admin/notify', { message: msg, target, role });
      UI.showToast(res.message || '✅ Notification sent!');
    });
  },

  _initSystemStatus() {
    const refresh = async () => {
      const res = await API.get('/api/admin/system-status');
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

  /* ---------- chat ---------- */
  async chat() {
    Auth.init();
    if (!Auth.isLoggedIn()) { window.location.href = 'login.html'; return; }
    WS.connect();
    Pages._initChatTabs();
    Pages._initMessageInput();
    Pages._initDashNav();
    Pages._initLogout();
    await Pages._loadConversationList();
    await Pages._loadEmergencyContacts();

    // Auto-open conversation if ?conv= or ?user= in URL
    const params = new URLSearchParams(location.search);
    const convId = params.get('conv');
    const userId = params.get('user');
    if (convId) {
      await Pages._openConversation(parseInt(convId));
    } else if (userId) {
      const res = await API.post('/api/conversations/start', { participant_id: parseInt(userId) });
      if (res.conversation_id || res.id) {
        await Pages._openConversation(res.conversation_id || res.id);
      }
    }
  },

  async _loadConversationList() {
    const container = document.getElementById('conversationList');
    if (!container) return;
    const res = await API.get('/api/conversations');
    State.conversations = res.conversations || [];
    UI.updateBadges();
    if (!State.conversations.length) {
      container.innerHTML = '<div style="padding:20px;text-align:center;color:#9ca3af;">No conversations yet.<br>Start one from the dashboard.</div>';
      return;
    }
    container.innerHTML = State.conversations.map(c => {
      const other = (c.participants || []).find(p => p.id !== State.user?.id);
      const name  = other ? (other.full_name || other.business_name || 'User') : 'Conversation';
      const last  = c.last_message || '';
      const unread = c.unread > 0 ? `<span style="background:var(--red-btn);color:#fff;border-radius:50%;padding:2px 6px;font-size:0.65rem;font-weight:800;">${c.unread}</span>` : '';
      return `<div class="conv-item" onclick="Pages._openConversation(${c.id})" style="padding:14px 16px;border-bottom:1px solid rgba(255,255,255,0.08);cursor:pointer;display:flex;align-items:center;gap:12px;">
        <div style="width:42px;height:42px;border-radius:50%;background:linear-gradient(135deg,var(--magenta),var(--cyan-accent));display:flex;align-items:center;justify-content:center;font-size:1.2rem;flex-shrink:0;">👤</div>
        <div style="flex:1;min-width:0;">
          <div style="font-weight:700;font-size:0.88rem;color:#fff;">${UI.escapeHtml(name)}</div>
          <div style="font-size:0.75rem;color:#9ca3af;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${UI.escapeHtml(last)}</div>
        </div>
        ${unread}
      </div>`;
    }).join('');
  },

  async _openConversation(convId) {
    State.currentConvId = convId;
    const convView = document.getElementById('convView');
    if (convView) convView.classList.add('open');

    // Load messages
    const res = await API.get(`/api/conversations/${convId}/messages`);
    const area = document.querySelector('.messages-area');
    if (area) {
      area.innerHTML = '';
      (res.messages || []).forEach(m => UI.appendMessage(m));
      area.scrollTop = area.scrollHeight;
    }

    // Join WS room
    WS.emit('join_conversation', { conversation_id: convId });

    // Mark as read
    WS.emit('mark_read', { conversation_id: convId, sender_id: State.user?.id });

    // Back button
    document.getElementById('convBackBtn')?.addEventListener('click', () => {
      convView?.classList.remove('open');
      State.currentConvId = null;
      WS.emit('leave_conversation', { conversation_id: convId });
    }, { once: true });
  },

  async _loadEmergencyContacts() {
    const container = document.getElementById('emergencyContactsList');
    if (!container) return;
    container.innerHTML = '<div style="padding:16px;text-align:center;color:#9ca3af;">Loading emergency contacts...</div>';
    try {
      // Get user's country for filtering
      const country = State.user?.country || '';
      const url = country ? `/api/emergency/contacts?country=${encodeURIComponent(country)}` : '/api/emergency/contacts';
      const res = await fetch(`${MECH_CONFIG.API_BASE}${url}`);
      const data = await res.json();
      const contacts = data.contacts || [];
      if (!contacts.length) {
        container.innerHTML = '<div style="padding:16px;text-align:center;color:#9ca3af;">No emergency contacts available.</div>';
        return;
      }
      container.innerHTML = contacts.map(c => `
        <div class="emerg-card">
          <div class="emerg-icon">${c.icon || '🚨'}</div>
          <div style="flex:1;min-width:0;">
            <div style="font-weight:700;font-size:0.88rem;">${UI.escapeHtml(c.name)}</div>
            <div style="font-size:0.75rem;color:#6b7280;">${UI.escapeHtml(c.region || '')} · ${UI.escapeHtml(c.category || '')}</div>
            ${c.available_24_7 ? '<div style="font-size:0.7rem;color:#16a34a;font-weight:600;">24/7</div>' : ''}
            ${c.notes ? `<div style="font-size:0.7rem;color:#9ca3af;margin-top:2px;">${UI.escapeHtml(c.notes)}</div>` : ''}
          </div>
          <a href="tel:${UI.escapeHtml(c.contact)}" class="btn btn-red" style="padding:8px 12px;font-size:0.8rem;white-space:nowrap;text-decoration:none;">
            📞 ${UI.escapeHtml(c.contact)}
          </a>
        </div>`).join('');
    } catch(e) {
      container.innerHTML = '<div style="padding:16px;text-align:center;color:#ef4444;">Could not load emergency contacts.</div>';
    }
  },

  /* ---------- profile ---------- */
  async profile() {
    Auth.init();
    if (!Auth.isLoggedIn()) { window.location.href = 'login.html'; return; }
    Pages._initDashNav();
    Pages._initLogout();

    // Load profile from backend
    const res = await API.get('/api/profile');
    const user = res.user || State.user || {};

    // Populate fields
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val || ''; };
    const setText = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val || ''; };
    set('profileName', user.full_name);
    set('profileEmail', user.email);
    set('profilePhone', user.phone);
    set('profileLocation', user.location_text);
    set('profileBusiness', user.business_name);
    setText('profileRole', (user.role || '').charAt(0).toUpperCase() + (user.role||'').slice(1));
    setText('profileRatingAvg', user.rating_avg ? user.rating_avg.toFixed(1) : '--');
    setText('profileRatingCount', user.rating_count ? `${user.rating_count} reviews` : '0 reviews');

    // Save profile
    document.getElementById('saveProfileBtn')?.addEventListener('click', async () => {
      const payload = {
        full_name:     document.getElementById('profileName')?.value.trim(),
        phone:         document.getElementById('profilePhone')?.value.trim(),
        location_text: document.getElementById('profileLocation')?.value.trim(),
        business_name: document.getElementById('profileBusiness')?.value.trim(),
      };
      const saveRes = await API.put('/api/profile', payload);
      if (saveRes.success || saveRes.user) {
        UI.showToast('✅ Profile updated!');
        Auth.save(State.token, { ...State.user, ...payload }, State.role);
      } else {
        UI.showToast(saveRes.error || 'Could not save profile');
      }
    });

    // Change password
    document.getElementById('changePasswordBtn')?.addEventListener('click', async () => {
      const current = document.getElementById('currentPassword')?.value;
      const newpw   = document.getElementById('newPassword')?.value;
      const confirm = document.getElementById('confirmPassword')?.value;
      if (!current || !newpw) { UI.showToast('Fill in all password fields'); return; }
      if (newpw !== confirm)  { UI.showToast('Passwords do not match'); return; }
      if (newpw.length < 8)   { UI.showToast('Password must be at least 8 characters'); return; }
      const pwRes = await API.post('/api/auth/change-password', { current_password: current, new_password: newpw });
      UI.showToast(pwRes.message || pwRes.error || 'Done');
      if (pwRes.message) {
        ['currentPassword','newPassword','confirmPassword'].forEach(id => {
          const el = document.getElementById(id); if (el) el.value = '';
        });
      }
    });
  },

  /* ---------- shared helpers ---------- */
  _initDashNav() {
    // Set role-aware home nav target for profile page
    const roleDashMap = {
      driver:    'dashboard_driver.html',
      mechanic:  'dashboard_mechanic.html',
      spareshop: 'dashboard_spareshop.html',
      admin:     'dashboard_admin.html',
    };
    const navHome = document.getElementById('navHome');
    if (navHome && State.role) {
      navHome.dataset.target = roleDashMap[State.role] || 'index.html';
    }

    document.querySelectorAll('.dash-nav-tab, .nav-tab').forEach(tab => {
      tab.addEventListener('click', function() {
        const target = this.dataset.target;
        if (target && target !== '#') window.location.href = target;
      });
    });
  },

  _initLogout() {
    document.querySelectorAll('[data-logout], #logoutBtn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (confirm('Log out?')) Auth.logout();
      });
    });
  },

  _initAvailability() {
    const toggle    = document.getElementById('availabilityToggle');
    const statusVal = document.getElementById('availStatusValue');
    const statusBg  = document.getElementById('availStatusBg');
    const switchBtn = document.getElementById('switchAvailBtn');

    const apply = available => {
      State.availability = available;
      if (statusVal) statusVal.textContent = available ? 'AVAILABLE' : 'UNAVAILABLE';
      if (statusBg)  statusBg.style.background = available ? 'var(--green-btn)' : '#6b7280';
      if (switchBtn) {
        switchBtn.textContent = available ? 'Switch to: Unavailable' : 'Switch to: Available';
        switchBtn.className   = available ? 'btn btn-red btn-full' : 'btn btn-green btn-full';
      }
      API.put('/api/profile/availability', { available });
      WS.emit('availability_change', { user_id: State.user?.id, available });
    };

    toggle?.addEventListener('change', () => apply(toggle.checked));
    switchBtn?.addEventListener('click', () => {
      if (toggle) { toggle.checked = !toggle.checked; apply(toggle.checked); }
    });
  },

  _initChatTabs() {
    document.querySelectorAll('.nav-tab[data-page]').forEach(tab => {
      tab.addEventListener('click', () => {
        const page = tab.dataset.page;
        document.querySelectorAll('.chat-page-section').forEach(s => s.style.display = 'none');
        const section = document.getElementById(`page-${page}`);
        if (section) section.style.display = 'flex';
        document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
      });
    });
    // Show first tab by default
    const first = document.querySelector('.nav-tab[data-page]');
    if (first) first.click();
  },

  _initMessageInput() {
    const input   = document.querySelector('.msg-input');
    const sendBtn = document.querySelector('.msg-send-btn');
    const send = () => {
      const msg = input?.value.trim();
      if (!msg || !State.currentConvId) return;
      WS.sendMessage(State.currentConvId, msg);
      UI.appendMessage({ sender_id: State.user?.id, message: msg, created_at: new Date().toISOString() });
      if (input) input.value = '';
    };
    sendBtn?.addEventListener('click', send);
    input?.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });

    // Mic button (visual only)
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

    const area = document.querySelector('.messages-area');
    if (area) area.scrollTop = area.scrollHeight;
  },

  async _loadNotifications(listId) {
    const panel = document.getElementById(listId);
    if (!panel) return;
    const res = await API.get('/api/notifications');
    const notifs = res.notifications || [];
    panel.innerHTML = notifs.length
      ? notifs.slice(0,10).map(n => `<div class="notif-item">${UI.escapeHtml(n.message || n)}</div>`).join('')
      : '<div class="notif-item" style="color:#9ca3af;">No notifications yet.</div>';
  },

  _pollNotifications(listId) {
    setInterval(async () => {
      if (!State.token) return;
      const res = await API.get('/api/dashboard/ping');
      if (res.notifications?.length) {
        res.notifications.forEach(n => UI.addNotification(n));
      }
    }, 30000);
  },
};

/* ── Password toggle ── */
document.querySelectorAll('.toggle-password, [data-toggle-pw]').forEach(btn => {
  btn.addEventListener('click', () => {
    const input = btn.previousElementSibling || document.getElementById(btn.dataset.togglePw || btn.dataset.target);
    if (input) {
      input.type = input.type === 'password' ? 'text' : 'password';
      btn.textContent = input.type === 'password' ? '👁' : '🙈';
    }
  });
});

/* ── Expose globals ── */
window.MechApp = { Auth, API, WS, Geo, UI, Pages, State, Storage };

/* ── Auto-init ── */
document.addEventListener('DOMContentLoaded', () => {
  Auth.init();
  document.body.classList.add('page-enter');

  const path = window.location.pathname.split('/').pop() || 'index.html';
  const pageMap = {
    'index.html':              Pages.index,
    'register_driver.html':    Pages.registerDriver,
    'register_mechanic.html':  Pages.registerMechanic,
    'register_spareshop.html': Pages.registerSpareshop,
    'dashboard_driver.html':   Pages.dashboardDriver,
    'dashboard_mechanic.html': Pages.dashboardMechanic,
    'dashboard_spareshop.html':Pages.dashboardSpareParts,
    'dashboard_admin.html':    Pages.dashboardAdmin,
    'chat.html':               Pages.chat,
    'profile.html':            Pages.profile,
  };

  const initFn = pageMap[path];
  if (initFn) initFn.call(Pages);
});

/* ── Service Worker ── */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js', { scope: '/' })
      .then(reg => {
        reg.addEventListener('updatefound', () => {
          const nw = reg.installing;
          nw?.addEventListener('statechange', () => {
            if (nw.state === 'installed' && navigator.serviceWorker.controller)
              UI.showToast('🔄 App updated — refresh to get the latest version', 6000);
          });
        });
      })
      .catch(err => console.warn('[SW] Registration failed:', err));
    let refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!refreshing) { refreshing = true; window.location.reload(); }
    });
  });
}

/* ── Admin guard ── */
(function adminGuard() {
  const path = window.location.pathname.split('/').pop();
  if (path === 'dashboard_admin.html') {
    Auth.init();
    if (!Auth.isLoggedIn()) { window.location.replace('index.html'); return; }
    const u = Storage.get('mech_user');
    if (!u || u.role !== 'admin') { window.location.replace('index.html'); return; }
    fetch(`${MECH_CONFIG.API_BASE}/api/auth/me`, { headers: Auth.headers() })
      .then(r => r.json())
      .then(d => { if (!d.user || d.user.role !== 'admin') window.location.replace('index.html'); })
      .catch(() => {});
  }
})();
