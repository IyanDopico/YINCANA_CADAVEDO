/* Service worker de la yincana.
   Objetivo: que la página siga funcionando sin cobertura. El GPS no la
   necesita (GNSS sólo recibe), pero la web sí, así que la cacheamos entera.

   Sube el número de VERSION cada vez que edites index.html o el mapa,
   o los móviles seguirán sirviendo la copia vieja. */

const VERSION = "yincana-v6";

const ARCHIVOS = [
  "./",
  "./index.html",
  "./mapa-pueblo.jpg",
  "./mapa-regalina.jpg",
  "./manifest.json",
];

self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(VERSION).then(c =>
      // addAll falla entero si un archivo falta; los añadimos uno a uno
      // para que la ausencia del mapa no rompa la instalación.
      Promise.all(ARCHIVOS.map(u => c.add(u).catch(() => {})))
    )
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;

  // Red primero, caché de respaldo. Así ves tus cambios al editar en casa
  // con cobertura, pero en el pueblo sin señal sigue tirando de la copia.
  e.respondWith(
    fetch(e.request)
      .then(r => {
        const copia = r.clone();
        caches.open(VERSION).then(c => c.put(e.request, copia)).catch(() => {});
        return r;
      })
      .catch(() =>
        caches.match(e.request, { ignoreSearch: true })
          .then(r => r || caches.match("./index.html"))
      )
  );
});
