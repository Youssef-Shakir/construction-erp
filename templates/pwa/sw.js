/* Construction ERP service worker - version {{ version }}
 *
 * - Static assets: cache-first (precached at install, refreshed per version).
 * - Page navigations: always from the network; offline -> offline page.
 *   Financial pages and attachments are NEVER cached on the device.
 */
const CACHE = 'erp-static-{{ version }}';
const OFFLINE_URL = '{{ offline_url }}';
const STATIC_PREFIX = '{{ static_prefix }}';
const PRECACHE = {{ precache_json|safe }};

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('erp-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;                 // uploads, posting, share target: network only
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  if (url.pathname.startsWith(STATIC_PREFIX)) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy));
        }
        return res;
      }))
    );
  }
  // Everything else (HTMX partials, attachments, reports): straight to network.
});
