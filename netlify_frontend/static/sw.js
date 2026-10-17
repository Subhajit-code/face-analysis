/**
 * FaceVault Progressive Web App (PWA) Service Worker
 */
const CACHE_NAME = 'facevault-cache-v1';
const STATIC_ASSETS = [
    '/',
    '/static/css/style.css',
    '/static/js/app.js',
    '/static/js/camera.js',
    '/static/js/audio.js',
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
    '/static/audio_cache/instructions_male.mp3'
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

// Fetch event: network-first for API, cache-first for static shell
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Bypass caching for all API calls and dynamic data
    if (url.pathname.startsWith('/api/')) {
        return event.respondWith(fetch(event.request));
    }

    // Cache-first falling back to network for static shell
    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) {
                return cachedResponse;
            }
            return fetch(event.request).then((networkResponse) => {
                if (networkResponse && networkResponse.status === 200 && event.request.method === 'GET') {
                    const clone = networkResponse.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                }
                return networkResponse;
            }).catch(() => {
                // If offline and request is for page, return cached root
                if (event.request.mode === 'navigate') {
                    return caches.match('/');
                }
            });
        })
    );
});
