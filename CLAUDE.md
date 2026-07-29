# CLAUDE.md

Yincana con niebla de guerra para dos críos (6 y 10 años) en **Cadavedo**
(concejo de Valdés, Asturias), en agosto de 2026. Una web que se abre con el mapa del pueblo
cubierto de niebla, la despeja según caminan, y los guía por GPS hacia
etiquetas NFC escondidas que Iyán coloca el día antes.

Lo lleva Iyán, ingeniero de telecos. Habla en español, directo, sin florituras.
Prefiere ver opciones comparadas antes de meterse en detalle. No hace falta
explicarle qué es Web Mercator ni qué es el RSSI.

> **v2 en curso (versión útil, no demo).** En el pueblo **sí hay cobertura en
> todos los rincones**, así que el juego deja de ser offline-first y pasa a:
> **mapa vivo real** (teselas servidas y cacheadas por la propia máquina) con la
> niebla de guerra por encima; **login persistente con cookie de sesión** para
> tres usuarios (admin=Iyán con PIN, Himilce 10, Orián 6, los críos sin
> contraseña); y **provisión de etiquetas en el campo**: el admin coloca una
> etiqueta, la escanea y se guarda su posición GPS como ubicación de esa
> estación, en el servidor. Las secciones de abajo describen el diseño v1
> (imagen estática + offline) y se irán actualizando según aterriza la v2.

## Órdenes

```bash
python pruebas.py               # 97 comprobaciones con GPS simulado (incluye servidor)
python pruebas.py --capturas    # además deja pantallazos en capturas/
python pruebas.py --ver         # con navegador visible, para depurar
python pruebas_servidor.py      # pruebas del backend, sin navegador ni red
python servidor.py              # juego + API (sesiones, progreso, contenido, teselas)
python servidor.py publicar contenido.json   # sube metadatos (pueblo, radios, spawns)
python servidor.py jugadores                 # usuarios y su avance
python servidor.py estaciones                # estaciones y si están colocadas
YINCANA_PIN=1234 python servidor.py          # con PIN de admin (en prod va en el systemd)
docker compose up -d --build    # producción: servidor + túnel (ver DESPLIEGUE.md)
```

**`python`, no `python3`.** En la máquina de Iyán (Windows) `python3` es el
alias de la Microsoft Store, un 3.14 vacío; `python` es el 3.11 que tiene
Pillow y Playwright. `python3 mapa.py` falla con `No module named 'PIL'` y no
es que falte Pillow, es que es otro intérprete.

Direcciones: `?demo` recorrido simulado (sin login) · `?reset` borrar la partida
· `?k=<clave>` la abre una etiqueta (jugador: desbloquea; admin: coloca). El
panel de estaciones es el botón ⚙ (sólo admin).

`pruebas.py` necesita `pip install playwright && playwright install chromium`.

**Ejecuta `pruebas.py` después de tocar `index.html`.** Es lo único que hay
entre un cambio y descubrir el fallo en el pueblo con dos críos delante.

`http://localhost` cuenta como contexto seguro, así que la geolocalización
funciona en local sin certificado. En producción hace falta HTTPS de verdad.

## Cómo está montado

`index.html` es la aplicación (sin build ni gestor de paquetes). Única
dependencia: **Leaflet vendorizado en `vendor/leaflet/`** (servido desde la
propia máquina, no de un CDN). El `CONFIG` de arriba es la **copia integrada de
respaldo**; el contenido de verdad lo sirve el servidor.

- `index.html` — la aplicación entera (mapa vivo + niebla + login + provisión)
- `vendor/leaflet/` — Leaflet 1.9.4 (js+css+imágenes), sin CDN
- `sw.js` — service worker (red de seguridad; cachea app y teselas)
- `manifest.json` — para añadir a pantalla de inicio
- `servidor.py` — backend (stdlib + SQLite): sesiones, progreso, contenido,
  estaciones y **proxy-caché de teselas** (`/tiles/{z}/{x}/{y}.png`)
- `contenido.json` — metadatos publicables (pueblo, radios, spawns, final)
- `Dockerfile`, `compose.yml`, `tunel/` — despliegue recomendado (servidor +
  túnel en contenedores; estado en `./datos/`; `.env` y `tunel/credenciales.json`
  no se commitean)
- `Caddyfile`, `yincana.service`, `yincana-tunnel.service` — despliegue
  alternativo sin Docker
- `pruebas.py` — simulador de recorrido · `pruebas_servidor.py` — backend
- `LEEME.md`, `DEMO.md`, `DESPLIEGUE.md`, `PLAN-v2.md` — guías
- `mapa.py`, `mapa-*.jpg` — **obsoletos** en v2 (el mapa es vivo); se conservan
  por si algún día se quiere un modo sin conexión con imagen pre-generada.

## Una sola zona, mapa vivo

En v2 hay cobertura, así que el mapa es **vivo** (teselas reales de OSM
proxeadas por la máquina) con la niebla de guerra por encima. **Una sola zona**:
el área de juego (`boundsDeJuego()`) se ajusta sola al rectángulo que engloba
las estaciones colocadas, con margen. Fuera quedan los capítulos, el traslado y
el conmutador de mapas de la v1.

Las coordenadas de las estaciones **se capturan en campo**: el admin escanea
cada etiqueta y se guarda su GPS (tabla `estaciones` del servidor). El `CONFIG`
integrado sólo trae unas de ejemplo para la demo.

Capas del render (todas dentro de `#lienzos`, que crea su propio contexto de
apilado para no tapar las pantallas completas):

| | |
|---|---|
| `#mapa` | mapa Leaflet con `tileLayer('tiles/{z}/{x}/{y}.png')` |
| capa niebla | `NieblaOverlay` (subclase de `L.ImageOverlay`): un canvas anclado al mapa a un zoom de referencia; se pica un agujero por pisada y no se repinta al mover/zoom |
| rastro / precisión / spawns | capas de Leaflet (`L.polyline` / `L.circle` / `L.marker`) |
| `#hud` | sólo lo animado: marcador del jugador y anillos de sónar, por fotograma |

## Decisiones que no se tocan

**El desbloqueo NFC va por URL, no por la API Web NFC.** `NDEFReader` solo
existe en Chrome para Android y dejaría fuera cualquier iPhone o iPad. Cada
etiqueta guarda `https://…/?k=<clave>`; al tocarla el móvil abre la página, que
lee el parámetro y desbloquea. Funciona en iOS y Android sin instalar nada.
Si alguien propone "usar Web NFC que es más limpio", la respuesta es no.

**Tocar una etiqueta recarga la página.** Es consecuencia de lo anterior. Todo
el estado va a `localStorage` bajo `yincana.v1`, y `arrancarSeguimiento()` es
idempotente para retomar sin volver a pedir el botón de inicio. Cualquier
estado nuevo tiene que persistir o se pierde en la primera etiqueta.

**~~Tiene que funcionar sin cobertura.~~ (v1) → En el pueblo sí hay cobertura
(v2).** Esta era la restricción madre de la v1: sin datos, de ahí el mapa como
imagen pre-generada, la retícula de respaldo y el service worker cacheándolo
todo. **Ya no aplica**: hay cobertura en todo el pueblo, así que la v2 depende
de la conexión (mapa vivo con teselas, servidor en tiempo real). Lo que sí se
conserva por barato: nada de **CDN ni fuentes remotas de terceros** en tiempo de
ejecución —las teselas y todo lo demás salen de la propia máquina—, y el service
worker se mantiene como red de seguridad (que un bache momentáneo no tire la
página), no como requisito. `pruebas.py` sigue cortando la red para comprobar
que un corte puntual no rompe nada.

**Login persistente por cookie de sesión.** Tres usuarios fijos: `admin` (con
PIN de `YINCANA_PIN`), `himilce`, `orian` (botón directo, sin contraseña; Orián
no lee). El servidor deja una cookie `__Host-sesion` (HttpOnly, Secure,
SameSite=Lax, 180 días). El cliente cachea el nombre de usuario en
`localStorage` (`yincana.usuario`) para arrancar sin esperar a la red y sin
cobertura; `confirmarSesion()` lo valida en segundo plano. Hay que loguearse una
vez con red (en casa); a partir de ahí sobrevive a las recargas por etiqueta.

**El progreso va por usuario en el servidor, mejor-esfuerzo.** Se sube con
debounce y el `merge` no es destructivo (une `abiertas`/`capturas`, conserva el
rastro más largo). El cliente guarda todo en `localStorage` **siempre**; el
servidor es respaldo y permite retomar en otro móvil con el mismo login. El
contenido se resuelve **síncrono** al arrancar (caché local → `CONFIG`
integrado) y se refresca en segundo plano para la **siguiente** carga; sólo se
aplica si trae ≥1 estación, para no dejar una partida vacía antes de provisionar.
El estado ganó un campo `capturas` (spawns recogidos); pasa por `sanear()`.

**Las escrituras van con guardián CSRF.** `_origen_ok()` exige `Sec-Fetch-Site`
same-origin/none (o `Origin` == `YINCANA_ORIGEN`). Nada de CORS abierto: la
cookie de credenciales es incompatible con `Access-Control-Allow-Origin: *`.

**El público son un niño de 6 y otro de 10.** El de 6 se guía por el frío/
caliente y el sonido, no lee. Nada esencial puede depender de leer texto: por eso
el aviso de estar encima no es sólo el cambio de `#pistaTitulo`, sino la clase
`body.encima`, que enciende el borde del instrumento y hace latir el número.

**Es una carrera individual, con recolección libre.** Orián por un lado e
Himilce por otro buscan **las mismas etiquetas**, cada uno en el orden que se las
va cruzando: `comprobarEtiqueta()` acepta cualquier estación sin abrir, sin
"todavía no toca" ni etiquetas saltadas. La "estación activa" ya no marca orden,
es sólo la **más cercana sin abrir** (`estacionActiva()` la elige por distancia),
para que el sónar y el frío/caliente apunten a la que tienes al lado; la pista
cuenta cuántas quedan, no numera. Cada uno a lo suyo: en su móvil no ve el avance
del rival —el medallero es el suyo—; quien los ve a los dos es el admin, en el
panel de hallazgos. **No hay ganador automático**: lo canta quien vaya con ellos.
Cada crío toca cada etiqueta (no hay sincronización entre sus móviles); con
login, el progreso de cada uno se retoma por usuario si cambia de móvil.

Esto sustituye al modelo v1 (secuencia ordenada + perdón por rastro,
`perdonarSiPasaronCerca`), que ya no existe: en una carrera no hay huecos que
perdonar.

**Cada uno con su bicho y su color (`QUIENES`).** Himilce 🦊 `#8a6fb0`, Orián 🐢
`#4f9e78`, admin 🧭 `#c8952f` —los mismos del login—. Se usan en la cabecera
(`#yo`), en el arranque personalizado ("A por ellas, Orián" con su bicho en
grande), en el aro del marcador del mapa y en el tanteo del admin. En una
carrera individual la partida tiene que sentirse suya, y al de 6 su tortuga le
dice de quién es esto mucho antes que su nombre escrito. **El relleno del
marcador sigue siendo el frío/caliente**: eso es la guía, no se toca; su color
va sólo en el aro de fuera.

**La celebración es la mitad del juego para el de 6.** Al encontrar una:
confeti (`soltarConfeti()`, `<i>` con animación CSS, se limpian solos a los
3,2 s), halo dorado en la medalla, brinco del bicho de la cabecera
(`brincarAvatar()`), fanfarria (`fanfarria()`, escala más larga en la última) y
**`#logroCuenta`: un punto de oro por encontrada y uno hueco por cada una que
falta**. Ese es el marcador que entiende sin leer. Todo se salta con
`prefers-reduced-motion`.

**El cronómetro mide de la primera etiqueta a la última.** `estado.comenzado`
se arma en el primer `desbloquear()` (no en el botón de empezar: ése se pulsa
en casa la víspera, al hacer el login) y `estado.terminado` se congela al abrir
la última, para que re-enseñar el cierre horas después no infle el tiempo.
Ambos pasan por `sanear()`; `tiempoDeCarrera()` se calla ante disparates (reloj
movido). El tiempo **canónico** para comparar a los dos críos sale del panel
del admin, calculado con las fechas de `/api/hallazgos` (primera→última):
inmune a recargas y a cambios de móvil.

**El marcador de carrera vive sólo en el panel del admin**
(`marcadorDeCarrera()`): barras, tanteo, hora de la última y minutos de carrera
de cada uno, con los datos de `/api/hallazgos` **filtrados por claves vigentes**
(borrar o regrabar una etiqueta deja hallazgos huérfanos en el servidor; sin el
filtro el tanteo canta 3/2). En el móvil de cada crío **no puede aparecer el
rival** —hay una comprobación en `pruebas.py`, contra el servidor de verdad,
que lo vigila— y sigue sin haber ganador automático: lo canta quien vaya con
ellos.

**Las pistas describen dónde está SU etiqueta, no la siguiente.** Con la
carrera se invirtió la semántica: la pista que se ve es la de la estación a la
que ya apunta el instrumento (la más cercana sin abrir), así que "id hacia los
hórreos" estilo v1 ya no vale. Al escribir las pistas de agosto, cada una debe
decir dónde se esconde su propia etiqueta ("pegada al banco del andén"). Las
del `CONFIG` integrado son de ejemplo y siguen el estilo viejo: no copiarlas.

**La estación activa cambia sola al caminar, y la UI la sigue.**
`alRecibirPosicion()` vigila el cambio de `est.k`: rearma la alarma
(`yaAvisado`/`dentroSeguidas`) y repinta pista y medallero. Sin eso, la
fanfarria de llegada sonaba una sola vez entre escaneos y el texto describía
una estación mientras el sónar apuntaba a otra. Al salir del radio sin cambiar
de objetivo se restaura la pista (el "Estás encima" no se queda clavado), pero
`yaAvisado` se conserva: entrar y salir del radio de la misma estación no
repite la fanfarria.

**El admin coloca las etiquetas escaneándolas.** Escanear `?k=` con sesión de
admin no desbloquea: abre "Colocar etiqueta" y guarda el GPS actual como
ubicación de esa estación (`/api/estacion/colocar`, alta si es nueva). El panel
(botón ⚙) las nombra, ordena y da la URL a grabar. Los jugadores (no admin) al
escanear `?k=` desbloquean, como siempre.

## Trampas que ya nos mordieron

**La niebla se ancla al mapa, no a la pantalla.** `NieblaOverlay` extiende
`L.ImageOverlay` para heredar el posicionado y la animación de zoom: el canvas
tiene resolución fija a `ZREF` y Leaflet lo escala. Se pica un agujero por
pisada (`revelar`), nunca se repinta al mover/zoom. `montarMapa()` fija la vista
**antes** de añadir la capa (Leaflet difiere `addLayer` hasta que el mapa está
listo, y `reconstruir` necesita el canvas ya creado). La comprobación de
alineación de `pruebas.py` lee el alfa de ese canvas en el píxel del jugador.

**`#lienzos` crea su propio contexto de apilado (`z-index:0`).** Si no, los
paneles de Leaflet (z-index hasta 700) se cuelan por encima de las capas a
pantalla completa (login, medalla, cierre) y las tapan.

**`tintar()` espera `rgb()`, no hexadecimal.** Con un hex, su expresión regular
extrae dígitos sueltos y devuelve un color casi negro. `mezcla()` siempre
devuelve `rgb()`; mantenlo así.

**El suavizado exponencial va con retraso.** `ALFA = 0.4` sobre la posición.
Al probar con pasos grandes el filtro nunca alcanza al destino y parece que el
aviso de zona no funciona. `caminar()` en `pruebas.py` interpola a paso humano
justamente por esto.

**Dos lecturas seguidas dentro del radio antes de avisar.** Un pico del GPS no
puede disparar la alarma. `dentroSeguidas` lleva la cuenta.

**El rastro se diezma a 10 m.** Guardar cada lectura llenaría `localStorage` y
haría lento el repintado de la niebla.

**Lo que sale de `localStorage` pasa por `sanear()`.** Con `rastro` a null la
página se queda en blanco al primer repintado, y en mitad del monte eso es el
final de la yincana. También descarta las `abiertas`/`capturas` cuyas claves ya
no están en el contenido: pasa en cuanto recolocas estaciones y salen claves
nuevas, y sin eso el móvil se cree la yincana terminada.

**El contenido servido sólo se aplica si trae estaciones.** Antes de provisionar,
`/api/contenido` devuelve 0 estaciones; aplicarlo dejaría la partida sin nada que
buscar. `contenidoConEstaciones()` es la puerta: si no hay, se sigue con el
`CONFIG` integrado.

**Sube `VERSION` en `sw.js` al editar `index.html`, `sw.js` o el vendor.** Si no,
los móviles siguen sirviendo la copia vieja y te vuelves loco.

**Detrás de Cloudflare, el `sw.js` no se puede cachear en el edge.** Es la misma
trampa un nivel más arriba: aunque subas `VERSION`, si Cloudflare tiene cacheado
el `.js` sirve el service worker viejo. Por eso `servidor.py` manda
`Cache-Control: no-cache` en `sw.js`/`.html` y `no-store` en `/api`. Ver
`DESPLIEGUE.md` para los ajustes del panel (Rocket Loader off, etc.).

**En iOS no existe `navigator.vibrate`.** Nunca ha existido. El aviso tiene que
funcionar solo con sonido y con lo que se ve.

**La demo guarda en `yincana.demo`, no en `yincana.v1`.** Para que enseñarla no
borre la partida de verdad. Hay una comprobación que lo vigila.

**Los mandos de la demo van en `z-index: 70`,** por encima de las capas a
pantalla completa (50). Si no, la medalla los tapa y no se puede ni pausar.

**El audio necesita un gesto previo.** `abrirAudio()` se llama desde los
botones. Tras una recarga por etiqueta se engancha a `pointerdown` una vez.

## Estilo

Español en interfaz, comentarios y mensajes de commit. Comentarios solo donde
el porqué no se deduce del código; nada de comentarios que repitan la línea de
abajo.

Paleta: `--frio #3d7d8f` a `--caliente #f2b134`, oro `#c8952f` para medallas,
niebla `#1b2733`/`#0d151d`, hueso `#e8e0cf`. Serif para lo cartográfico,
monoespaciada para las lecturas del instrumento. La idea es carta de
levantamiento con un instrumento de campo encima, no mapa pirata.

No metas frameworks, ni build, ni gestor de paquetes. Un archivo que se sube
por FTP y funciona.
