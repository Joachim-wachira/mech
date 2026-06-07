// ============================================================
// MECH PLATFORM — Config Example
// Copy this file to config.js and fill in your values.
// DO NOT commit config.js to version control.
// ============================================================

window.MechConfig = {
  // Backend API base URL (no trailing slash)
  API_BASE: 'https://mech-backend-h7nk.onrender.com',

  // WebSocket server URL
  WS_URL: 'https://mech-backend-h7nk.onrender.com',

  // App metadata
  APP_NAME: 'mech',
  APP_VERSION: '1.0.0',

  // Feature flags
  FEATURES: {
    GEOLOCATION: true,        // Enable browser geolocation
    WEBSOCKETS: true,         // Enable real-time WebSocket
    SMS_VERIFICATION: true,   // Enable SMS phone verification
    VOICE_CALLS: true,        // Enable native voice call logs
    PUSH_NOTIFICATIONS: false, // Browser push notifications (future)
  },

  // Map configuration (OpenStreetMap / Nominatim — no API key needed)
  MAPS: {
    TILE_URL: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    DEFAULT_LAT: -1.2921,   // Nairobi, Kenya
    DEFAULT_LNG: 36.8219,
    DEFAULT_ZOOM: 13,
  },

  // Currency
  CURRENCY: 'KES',
  CURRENCY_LOCALE: 'en-KE',

  // Pagination
  NEARBY_RADIUS_KM: 25,
  PAGE_SIZE: 20,
};
