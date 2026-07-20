const CACHE_VERSION = "ffo-reports-pwa-v2";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;

const APP_SHELL = [
  "./",
  "./index.html",
  "./brand-shell.css",
  "./brand-shell.js",
  "./pwa.js",
  "./manifest.json",
  "./app-icon-192.png",
  "./app-icon-512.png",
  "./app-icon-maskable-512.png",
  "./apple-touch-icon.png",
  "./ffo-logo-main.png",
  "./ffo-hero.jpg",
  "./ffo-water-divider.jpg",
  "./official-sources.html",
  "./submit-report.html",
  "./report-water.html",
  "./404.html",
  "./site_config.js",
  "./official_state_sources.js",
  "./official_water_overrides.js",
  "./regional_water_search.js",
  "./official_species_data.js"
];

const FRESH_DATA_FILES = [
  "recent_fishing_reports.js",
  "community_fishing_reports.js",
  "update_status.js"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys
          .filter(key => ![STATIC_CACHE, PAGE_CACHE].includes(key))
          .map(key => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response && response.ok) cache.put(request, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) return cached;
    if (request.mode === "navigate") {
      return (await caches.match("./index.html")) || Response.error();
    }
    throw error;
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok) {
    const cache = await caches.open(STATIC_CACHE);
    cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request, PAGE_CACHE));
    return;
  }

  if (FRESH_DATA_FILES.some(name => url.pathname.endsWith(name))) {
    event.respondWith(networkFirst(request, PAGE_CACHE));
    return;
  }

  event.respondWith(cacheFirst(request));
});

self.addEventListener("message", event => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});
