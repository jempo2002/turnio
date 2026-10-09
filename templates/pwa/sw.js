/* Service worker de Turnio (T9). Lo arma app/routes/pwa.py: cambia cuando
   cambia un estatico, y entonces el navegador instala este y borra la cache
   vieja.

   Que hace y que no:
   - Estaticos con ?v= (CSS, JS, iconos): de la cache; si no estan, de la red
     y se guardan. Su URL cambia con el archivo, nunca quedan viejos.
   - Paginas: siempre de la red (dependen de la sesion y no se cachean). Sin
     senal, la pagina "Sin conexion".
   - /api, logos, POST y otros dominios: no los toca. La agenda y la caja
     necesitan red: no hay modo offline de datos. */
'use strict';

var CACHE = 'turnio-{{ version }}';
var PRECARGA = {{ precarga | tojson }};
var OFFLINE = PRECARGA[0];

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(PRECARGA); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (nombres) {
    return Promise.all(nombres.filter(function (n) { return n.indexOf('turnio-') === 0 && n !== CACHE; })
      .map(function (n) { return caches.delete(n); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(function () { return caches.match(OFFLINE); }));
    return;
  }
  if (url.pathname.indexOf('/static/') === 0 && url.searchParams.has('v')) {
    e.respondWith(caches.match(req).then(function (guardada) {
      return guardada || fetch(req).then(function (resp) {
        if (resp.ok) {
          var copia = resp.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copia); });
        }
        return resp;
      });
    }));
  }
});
