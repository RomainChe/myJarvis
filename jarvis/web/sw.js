// Service worker : cache du shell statique uniquement. Jamais /api/*, jamais une requête avec Authorization.
const CACHE = 'jarvis-shell-v18';
const SHELL = ['/', '/index.html', '/app.css', '/app.js', '/manifest.webmanifest', '/icon.svg', '/icon-192.png',
               '/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

// Notification générique (le serveur n'envoie jamais de contenu). Rien à signaler si l'appli est déjà visible.
self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data.json(); } catch { /* contenu illisible : notification par défaut */ }
  e.waitUntil(self.clients.matchAll({ type: 'window' }).then((list) => {
    if (list.some((c) => c.visibilityState === 'visible')) return undefined;
    return self.registration.showNotification(String(d.title || 'Jarvis').slice(0, 60),
      { body: String(d.body || '').slice(0, 120), tag: 'jarvis', renotify: true, icon: '/icon-192.png' });
  }));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: 'window' }).then((list) => (list.length ? list[0].focus() : self.clients.openWindow('/'))));
});

const purge = () => caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k))));

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;

  if (url.pathname.startsWith('/api/') || req.headers.has('Authorization')) {
    // Passage direct, sans mise en cache ; un 401 vide les caches.
    e.respondWith(fetch(req).then((res) => (res.status === 401 ? purge().then(() => res) : res)));
    return;
  }
  if (!SHELL.includes(url.pathname)) return;

  // Réseau d'abord (mises à jour immédiates), cache en secours hors ligne.
  e.respondWith(
    fetch(req)
      .then((res) => {
        // Seulement une réponse directe de notre origine : ni redirection, ni erreur, ni réponse opaque.
        if (res.ok && res.type === 'basic' && !res.redirected) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || caches.match('/'))),
  );
});
