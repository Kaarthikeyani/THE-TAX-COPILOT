/* Network-first service worker: the app always loads fresh from the server; the cached shell is used only when offline.
   API calls are never cached (they hold private data). */
const CACHE = 'copilot-shell-v3';
const SHELL = ['/', 'index.html', 'styles.css', 'v3.css', 'app.js', 'account.js', 'accuracy.js', 'monthly.js', 'icon.svg'];
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  const isShell = u.pathname === '/' || /\.(html|css|js|svg|webmanifest)$/.test(u.pathname);
  if (!isShell) return; // everything else (the API) goes straight to the network
  e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); return r; })
    .catch(() => caches.match(e.request).then(r => r || caches.match('/'))));
});
