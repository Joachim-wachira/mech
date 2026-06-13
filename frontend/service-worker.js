/* ============================================================
   MECH PLATFORM — Service Worker
   Strategy: Cache-First for static assets, Network-First for API
   Save this file at: frontend/service-worker.js
   ============================================================ */

'use strict';

const CACHE_NAME     = 'mech-v1.1.0';   // bumped — forces old cache eviction
const API_CACHE_NAME = 'mech-api-v1.1.0';

/* ── Assets to pre-cache on install ─────────────────────────── */
const PRECACHE_ASSETS = [
  '/',
  '/index.html',
  '/register_driver.html',
  '/register_mechanic.html',
  '/register_spareshop.html',
  '/dashboard_driver.html',
  '/dashboard_mechanic.html',
  '/dashboard_spareshop.html',
  '/chat.html',
  '/css/styles.css',
  '/js/app.js',
  '/config.js',
  '/logo.SVG',
  '/manifest.json',
  '/offline.html',
];

/* ── Offline fallback page ───────────────────────────────────── */
const OFFLINE_PAGE = '/offline.html';

/* ── API routes — network-first, short cache fallback ────────── */
const API_ORIGIN = self.location.origin;  // same origin; adjust if backend is separate

/* ══════════════════════════════════════════════════════════════
   INSTALL — pre-cache all static assets
   ══════════════════════════════════════════════════════════════ */
self.addEventListener('install', (event) => {
  console.log('[SW] Installing — cache:', CACHE_NAME);
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_ASSETS).catch((err) => {
        // Non-fatal: log missing assets but don't block install
        console.warn('[SW] Pre-cache partial failure:', err);
      });
    }).then(() => {
      // Activate immediately without waiting for old SW to finish
      return self.skipWaiting();
    })
  );
});

/* ══════════════════════════════════════════════════════════════
   ACTIVATE — clean up old caches
   ══════════════════════════════════════════════════════════════ */
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating — clearing old caches');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME && name !== API_CACHE_NAME)
          .map((name) => {
            console.log('[SW] Deleting old cache:', name);
            return caches.delete(name);
          })
      );
    }).then(() => {
      // Take control of all open pages immediately
      return self.clients.claim();
    })
  );
});

/* ══════════════════════════════════════════════════════════════
   FETCH — route-based caching strategies
   ══════════════════════════════════════════════════════════════ */
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // ── Skip non-GET and browser extension requests ─────────────
  if (request.method !== 'GET') return;
  if (!request.url.startsWith('http'))  return;

  // ── API calls → Network-First with short cache fallback ─────
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirstWithCache(request, API_CACHE_NAME, 300));
    return;
  }

  // ── Google Fonts → Cache-First (long-lived) ─────────────────
  if (url.hostname.includes('fonts.googleapis.com') ||
      url.hostname.includes('fonts.gstatic.com')) {
    event.respondWith(cacheFirst(request, CACHE_NAME));
    return;
  }

  // ── Socket.IO handshake → always network, never cache ───────
  if (url.pathname.startsWith('/socket.io/')) return;

  // ── HTML pages → Network-First so updates reach users immediately ──
  // Falls back to cache when offline. CSS/JS/SVG stay cache-first for speed.
  if (request.destination === 'document' || url.pathname.endsWith('.html') || url.pathname === '/') {
    event.respondWith(networkFirstWithCache(request, CACHE_NAME, 3600));
    return;
  }

  // ── CSS, JS, SVG, images → Cache-First (long-lived assets) ──
  event.respondWith(cacheFirstWithOfflineFallback(request));
});

/* ══════════════════════════════════════════════════════════════
   STRATEGIES
   ══════════════════════════════════════════════════════════════ */

/**
 * Cache-First: serve from cache; fetch & update cache on miss.
 * Falls back to offline.html for navigation requests.
 */
async function cacheFirstWithOfflineFallback(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const networkResponse = await fetch(request);
    if (networkResponse && networkResponse.status === 200) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch {
    // Navigation request → serve offline page
    if (request.mode === 'navigate') {
      const offlinePage = await caches.match(OFFLINE_PAGE);
      if (offlinePage) return offlinePage;
    }
    // Non-navigation (image, font, etc.) → return empty 503
    return new Response('Service unavailable offline', {
      status: 503,
      statusText: 'Service Unavailable',
      headers: { 'Content-Type': 'text/plain' },
    });
  }
}

/**
 * Cache-First: pure cache then network, no offline fallback.
 * Best for third-party static assets (fonts, CDN icons).
 */
async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response && response.status === 200) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('', { status: 503 });
  }
}

/**
 * Network-First: try network, cache on success; serve cache on
 * failure. maxAgeSeconds controls how long cached API responses
 * are considered fresh enough to serve offline.
 */
async function networkFirstWithCache(request, cacheName, maxAgeSeconds) {
  const cache = await caches.open(cacheName);
  try {
    const networkResponse = await fetch(request);
    if (networkResponse && networkResponse.status === 200) {
      // Add a timestamp header so we can check freshness later
      const cloned = networkResponse.clone();
      const headers = new Headers(cloned.headers);
      headers.set('sw-fetched-at', Date.now().toString());
      const timestampedResponse = new Response(await cloned.blob(), {
        status: cloned.status,
        statusText: cloned.statusText,
        headers,
      });
      cache.put(request, timestampedResponse);
    }
    return networkResponse;
  } catch {
    // Network failed → try cache
    const cached = await cache.match(request);
    if (cached) {
      const fetchedAt = cached.headers.get('sw-fetched-at');
      const age = fetchedAt ? (Date.now() - parseInt(fetchedAt)) / 1000 : Infinity;
      if (age < maxAgeSeconds) return cached;
    }
    return new Response(JSON.stringify({ error: 'Offline — cached data unavailable' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

/* ══════════════════════════════════════════════════════════════
   PUSH NOTIFICATIONS (future)
   ══════════════════════════════════════════════════════════════ */
self.addEventListener('push', (event) => {
  if (!event.data) return;
  let data = {};
  try { data = event.data.json(); } catch { data = { title: 'mech', body: event.data.text() }; }

  event.waitUntil(
    self.registration.showNotification(data.title || 'mech', {
      body: data.body || 'You have a new notification',
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-72.png',
      tag: data.tag || 'mech-notification',
      data: { url: data.url || '/' },
      vibrate: [100, 50, 100],
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url === targetUrl && 'focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});

/* ══════════════════════════════════════════════════════════════
   BACKGROUND SYNC (future)
   ══════════════════════════════════════════════════════════════ */
self.addEventListener('sync', (event) => {
  if (event.tag === 'mech-sync-messages') {
    event.waitUntil(syncPendingMessages());
  }
});

async function syncPendingMessages() {
  // Placeholder: in production, read queued messages from IndexedDB
  // and replay them to the backend once online.
  console.log('[SW] Background sync: mech-sync-messages');
}
