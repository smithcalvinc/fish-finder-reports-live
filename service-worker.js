const CACHE_VERSION="ffo-reports-pwa-v31";
const STATIC_CACHE=`${CACHE_VERSION}-static`;
const PAGE_CACHE=`${CACHE_VERSION}-pages`;

const APP_SHELL=[
  "./","./index.html",
  "./idaho-county-reports.html","./montana-county-reports.html",
  "./utah-county-reports.html","./colorado-county-reports.html",
  "./wyoming-county-reports.html",
  "./brand-shell.css","./brand-shell.js","./homepage.js","./county-query.js","./pwa.js",
  "./share-water.html","./force-update.html","./manifest.json",
  "./app-icon-192.png","./app-icon-512.png","./app-icon-maskable-512.png",
  "./apple-touch-icon.png","./ffo-logo-main.png","./ffo-hero.jpg",
  "./ffo-reports-hero-wide.jpg","./ffo-report-card-1.jpg",
  "./ffo-report-card-2.jpg","./ffo-report-card-3.jpg",
  "./ffo-water-divider.jpg","./official-sources.html","./submit-report.html",
  "./local-fishing-partners.html",
  "./report-water.html","./404.html","./site_config.js",
  "./official_state_sources.js","./official_water_overrides.js",
  "./regional_water_search.js","./official_species_data.js",
  "./fishing_report_search.js"
];

const NETWORK_FIRST_FILES=[
  "index.html","brand-shell.js","brand-shell.css","homepage.js","county-query.js","pwa.js","manifest.json",
  "recent_fishing_reports.js","community_fishing_reports.js","update_status.js",
  "regional_water_search.js","official_water_overrides.js",
  "idaho_fishing_report_database.js","idaho_fishing_report_database.json",
  "montana_fishing_report_database.js","montana_fishing_report_database.json",
  "montana_public_fishing_access.js","montana_public_fishing_access.json",
  "utah_public_fishing_access.json","colorado_public_fishing_access.json",
  "wyoming_public_fishing_access.json","wyoming_public_fishing_access.js",
  "wyoming_fishing_report_database.json","wyoming_fishing_report_database.js",
  "colorado_public_fishing_access.js","colorado_fishing_report_database.json",
  "colorado_fishing_report_database.js","utah_public_fishing_access.js",
  "utah_fishing_report_database.json","utah_fishing_report_database.js"
];

self.addEventListener("install",event=>{
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache=>cache.addAll(APP_SHELL))
      .then(()=>self.skipWaiting())
  );
});

self.addEventListener("activate",event=>{
  event.waitUntil(
    caches.keys()
      .then(keys=>Promise.all(keys
        .filter(key=>![STATIC_CACHE,PAGE_CACHE].includes(key))
        .map(key=>caches.delete(key))))
      .then(()=>self.clients.claim())
  );
});

async function networkFirst(request,cacheName){
  const cache=await caches.open(cacheName);
  try{
    const response=await fetch(request,{cache:"no-store"});
    if(response&&response.ok)await cache.put(request,response.clone());
    return response;
  }catch(error){
    const cached=await cache.match(request);
    if(cached)return cached;
    if(request.mode==="navigate")return(await caches.match("./index.html"))||Response.error();
    throw error;
  }
}

async function cacheFirst(request){
  const cached=await caches.match(request);
  if(cached)return cached;
  const response=await fetch(request);
  if(response&&response.ok){
    const cache=await caches.open(STATIC_CACHE);
    await cache.put(request,response.clone());
  }
  return response;
}

self.addEventListener("fetch",event=>{
  const request=event.request;
  if(request.method!=="GET")return;
  const url=new URL(request.url);
  if(url.origin!==self.location.origin)return;

  if(request.mode==="navigate"){
    event.respondWith(networkFirst(request,PAGE_CACHE));
    return;
  }

  if(NETWORK_FIRST_FILES.some(name=>url.pathname.endsWith(name))){
    event.respondWith(networkFirst(request,PAGE_CACHE));
    return;
  }

  event.respondWith(cacheFirst(request));
});

self.addEventListener("message",event=>{
  if(event.data==="SKIP_WAITING")self.skipWaiting();
  if(event.data==="CLEAR_FFO_CACHES"){
    event.waitUntil(caches.keys().then(keys=>Promise.all(keys.map(key=>caches.delete(key)))));
  }
});
