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
| `mapa.py` | Prepara la imagen de un mapa y calcula sus esquinas exactas. Se ejecuta una vez por capítulo, en tu ordenador. |
| `sw.js` | Service worker: hace que funcione sin cobertura. |
| `manifest.json` | Para poder añadirla a la pantalla de inicio. |
| `pruebas.py` | Recorre la ruta con un GPS falso y comprueba que todo responde. Ejecútalo tras cada cambio. |
| `CLAUDE.md` · `ARRANQUE.md` | Contexto y tareas pendientes para seguir en Claude Code. |

## Verla funcionar ahora mismo

```
https://tu-dominio/yincana/?demo
```

Recorrido simulado por Cadavedo: no usa el GPS ni pide permisos, así que
funciona igual en un portátil. Camina sola por las tres estaciones, va tocando
las etiquetas al llegar, cambia de mapa en el traslado a La Regalina y remata en
la pantalla de cierre. Los mandos de abajo pausan, aceleran y repiten: a x4 se
hace larga, ponla a x30 para enseñarla.

Guarda en su propio sitio, así que enseñarla no toca la partida de verdad.

## Comprobar que todo sigue en pie

```bash
pip install playwright && playwright install chromium
python3 pruebas.py
```

Simula el recorrido completo y valida 88 comportamientos. Con `--capturas`
deja además los pantallazos en `capturas/`.

## Puesta en marcha

### 1 · Los mapas

La yincana va por capítulos: un mapa por zona. Cadavedo está estirado —del
apeadero a La Regalina hay casi dos kilómetros— y en un solo mapa cada pisada
despejaría el 0,13 %: caminarían un montón sin ver abrirse nada. Partido en
dos, el casco va al 0,70 % por pisada y La Regalina al 2,38 %.

Los dos de una vez, sacando los recuadros del propio `index.html`:

```bash
pip install pillow
python3 mapa.py --capitulos
```

Al terminar imprime un bloque `esquinas` por capítulo. Pégalos en su capítulo
**tal cual**: son las esquinas reales de la imagen recortada, no las que había
puestas, y esa diferencia importa. Los recuadros que hay ahora en `CONFIG` son
los pedidos, no los recortados, así que hay que sustituirlos.

También dice cuánto abre cada pisada en cada mapa. Por debajo del 0,5 % se hace
lento; si sale así, aprieta el recuadro.

Si quieres cambiar un recuadro, edítalo en `CONFIG` y vuelve a lanzarlo sólo
para ese capítulo:

```bash
python3 mapa.py --capitulos regalina
```

Y para un mapa que no esté en el `CONFIG`, a mano con `sur oeste norte este`,
sacados de openstreetmap.org con la pestaña **Exportar**:

```bash
python3 mapa.py 43.5422 -6.3926 43.5505 -6.3852 --salida prueba.jpg
```

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

Arriba tienes el mapa con lo que llevas marcado: cada punto en oro, con el
círculo de `radioZona` alrededor —eso es lo que van a tener que barrer buscando
la etiqueta— y las estaciones que ya están en el `CONFIG` en azul hueco, para
comparar. Si un punto cae fuera de todos los recuadros sale un aviso en rojo:
ese punto no se vería en el juego. Los botones de arriba cambian de mapa, y al
coger señal salta solo al del sitio donde estés.

Debajo tienes la lista de lo marcado, cada punto con el capítulo en el que cae y
un aspa para borrarlo. Si uno sale torcido, se quita ese y ya: no hay que
repetir los demás.

Al terminar, *Copiar al portapapeles*. Te da dos cosas: las estaciones ya
agrupadas por capítulo, listas para pegar en el `estaciones` que toque, y la URL
que hay que grabar en cada etiqueta.

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

En el `estaciones` de cada capítulo, el campo `pista` de cada una dice dónde
está **la siguiente**, no ella misma. El orden de los capítulos y el de los
arrays dentro es el orden del juego.

Al pasar de un capítulo al siguiente sale la pantalla de traslado, que es donde
se les dice que hay que desplazarse. El texto está en `traslado` del capítulo al
que se va.

## Ajustes

En `CONFIG`:

- `radioNiebla` (35 m) — cuánto mapa despeja al caminar. Súbelo si el pueblo es
  grande y va muy lento.
- `radioZona` (25 m) — a partir de aquí avisa de que están encima. No bajes de
  20: entre fachadas de piedra el GPS no da para más.
- `radioAudio` (150 m) — desde dónde empieza a pitar.
- `perdonarSiPasaronCerca` (true) — si a un móvil se le pasa una etiqueta, al
  tocar la siguiente se pone al día, siempre que su rastro demuestre que estuvo
  allí. Ponlo a `false` para exigir que se toquen todas en orden.

Y en cada capítulo: `mapa`, `esquinas`, `inicioDemo` (por dónde arranca el
muñeco de la demo), `estaciones` y, salvo en el primero, `traslado`.

Otras direcciones útiles:

- `?demo` — recorrido simulado, sin GPS.
- `?modo=autor` — capturar coordenadas.
- `?reset` — borrar la partida y empezar de cero. Pregunta antes: es una
  dirección corta, se queda en el historial, y lo que borra es el mapa que
  llevan despejado.

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
