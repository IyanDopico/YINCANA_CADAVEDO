# CLAUDE.md

Yincana con niebla de guerra para dos críos (6 y 10 años) en **Cadavedo**
(concejo de Valdés, Asturias), en agosto de 2026. Una web que se abre con el mapa del pueblo
cubierto de niebla, la despeja según caminan, y los guía por GPS hacia
etiquetas NFC escondidas que Iyán coloca el día antes.

Lo lleva Iyán, ingeniero de telecos. Habla en español, directo, sin florituras.
Prefiere ver opciones comparadas antes de meterse en detalle. No hace falta
explicarle qué es Web Mercator ni qué es el RSSI.

## Órdenes

```bash
python3 pruebas.py               # 82 comprobaciones con GPS simulado
python3 pruebas.py --capturas    # además deja pantallazos en capturas/
python3 pruebas.py --ver         # con navegador visible, para depurar
python3 mapa.py --capitulos      # genera los mapas del CONFIG y sus esquinas
python3 mapa.py <sur> <oeste> <norte> <este> --salida <archivo>   # uno suelto
python3 -m http.server 8000      # servidor local
```

Direcciones: `?demo` recorrido simulado · `?modo=autor` capturar coordenadas ·
`?reset` borrar la partida.

`pruebas.py` necesita `pip install playwright && playwright install chromium`.

**Ejecuta `pruebas.py` después de tocar `index.html`.** Es lo único que hay
entre un cambio y descubrir el fallo en el pueblo con dos críos delante.

`http://localhost` cuenta como contexto seguro, así que la geolocalización
funciona en local sin certificado. En producción hace falta HTTPS de verdad.

## Cómo está montado

Un solo `index.html` sin dependencias ni CDN. Tipografías del sistema. Todo lo
configurable está en el bloque `CONFIG` de arriba del todo.

- `index.html` — la aplicación entera
- `sw.js` — service worker, para que funcione sin cobertura
- `manifest.json` — para añadir a pantalla de inicio
- `mapa.py` — descarga teselas de OSM, las cose, y calcula las esquinas
- `pruebas.py` — simulador de recorrido
- `LEEME.md` — guía de montaje para Iyán
- `mapa-pueblo.jpg`, `mapa-regalina.jpg` — no están en el repo todavía; uno por
  capítulo, los genera `mapa.py`

## Geografía de Cadavedo

Distancias reales entre los tres puntos con coordenadas públicas verificadas:

| | |
|---|---|
| Apeadero → núcleo | 875 m |
| Núcleo → La Regalina | 1 196 m |
| Apeadero → La Regalina | 1 985 m |

**Resuelto partiéndolo en capítulos**, un mapa por zona. En un solo recuadro
(1934 × 1557 m) cada pisada despejaba el 0,13 %: caminaban mucho y no veían
abrirse casi nada. Ahora son dos:

| | | |
|---|---|---|
| `pueblo` | 923 × 597 m | 0,70 % por pisada |
| `regalina` | 400 × 404 m | 2,38 % por pisada |

El capítulo activo **se deduce de `estado.abiertas`**, no se guarda: la primera
estación sin abrir manda. Eso lo hace idempotente frente a las recargas por
etiqueta, que es la razón de montarlo así y no con un `CONFIG` por capítulo.
Las etiquetas apuntan todas a la misma URL.

Las coordenadas de las estaciones salen de OpenStreetMap y de fuentes
públicas. Valen para la demo. **No valen para jugar**: apuntan al sitio
aproximado, no a donde vaya a estar la etiqueta. Se sustituyen por capturas de
campo con `?modo=autor`.

Tres lienzos apilados sobre la imagen del mapa:

| | |
|---|---|
| `#mapa` | la imagen, con `object-fit: contain` |
| `#niebla` | capa opaca a la que se le abren agujeros con `destination-out` |
| `#hud` | marcador, anillos de sónar y rastro; se repinta en cada fotograma |

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

**Tiene que funcionar sin cobertura.** En el pueblo puede no haber datos. El
GPS no los necesita (GNSS solo recibe) pero la web sí, de ahí el service
worker. Nada de CDN, fuentes remotas ni llamadas a API en tiempo de ejecución.
`pruebas.py` corta la red de verdad y comprueba que la página carga y que la
etiqueta sigue desbloqueando: si tocas `sw.js`, esa es la que avisa.

**El público son un niño de 6 y otro de 10.** El de 6 se guía por el frío/
caliente y el sonido, no lee. Nada esencial puede depender de leer texto: por eso
el aviso de estar encima no es sólo el cambio de `#pistaTitulo`, sino la clase
`body.encima`, que enciende el borde del instrumento y hace latir el número.

**Cada móvil lleva su partida, y se pone al día solo.** No hay sincronización
—sin backend haría falta QR, y `BarcodeDetector` no existe en Safari— así que
los dos tienen que tocar cada etiqueta. Lo que sí se arregla es el despiste: al
tocar una etiqueta posterior se dan por buenas las saltadas, pero sólo si el
rastro de ese móvil pasó a menos de `radioZona * 2` de ellas. El rastro es lo
único que distingue "se me olvidó tocar" de "he encontrado una etiqueta de más
adelante", y esa distinción es la razón de que no valga contar huecos.

## Trampas que ya nos mordieron

**Proyección y `object-fit: contain`.** La imagen se centra con barras dentro
del contenedor, pero los lienzos ocupan el contenedor entero. `aPixel()`
proyecta sobre `recto` (el rectángulo real de la imagen), no sobre `W`/`H`. Si
tocas la proyección, la comprobación de alineación de `pruebas.py` es la que lo
pilla: lee el alfa del lienzo de niebla justo donde está el jugador.

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

**El rastro es uno solo para toda la yincana, y los mapas son varios.** Se
guarda entero, pero al pintar hay que filtrarlo con `dentroDelMapa()`: sin eso,
las pisadas del pueblo abren agujeros en el mapa de La Regalina, que está a
1,2 km. Hay una comprobación que cuenta píxeles despejados justo después de
cambiar de capítulo y exige cero.

**El mapa no cambia detrás de la medalla.** Al abrir la última estación de un
capítulo, primero sale la pantalla de traslado y sólo al pulsar se cambia. Si no,
cierran la medalla y aparece un mapa desconocido sin explicación.

**Sube `VERSION` en `sw.js` al editar `index.html`.** Si no, los móviles siguen
sirviendo la copia vieja y te vuelves loco.

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
