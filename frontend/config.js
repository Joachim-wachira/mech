// ============================================================
// MECH PLATFORM — Runtime Configuration
// ============================================================

window.MechConfig = {
  // ✅ FIXED: Points to your actual Render backend (no localhost)
  API_BASE: 'https://mech-backend-h7nk.onrender.com',
  WS_URL:   'wss://mech-backend-h7nk.onrender.com',
  APP_NAME: 'mech',
  APP_VERSION: '1.0.0',

  FEATURES: {
    GEOLOCATION: true,
    WEBSOCKETS: true,
    SMS_VERIFICATION: true,
    VOICE_CALLS: true,
    PUSH_NOTIFICATIONS: false,
  },

  MAPS: {
    TILE_URL: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    DEFAULT_LAT: -1.2921,
    DEFAULT_LNG: 36.8219,
    DEFAULT_ZOOM: 13,
  },

  CURRENCY: 'KES',
  CURRENCY_LOCALE: 'en-KE',
  NEARBY_RADIUS_KM: 25,
  PAGE_SIZE: 20,
};
