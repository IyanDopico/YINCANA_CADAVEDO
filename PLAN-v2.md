He revisado el código real (index.html, servidor.py, sw.js, contenido.json, pruebas_servidor.py) para que el plan encaje con los nombres y decisiones que ya existen. Aquí va.

---

# PLAN DE IMPLEMENTACIÓN — Yincana v2

## 1 · Arquitectura de un vistazo

**Idea rectora:** el motor de juego v1 no se toca casi. Lo que cambia es de dónde salen los píxeles del mapa (imagen estática → teselas Leaflet) y cómo se proyecta lat/lon a pantalla (`aPixel` → `map.latLngToContainerPoint` / `map.project`). Todo lo demás (física, avisos, medallas, persistencia, merge) se reutiliza.

### Cliente (`index.html` + `/vendor/leaflet/`)
```
┌─ #login (nuevo, tapa todo hasta elegir identidad) ──────────┐
│  admin 🧭 (PIN) · Himilce 🦊 · Orián 🐻 (botón directo)      │
└─────────────────────────────────────────────────────────────┘
┌─ #mapa  → Leaflet: L.tileLayer('/tiles/{z}/{x}/{y}.png')     │  REEMPLAZA la <img>
├─ capa niebla (L.Layer custom, patrón C, anclada a bounds)    │  REEMPLAZA #niebla+aPixel
├─ #hud    → marcador + sónar + latido (canvas propio)         │  REUTILIZA, cambia proyección
├─ rastro  → L.Polyline (geográfico, lo mueve Leaflet)         │  REEMPLAZA pintado a mano
└─ #autor / #admin (provisión y CRUD de estaciones)            │  AMPLÍA modo autor v1
```

### Servidor (`servidor.py`, stdlib + sqlite3)
Mismo proceso, mismo origen. Se le añaden: sesiones por cookie, CRUD de estaciones colocadas, y el proxy-caché de teselas. El resto (`/api/contenido`, `/api/progreso`, estático) sigue.

### Datos
- `yincana.db`: tablas nuevas `sesiones` y `estaciones`; `progreso` pasa a indexarse por `usuario` en vez de por token aleatorio.
- `cache_teselas/`: árbol `{z}/{x}/{y}.png` en disco (en `.gitignore`).

### Qué se REUTILIZA tal cual (con o sin retoque mínimo)
| Pieza | Estado en v2 |
|---|---|
| Suavizado exponencial `ALFA=0.4` sobre `pos.lat/lon` | Igual. Sigue alimentado por `watchPosition`. |
| Haversine (`distActual`) | Igual, es geográfico, ajeno al mapa. |
| Sónar (latido/pitido que acelera), `radioAudio` | Igual; su `requestAnimationFrame` propio en canvas pequeño. |
| `dentroSeguidas` (dos lecturas antes de avisar) + `body.encima` | Igual. |
| Medallas, pantalla de traslado entre capítulos | Igual. |
| Spawns capturables por proximidad | Igual (proyección aparte). |
| `sanear()` del estado de localStorage | Se amplía (rastro reproyectado a la capa Leaflet). |
| Merge no destructivo en servidor (`fusionar_progreso`) | Igual, cambia la clave (usuario). |
| Desbloqueo NFC por `?k=` con recarga | Igual, ahora con sesión por cookie encima. |
| `perdonarSiPasaronCerca` (perdón por rastro) | Igual. |

### Qué se REEMPLAZA
| v1 | v2 |
|---|---|
| `<img>` con `object-fit:contain` + `recto` | `L.map` + `L.tileLayer` a `/tiles/...` |
| `aPixel(lat,lon)` proyectando sobre `recto` | `map.latLngToContainerPoint` (HUD) / `map.project(ll, ZREF)` (niebla) |
| `#niebla` full-screen repintado en cada frame | `L.Layer` custom anclada a `bounds` (patrón C): se pica un agujero por punto, cero repintado en pan/zoom |
| `dentroDelMapa()` + capítulos por recorte de imagen | Un solo mapa vivo; el "capítulo" pasa a ser el `bounds`/vista activa (se puede conservar el concepto para el medallero y el traslado, pero ya no filtra píxeles) |
| `mapa-*.jpg` pre-generados | teselas OSM cacheadas en servidor |
| Coordenadas de estación en `contenido.json` | coordenadas capturadas en campo, en tabla `estaciones` |

**Decisión de fondo:** se conserva el service worker como red de seguridad (ya no es offline-first, pero el cache-first de teselas evita depender de OSM en el pueblo) y CERO CDN de terceros: Leaflet vendorizado, teselas proxeadas.

---

## 2 · Servidor (`servidor.py`)

### 2.1 Tablas nuevas (en `crear_tablas`)
```sql
CREATE TABLE IF NOT EXISTS sesiones(
    id      TEXT PRIMARY KEY,   -- secrets.token_urlsafe(32), 256 bits
    usuario TEXT NOT NULL,      -- 'admin' | 'himilce' | 'orian'
    creada  REAL
);
CREATE TABLE IF NOT EXISTS estaciones(
    k        TEXT PRIMARY KEY,  -- la clave NFC, la misma que ?k=
    capitulo TEXT,              -- 'pueblo' | 'regalina'
    nombre   TEXT,
    pista    TEXT,
    medalla  TEXT,
    lat      REAL,              -- NULL hasta que se coloca en campo
    lon      REAL,
    orden    INTEGER,           -- posición dentro del capítulo
    colocada REAL               -- timestamp de la última captura GPS
);
```
`progreso` no cambia de forma, pero su PK pasa de `token` a `usuario` (tres filas como mucho). Migración: como es familiar y aún no hay partida de verdad, lo más limpio es **empezar `yincana.db` de cero** para v2 (documentarlo en ARRANQUE.md). No merece la pena escribir migración.

### 2.2 Config arriba del fichero
```python
import os
USUARIOS  = ("admin", "himilce", "orian")
PIN_ADMIN = os.environ.get("YINCANA_PIN", "")        # sólo en el systemd, nunca en git
ORIGEN    = os.environ.get("YINCANA_ORIGEN", "https://yincana.iyando.qzz.io")
COOKIE      = "__Host-sesion"
DIAS_SESION = 180
UPSTREAM = os.environ.get("YINCANA_TESELAS",
                          "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
UA = "YincanaCadavedo/2.0 (+https://yincana.iyando.qzz.io; iyan.dopico@gmail.com)"
CACHE = RAIZ / "cache_teselas"
```

### 2.3 Sesiones y guardián CSRF
Funciones de dominio (reciben `c`, para probar en `:memory:`): `crear_sesion(c, usuario)`, `usuario_de_sesion(c, sid)`, `borrar_sesion(c, sid)`. Cadena de cookie a mano (`_galleta_sesion` / `_galleta_fuera`) con `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=`. **Lax, no Strict**: la etiqueta abre `?k=` como navegación GET de nivel superior y con Strict el admin aparecería deslogueado justo al ir a capturar el GPS.

Helpers en `Handler`: `_sid()` (parsea `Cookie` con `http.cookies.SimpleCookie`, captura `CookieError`), `_usuario()`, y `_origen_ok()` (señal principal `Sec-Fetch-Site ∈ {same-origin, none}`; respaldo `Origin == ORIGEN`; sin ninguna señal → bloquea).

**Refactor de `_json`:** aceptar `cookies=()` y emitir un `Set-Cookie` por cada una **antes** de `end_headers()`. Y **quitar `Access-Control-Allow-Origin: *`**: es incompatible con cookies (el navegador rechaza credenciales contra `ACAO:*`) y en v2 todo es mismo origen. El `do_OPTIONS` con `*` puede quedarse sólo si se deja CORS para pruebas con origen explícito; lo natural es eliminarlo.

### 2.4 Endpoints
```
POST /api/login    {usuario, pin?}  → _origen_ok; valida usuario; si admin, compara
                                       PIN con secrets.compare_digest; crea sesión;
                                       responde con Set-Cookie
POST /api/logout                    → borra sesión, cookie caducada
GET  /api/me                        → {usuario: 'admin'|...|null}  (el cliente decide login)

GET    /api/estaciones             → lista (para pintar medallero, pistas y CRUD)
POST   /api/estaciones             → admin: alta/edición nombre/pista/medalla/capítulo/orden
POST   /api/estacion/colocar {k,lat,lon}  → admin: guarda GPS capturado (recolocar = re-POST)
POST   /api/estacion/borrar  {k}   → admin
   (todas las de escritura: _origen_ok + _usuario()=='admin', si no 403)

GET  /tiles/{z}/{x}/{y}.png        → proxy + caché en disco (público, sin sesión)
```

### 2.5 Progreso y contenido
- `/api/progreso` deduce el jugador de la **cookie** (`self._usuario()`), no de `?u=`. Se elimina `_token()` y `?u=`. El merge (`fusionar_progreso`) y `sanear` quedan igual, cambiando la clave a `usuario`.
- **`/api/contenido` se compone ahora del CONFIG estático + la tabla `estaciones`**: metadatos de capítulos/`esquinas`/traslado/final salen del JSON publicado; las coordenadas de cada estación salen de `estaciones` (lo colocado en campo manda sobre lo aproximado del JSON). Así el cliente siempre recibe la posición real de la etiqueta.
- Subcomando CLI nuevo `python servidor.py estaciones` para listar qué falta por colocar el día del montaje.

### 2.6 Proxy-caché de teselas
`GET /tiles/{z}/{x}/{y}.png`:
- Validar con `^/tiles/(\d+)/(\d+)/(\d+)\.png$`, comprobar `13 ≤ z ≤ 18`, `0 ≤ x,y < 2**z` (evita path traversal y zooms absurdos).
- Ruta de caché derivada **sólo de los enteros validados**: `cache_teselas/{z}/{x}/{y}.png`.
- Cache hit → sirve de disco. Miss → descarga con `urllib.request.Request(headers={"User-Agent": UA})` (el UA por defecto de urllib está en la lista de bloqueo de OSM, fijarlo NO es opcional), `timeout=10`, escritura atómica (`.tmp` + `os.replace`), `threading.Semaphore(2)` hacia upstream.
- Salida: `Content-Type: image/png`, `Cache-Control: public, max-age=604800` (≥7 días que exige la política).
- Caché negativa para 404 (borde/mar) para no repedir en bucle.
- **Requiere pasar a `ThreadingHTTPServer`** — ya lo es (`Servidor(socketserver.ThreadingTCPServer)`), bien; una descarga lenta no congela el juego.
- **Atribución obligatoria** `© colaboradores de OpenStreetMap` visible en el mapa (control de atribución de Leaflet).
- Nada de pre-seeding masivo por código (la política lo bloquea): el bbox de Cadavedo son ~300-400 teselas a z13-18; se "calienta" paseando la vista el día del montaje y a partir de ahí es de facto auto-hospedado.

---

## 3 · Cliente (`index.html` + Leaflet vendorizado)

### 3.1 Vendorizar Leaflet 1.9.4 (sin build)
Bajar a `/vendor/leaflet/`: `leaflet.js` (UMD, expone `window.L`), `leaflet.css` y la carpeta `images/` (5 PNG, 6,5 KB, referenciados por el CSS). Cargar con `<link>` y `<script src>` normales. Total ~46 KB gzip. **No** MapLibre: es 3× más JS, exige WebGL (riesgo en iPad viejo) y su fuerza (vector) no se usa aquí.

### 3.2 Pantalla de login visual (`#login`)
Capa a pantalla completa que tapa el juego hasta que hay identidad. Tres tarjetas grandes emoji+color (Orián no lee: la suya es reconocible por icono/color, sin texto imprescindible). Al tocar Himilce/Orián → `POST /api/login {usuario}` directo. Al tocar admin → teclado numérico de 4 dígitos → `POST /api/login {usuario:'admin', pin}`. Al arrancar, `GET /api/me`: si devuelve usuario, se salta el login (cookie persistente 180 días). Sin cobertura y sin `/api/me`, cae en la última identidad guardada en localStorage (red de seguridad; la escritura real la sigue guardando el guardián del servidor).

### 3.3 Mapa vivo + niebla (el cambio técnico grande)
```js
const map = L.map('mapa', { zoomControl:false, attributionControl:true });
L.tileLayer('/tiles/{z}/{x}/{y}.png', { minZoom:15, maxZoom:18,
    attribution:'© colaboradores de OpenStreetMap' }).addTo(map);
map.createPane('niebla');   // z-index entre tilePane(200) y markerPane(600)
```
**Niebla = patrón C** (capa `L.Layer` custom anclada a un rectángulo geográfico, como `L.ImageOverlay`):
- Canvas en píxeles intrínsecos a un zoom de referencia `ZREF≈18-19`, tamaño = proyección del `bounds` del área de juego. Vigilar RAM: acotar `bounds` al área real con margen (no al pueblo entero). Con `ZREF=18` los agujeros salen un pelín blandos al acercar, pero la niebla ya es borrosa por diseño.
- `getEvents()` engancha `zoom`/`viewreset` → `_reset` (reposiciona/escala el canvas por CSS) y **`zoomanim` → `_animateZoom`** (copia literal del core: `setTransform(canvas, offset, scale)`). Esto **mata el "salto"** de la animación de zoom.
- `revelar(latlng)`: `map.project(latlng, ZREF).subtract(nwPt)` → píxel del mask; radio en metros→px con `mpp`; `destination-out` con gradiente radial. **Se llama una vez por punto nuevo**, cero repintado en pan/zoom. Adiós a `dentroDelMapa`/`aPixel`/`recto`.
- Al montar la capa, reconstruye lo explorado recorriendo `estado.rastro` con `revelar` (respeta `sanear`: rastro null → niebla entera, no revienta).
- `pointer-events:none` en la capa (y en el HUD) o el mapa deja de arrastrarse.

**Rastro** → `L.Polyline` (geográfico, escala con el zoom, Leaflet lo mueve solo). **Marcador jugador + círculo de precisión** → `L.circleMarker` (tamaño de pantalla fijo) + `L.circle` (metros, escala). **Sónar/latido** → único `requestAnimationFrame` propio, canvas pequeño; congelarse 250 ms en el zoom no se nota. `watchPosition` sigue alimentando el suavizado `ALFA=0.4` y luego `map.panTo([latSuave,lngSuave])`.

Ojo al bug [Leaflet #4672]: `latLngToContainerPoint` da mal **durante** la animación de zoom; por eso el HUD se congela en `zoomstart`→`zoomend` y la niebla usa `_animateZoom` en vez de proyectar por frame.

### 3.4 Provisión de etiquetas en campo (admin)
Evolución del modo autor v1 (que ya captura GPS esperando a que la precisión baje de 10 m):
1. Iyán pega la etiqueta física, la escanea → abre `?k=<clave>` **con su sesión admin** (cookie Lax viaja en la navegación GET, sigue logueado).
2. La página ve `k` + `/api/me == 'admin'` → entra en modo colocación en vez de desbloquear: muestra la ficha de esa estación y el afinado de precisión (reutiliza el `watchPosition` y el "quédate quieto hasta <10 m" de v1).
3. Al marcar → `POST /api/estacion/colocar {k, lat, lon}` (fetch same-origin, cookie automática, `Sec-Fetch-Site: same-origin` pasa el guardián). Suelta un `L.marker` en la posición como confirmación visual.
4. Recolocar = volver a escanear y remarcar; borrar desde el panel.

Si el que escanea `?k=` **no** es admin (los críos), comportamiento v1: desbloquea la estación y sigue el juego.

### 3.5 Panel de admin (`#admin`)
Lista de `/api/estaciones` con estado (colocada/pendiente, precisión de la última captura), edición de nombre/pista/medalla/orden/capítulo, botones recolocar/borrar. Sólo visible con sesión admin. Reemplaza la exportación de URLs `?k=` del modo autor v1 por algo con estado en servidor.

### 3.6 Encaje `?k=` con sesión por cookie
La recarga por etiqueta sigue siendo la de siempre (decisión que no se toca: URL, no Web NFC; recarga completa; estado en localStorage). Lo nuevo: al recargar, además de leer `?k=`, el cliente llama a `/api/me` para saber si esta recarga es de admin (→ colocar) o de jugador (→ desbloquear). `arrancarSeguimiento()` sigue siendo idempotente. El `abrirAudio()` enganchado a `pointerdown` tras recarga se mantiene.

### 3.7 Service worker (`sw.js`)
- Añadir a `ARCHIVOS`: `./vendor/leaflet/leaflet.js`, `./leaflet.css`, `./vendor/leaflet/images/*`. Quitar los `mapa-*.jpg` (ya no existen).
- `/tiles/...` → estrategia **cache-first** (son inmutables): así en el pueblo sin datos sigue habiendo mapa una vez visto. El resto sigue red-primero.
- **Subir `VERSION`** (v7 → v8). Es obligatorio o los móviles sirven la copia vieja.

---

## 4 · Riesgos / decisiones abiertas y orden de construcción

### Riesgos y decisiones
1. **RAM del mask de niebla.** Es el único coste real a vigilar. Acotar `bounds` al área de juego + margen y elegir `ZREF` con la fórmula `px_lado ≈ metros/(156543·cos(lat)/2^ZREF)`. Decidir: ¿un solo `bounds` que englobe pueblo y Regalina (están a 1,2 km → mask enorme) o **mantener el concepto de capítulo** con un `bounds` por capítulo y recrear la capa al cambiar? → Recomendado: **un `bounds` por capítulo**, se recrea la capa de niebla en el traslado; conserva el medallero, la pantalla de traslado y evita el mask gigante. El invariante v1 "cero píxeles despejados justo tras cambiar de capítulo" sigue teniendo sentido.
2. **Política OSM y bloqueo sin aviso.** Sin SLA. Mitigación: UA identificable, atribución, caché persistente, `UPSTREAM` configurable (permite cambiar a otro proveedor raster sin tocar cliente). No hacer pre-seeding por código.
3. **`Secure`/`__Host-` detrás de Caddy/Cloudflare.** El servidor ve HTTP en localhost; el flag `Secure` lo ponemos en la cadena y lo hace cumplir el navegador (HTTPS al edge). En local `http://localhost` es contexto seguro, así que la cookie se guarda. Sólo fallaría probando por IP de LAN por HTTP → interruptor por entorno que quite `__Host-`/`Secure` si hiciera falta.
4. **PIN de admin.** 4 dígitos, fuera de git, en `YINCANA_PIN` del systemd, comparado con `compare_digest`. No es barrera de seguridad para los críos (elegir identidad no protege nada); protege sólo la escritura de estaciones.
5. **`ACAO:*` incompatible con cookies.** Hay que quitarlo; requiere que todo sea mismo origen (ya lo es con Caddy) y adaptar las pruebas (ver §5).
6. **Abierto:** ¿el medallero y las pistas se siguen precargando del CONFIG integrado para funcionar sin cobertura la primera vez? Sí — el CONFIG queda como respaldo; `/api/contenido` (CONFIG + coordenadas de `estaciones`) actualiza cuando hay señal, igual que hoy.

### Orden de construcción (fases pequeñas y testeables)
- **F0 — Vendorizar Leaflet.** Bajar ficheros, cargar `L`, mapa mudo centrado en Cadavedo sobre `/tiles` (aún apuntando a OSM directo para arrancar). Test: la página monta el mapa. *Commit.*
- **F1 — Proxy de teselas en servidor.** `/tiles/{z}/{x}/{y}.png` con caché en disco y UA. Cliente apunta al proxy. Tests de servidor (validación z/x/y, cache hit/miss con upstream mockeado, path traversal). *Commit + subir VERSION sw.*
- **F2 — Niebla patrón C sobre el mapa.** Capa custom anclada a `bounds`, `revelar`, `_animateZoom`. Portar HUD/sónar/rastro/marcador a proyección Leaflet. Reutilizar suavizado. Adaptar `pruebas.py` (ver §5). Es la fase más gorda; partirla en: (a) niebla estática que se despeja al caminar; (b) sin salto en zoom; (c) rastro+marcador+sónar. *Commit por subfase.*
- **F3 — Sesiones y login.** Tablas, `crear/usuario_de/borrar_sesion`, `_origen_ok`, refactor `_json` con cookies, endpoints login/logout/me, quitar `ACAO:*`, migrar progreso a usuario. Pantalla `#login`. Tests de servidor (PIN bien/mal, crío sin PIN, `/api/me`, escritura sin cookie→403, sin señal de origen→403). *Commit.*
- **F4 — Estaciones y provisión.** Tabla `estaciones`, CRUD, `/api/estacion/colocar`, composición de `/api/contenido`. Flujo `?k=` admin→colocar. Panel `#admin`. Tests de provisión. *Commit.*
- **F5 — SW cache-first de teselas, ARRANQUE.md, calentar caché, repaso de campo.** Subir VERSION. *Commit.*

Cada fase deja el juego jugable y `pruebas.py`/`pruebas_servidor.py` en verde antes de la siguiente.

---

## 5 · Enfoque de pruebas

### `pruebas_servidor.py`
- **`pedir()`**: añadir por defecto `"Sec-Fetch-Site": "same-origin"` (imita el fetch real de la página) o el guardián devolvería 403 a todos los POST existentes y reventaría `test_flujo_cuenta_progreso`. Añadir parámetro `cookie=None` y devolver también las cabeceras de respuesta para poder leer `Set-Cookie`.
- **Sesiones**: login admin con PIN correcto (200 + `Set-Cookie` con `__Host-sesion`), PIN incorrecto (403), crío sin PIN (200), `/api/me` con y sin cookie, logout invalida.
- **CSRF**: POST de escritura **sin** `Sec-Fetch-Site` y **sin** `Origin` → 403; con `Sec-Fetch-Site: cross-site` → 403.
- **Autorización**: `POST /api/estacion/colocar` sin cookie o con cookie de crío → 403; con cookie admin → 200.
- **Progreso**: reescribir para que dependa de la cookie, no de `?u=`. Los tests de merge en `:memory:` (`fusionar_progreso`) siguen igual, sólo cambia la clave.
- **Teselas**: mock del upstream (monkeypatch de `urllib.request.urlopen` o `bajar`) para no llamar a OSM en tests; comprobar cache hit sirve de disco sin segunda llamada, validación de rango (z fuera → 404), path traversal (`/tiles/1/../../etc` → 404), escritura atómica (no queda `.tmp`).

### `pruebas.py` (Playwright, las 92 comprobaciones con GPS simulado)
- **Mock de teselas obligatorio**: Playwright con `page.route('**/tiles/**', ...)` devolviendo un PNG 256×256 de un color plano generado en memoria (sin red, sin OSM). Igual que hoy corta la red, aquí intercepta teselas. Vendorizar Leaflet también evita cualquier fetch externo.
- **La comprobación estrella cambia de sujeto**: v1 leía el alfa del canvas `#niebla` justo donde está el jugador (proyección con `aPixel`). En v2 lee el alfa del canvas de la capa de niebla en la posición dada por `map.latLngToContainerPoint(jugador)` — hay que esperar a que el mapa esté quieto (`moveend`/idle) para no chocar con el bug #4672, y exponer `window.map`/la capa de niebla para inspección desde el test (como ya se expone el estado hoy).
- **Alineación niebla↔jugador**: mismo espíritu que v1 — tras caminar, el píxel bajo el marcador está despejado y a `radioNiebla+ε` sigue con niebla.
- **Sin salto en zoom**: nuevo test — hacer `map.setZoom(z±1)`, esperar `zoomend`, y verificar que el agujero sigue centrado en el marcador (que la niebla no se desplazó respecto al mapa).
- **`caminar()`** sigue interpolando a paso humano (el filtro `ALFA=0.4` con pasos grandes nunca alcanza al destino — invariante intacto).
- **Login en Playwright**: helper que hace el flujo de `#login` (o inyecta la cookie de sesión vía `context.addCookies`) antes de cada escenario; escenario de admin colocando una estación por `?k=` y comprobando que `POST /api/estacion/colocar` persiste la coordenada capturada.
- **Sin cobertura**: se mantiene el test de red cortada — la página carga del SW, las teselas ya vistas salen de caché, y `?k=` sigue desbloqueando.
- **Demo**: sigue guardando en `yincana.demo`, no en `yincana.v1` (el test que lo vigila se mantiene).

---

### Ficheros que se tocan
`/home/iyan/YINCANA_CADAVEDO/servidor.py` (sesiones, estaciones, proxy teselas, `_json` con cookies, quitar `ACAO:*`, progreso por usuario) · `/home/iyan/YINCANA_CADAVEDO/index.html` (login, Leaflet, niebla patrón C, provisión, panel admin) · `/home/iyan/YINCANA_CADAVEDO/sw.js` (vendor + tiles cache-first, subir VERSION) · `/home/iyan/YINCANA_CADAVEDO/pruebas_servidor.py` y `/home/iyan/YINCANA_CADAVEDO/pruebas.py` (§5) · `/home/iyan/YINCANA_CADAVEDO/yincana.service` (`YINCANA_PIN`, `YINCANA_ORIGEN`) · nuevos `/home/iyan/YINCANA_CADAVEDO/vendor/leaflet/*` · `.gitignore` (`cache_teselas/`) · `ARRANQUE.md`/`LEEME.md` (PIN, calentar caché, empezar BD de cero). `mapa.py` y los `mapa-*.jpg` quedan obsoletos para el juego (conservables como respaldo o para un `--teselas` de pre-generación futura).