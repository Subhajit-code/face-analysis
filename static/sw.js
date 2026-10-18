/**
 * FaceVault Progressive Web App (PWA) Service Worker
 */
const CACHE_NAME = 'facevault-cache-v3';
const STATIC_ASSETS = [
    '/',
    '/static/css/style.css',
    '/static/js/app.js',
    '/static/js/camera.js',
    '/static/js/audio.js',
    '/static/js/fingerprint.js',
    '/static/img/icon-192.png',
    '/static/img/icon-512.png',
    '/static/img/apple-touch-icon.png',
    '/static/img/favicon.png',
    '/static/img/default_avatar.png',
    '/static/audio_cache/mismatch_female.mp3',
    '/static/audio_cache/verified_female.mp3',
    '/static/audio_cache/alert_female.mp3',
    '/static/audio_cache/instructions_female.mp3',
    '/static/audio_cache/mismatch_male.mp3',
    '/static/audio_cache/verified_male.mp3',
    '/static/audio_cache/alert_male.mp3',
    '/static/audio_cache/instructions_male.mp3',
    '/static/audio_cache/registered_female.mp3',
    '/static/audio_cache/registered_male.mp3',
    '/static/audio_cache/credentials_female.mp3',
    '/static/audio_cache/credentials_male.mp3',
    '/static/audio_cache/geo_restricted_female.mp3',
    '/static/audio_cache/geo_restricted_male.mp3',
    '/static/audio_cache/geo_verified_female.mp3',
    '/static/audio_cache/geo_verified_male.mp3',
    '/static/audio_cache/geo_captured_female.mp3',
    '/static/audio_cache/geo_captured_male.mp3'
];

// Install event: cache app shell assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(STATIC_ASSETS).catch((err) => {
                console.warn('Non-critical asset cache skip:', err);
            });
        }).then(() => self.skipWaiting())
    );
});

// Activate event: clean up outdated caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch event: network-first for everything. This means a fresh deploy is picked up on the
// very next load without anyone needing to manually clear site data — the service worker only
// ever falls back to its cache when the network request actually fails (i.e. genuinely offline).
// (A pure cache-first strategy was used previously, which is why deployed changes kept appearing
// stale: once a file was cached, it was served forever regardless of what was actually deployed,
// since nothing ever forced a fresh network fetch for it again.)
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Bypass caching for all API calls and dynamic data
    if (url.pathname.startsWith('/api/')) {
        return event.respondWith(fetch(event.request));
    }

    event.respondWith(
        fetch(event.request).then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200 && event.request.method === 'GET') {
                const clone = networkResponse.clone();
                caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
            }
            return networkResponse;
        }).catch(() => {
            return caches.match(event.request).then((cachedResponse) => {
                if (cachedResponse) return cachedResponse;
                if (event.request.mode === 'navigate') {
                    return caches.match('/');
                }
            });
        })
    );
});
