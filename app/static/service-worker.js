const CACHE = 'personal-agent-shell-v2';
const ASSETS = ['/', '/static/styles.css', '/static/app.js', '/static/icon.svg', '/manifest.webmanifest'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.pathname.startsWith('/api/')) return;
  // 网络优先：服务跑在本机/局域网，响应极快，优先拿最新代码。
  // 原来用缓存优先，导致改完前端后浏览器一直读旧的 app.js，必须手动升版本号才生效。
  // 断网或请求失败时回落到缓存，保留离线打开界面的能力。
  event.respondWith(
    fetch(event.request).then(response => {
      if (response.ok && url.origin === self.location.origin) {
        const copy = response.clone();
        caches.open(CACHE).then(cache => cache.put(event.request, copy)).catch(() => {});
      }
      return response;
    }).catch(() => caches.match(event.request).then(cached => cached || caches.match('/')))
  );
});
