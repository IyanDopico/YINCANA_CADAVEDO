# Yincana con niebla de guerra

Página web que se abre con el mapa del pueblo cubierto de niebla. La niebla se
despeja según caminan. Al acercarse a una estación empieza a pitar cada vez más
rápido, y al tocar la etiqueta NFC escondida se desbloquea la medalla y la
siguiente pista.

No hace falta instalar nada en los móviles de tus primos.

## Archivos

| | |
|---|---|
| `index.html` | La aplicación entera. Toda la configuración está arriba del todo, en el bloque `CONFIG`. |
| `mapa.py` | Prepara `mapa.jpg` y calcula sus esquinas exactas. Se ejecuta una vez, en tu ordenador. |
| `sw.js` | Service worker: hace que funcione sin cobertura. |
| `manifest.json` | Para poder añadirla a la pantalla de inicio. |
| `pruebas.py` | Recorre la ruta con un GPS falso y comprueba que todo responde. Ejecútalo tras cada cambio. |
| `CLAUDE.md` · `ARRANQUE.md` | Contexto y tareas pendientes para seguir en Claude Code. |

## Verla funcionar ahora mismo

```
https://tu-dominio/yincana/?demo
```

Recorrido simulado por Cadavedo: no usa el GPS ni pide permisos, así que
funciona igual en un portátil. Camina sola por las tres estaciones y va tocando
las etiquetas al llegar. Los mandos de abajo pausan, aceleran y repiten.

Guarda en su propio sitio, así que enseñarla no toca la partida de verdad.

## Comprobar que todo sigue en pie

```bash
pip install playwright && playwright install chromium
python3 pruebas.py
```

Simula el recorrido completo y valida 39 comportamientos. Con `--capturas`
deja además los pantallazos en `capturas/`.

## Puesta en marcha

### 1 · El mapa

En openstreetmap.org, encuadra el pueblo y abre la pestaña **Exportar**: ahí
tienes los cuatro límites del recuadro que estás viendo. Con esos números:

```bash
pip install pillow
python3 mapa.py <sur> <oeste> <norte> <este>
```

Te deja `mapa.jpg` y te imprime el bloque `esquinas` ya calculado. Pégalo en
`index.html` **tal cual**: son las esquinas reales de la imagen recortada, no
los números que pediste, y esa diferencia importa.

Si no pones imagen no pasa nada: la app funciona igual y al despejar se ve una
retícula.

### 2 · Colocar las etiquetas

Sube todo a tu servidor y abre en el móvil:

```
https://tu-dominio/yincana/?modo=autor
```

Vete al pueblo. En cada sitio donde escondas una etiqueta: **quédate quieto**
hasta que la precisión baje de 10 m (el número se pone verde), escribe el nombre
y pulsa *Marcar punto*. Con prisa salen coordenadas malas y luego el juego no
cuadra; esperar treinta segundos en cada punto es la diferencia entre que
funcione y que no.

Al terminar, *Copiar al portapapeles*. Te da dos cosas: las estaciones listas
para pegar en `CONFIG.estaciones`, y la URL que hay que grabar en cada etiqueta.

### 3 · Grabar las etiquetas

Con la app **NFC Tools** (gratis, Android e iOS), en cada NTAG215 escribe un
registro de tipo **URL** con la dirección que te dio el modo autor:

```
https://tu-dominio/yincana/?k=a7f3c1
```

Y bloquéalas en solo lectura al final, para que no se borren de un roce.

Cuando el móvil toque la etiqueta sale un aviso; al pulsarlo se abre esta misma
página, que reconoce el `?k=` y desbloquea la estación. No usa la API Web NFC a
propósito: esa solo existe en Chrome para Android, y de esta forma funciona
igual en iPhone.

### 4 · Rellenar las pistas

En `CONFIG.estaciones`, el campo `pista` de cada una dice dónde está **la
siguiente**, no ella misma. El orden del array es el orden del juego.

## Ajustes

En `CONFIG`:

- `radioNiebla` (35 m) — cuánto mapa despeja al caminar. Súbelo si el pueblo es
  grande y va muy lento.
- `radioZona` (25 m) — a partir de aquí avisa de que están encima. No bajes de
  20: entre fachadas de piedra el GPS no da para más.
- `radioAudio` (150 m) — desde dónde empieza a pitar.

Otras direcciones útiles:

- `?demo` — recorrido simulado, sin GPS.
- `?modo=autor` — capturar coordenadas.
- `?reset` — borrar la partida y empezar de cero.

## Antes del día

- **Pruébalo caminando la ruta de verdad**, con el móvil que vayan a llevar.
  Es el único paso que no te puedes saltar.
- **HTTPS obligatorio.** Sin certificado válido el navegador no da ni la
  ubicación ni el service worker.
- **Abre la página en cada móvil una vez con cobertura**, en casa, para que el
  service worker se guarde la copia. Después ya funciona sin datos.
- **Añádela a la pantalla de inicio** en cada dispositivo: se abre a pantalla
  completa y molesta menos.
- **Power bank.** El GPS de alta precisión en continuo se come una batería en
  dos o tres horas.
- **Lleva las pistas en papel en un sobre.** Si un móvil muere o una etiqueta
  desaparece, la yincana sigue.

## Lo que esta versión no hace

Las coordenadas y las pistas están en el código de la página, así que un crío
que sepa mirar el código fuente puede verlas todas. Para 6 y 10 años sobra;
si el de 10 es de los que hurgan, ya lo pensaremos.

---

Mapa © colaboradores de OpenStreetMap, bajo ODbL.
