/**
 * Service worker: app shell only.
 *
 * What it caches: the HTML, the stylesheet, the modules, the manifest. That is
 * what makes ORCA open instantly on a bad link and installable as an app.
 *
 * What it deliberately does NOT cache: API responses. Serving a stale marine
 * forecast from a transparent HTTP cache is precisely the failure this product
 * exists to avoid - the user would have no way to know the reading was old.
 * Saved answers live in the app's own store instead, where they are shown with
 * the time they were retrieved and labelled as saved.
 */

const VERSION = 'orca-shell-v3';
const SHELL = [
  '/app/',
  '/app/index.html',
  '/app/styles/app.css',
  '/app/js/main.js',
  '/app/js/config.js',
  '/app/js/api.js',
  '/app/js/state.js',
  '/app/js/i18n.js',
  '/app/js/util/dom.js',
  '/app/js/util/format.js',
  '/app/js/services/net.js',
  '/app/js/services/geolocation.js',
  '/app/js/services/voice.js',
  '/app/js/services/cache.js',
  '/app/js/views/ask.js',
  '/app/js/views/answer.js',
  '/app/js/views/evidence.js',
  '/app/js/views/trace.js',
  '/app/js/views/map.js',
  '/app/js/views/screens.js',
  '/app/js/views/settings.js',
  '/app/js/views/progress.js',
  '/manifest.webmanifest',
  '/offline.html',
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(VERSION);
    // Individually, so one missing file cannot fail the whole install.
    await Promise.all(SHELL.map((url) =>
      cache.add(url).catch(() => undefined)));
    self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name !== VERSION)
      .map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // API traffic is never served from the cache. If the network cannot answer,
  // the app handles it and tells the user - it does not get a silent old value.
  if (url.pathname.startsWith('/api/')) return;

  event.respondWith((async () => {
    const cached = await caches.match(request);
    if (cached) {
      // Refresh in the background so the shell stays current without the user
      // waiting for it.
      event.waitUntil((async () => {
        try {
          const fresh = await fetch(request);
          if (fresh.ok) (await caches.open(VERSION)).put(request, fresh.clone());
        } catch { /* offline: the cached shell is correct */ }
      })());
      return cached;
    }
    try {
      const response = await fetch(request);
      if (response.ok && (url.pathname.startsWith('/app/')
          || url.pathname === '/manifest.webmanifest')) {
        (await caches.open(VERSION)).put(request, response.clone());
      }
      return response;
    } catch {
      if (request.mode === 'navigate') {
        return (await caches.match('/offline.html'))
          || new Response('Offline', { status: 503 });
      }
      return new Response('', { status: 504 });
    }
  })());
});
