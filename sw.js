/* Service worker de la yincana.
   Red de seguridad: en la v2 hay cobertura, pero un bache momentáneo no puede
   tirar la página. Cachea la app y las teselas ya vistas.

   Sube el número de VERSION cada vez que edites index.html, sw.js o el vendor,
   o los móviles seguirán sirviendo la copia vieja. */

const VERSION = "yincana-v15";

const ARCHIVOS = [
  "./",
  "./index.html",
  "./manifest.json",
  // Leaflet vendorizado: sin esto la página no arranca sin cobertura (la v2 usa
  // mapa vivo). Las teselas se cachean solas al verlas (fetch → caché).
  "./vendor/leaflet/leaflet.js",
  "./vendor/leaflet/leaflet.css",
  "./vendor/leaflet/images/marker-icon.png",
  "./vendor/leaflet/images/marker-icon-2x.png",
  "./vendor/leaflet/images/marker-shadow.png",
  "./vendor/leaflet/images/layers.png",
  "./vendor/leaflet/images/layers-2x.png",
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

function guardarEnCache(req, resp){
  const copia = resp.clone();
  caches.open(VERSION).then(c => c.put(req, copia)).catch(() => {});
}

self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const ruta = new URL(e.request.url).pathname;

  // /api: dinámico (sesión, contenido, progreso). Red directa, sin cachear: el
  // cliente ya guarda su estado y su contenido en localStorage para el offline.
  if (ruta.startsWith("/api/")) return;

  // Teselas: inmutables. Caché primero (rápido y sobrevive a cortes); si no está,
  // se baja y se guarda.
  if (ruta.startsWith("/tiles/")){
    e.respondWith(
      caches.match(e.request).then(c => c || fetch(e.request).then(r => {
        guardarEnCache(e.request, r); return r;
      }).catch(() => c))
    );
    return;
  }

  // Resto (app, vendor, imágenes): red primero, caché de respaldo. Así ves tus
  // cambios al editar con cobertura, y sin señal sigue tirando de la copia.
  e.respondWith(
    fetch(e.request)
      .then(r => { guardarEnCache(e.request, r); return r; })
      .catch(() =>
        caches.match(e.request, { ignoreSearch: true })
          .then(r => r || caches.match("./index.html"))
      )
  );
});
