const CACHE = "emaus-hub-ui-v0.10.1";
const ASSETS = [
  "/",
  "/static/styles.css?v=0.10.1",
  "/static/app.js?v=0.10.1",
  "/static/brand-icon.png?v=0.10.1",
];
self.addEventListener("install", event => event.waitUntil(
  caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting())
));
self.addEventListener("activate", event => event.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
    .then(() => self.clients.claim())
));
self.addEventListener("fetch", event => {
  if (event.request.method !== "GET" || event.request.url.includes("/api/")) return;
  event.respondWith(fetch(event.request).then(response => {
    const copy = response.clone();
    caches.open(CACHE).then(cache => cache.put(event.request, copy));
    return response;
  }).catch(() => caches.match(event.request)));
});
