# Arranque en Claude Code

Pega esto como primer mensaje. `CLAUDE.md` se carga solo, así que no hace falta
repetir lo que ya está ahí.

---

## Mensaje para pegar

> Yincana con niebla de guerra para mis primos de 6 y 10 años, en Cadavedo
> (Valdés, Asturias), en agosto. El código base ya está y las 69 pruebas pasan:
> ejecuta `python3 pruebas.py` antes de nada para confirmarlo. Abre también
> `?demo` en el navegador para ver de qué va sin necesidad de GPS.
>
> Léete `CLAUDE.md` y `LEEME.md`. Las tareas están abajo en este archivo.
> Empieza por la 3: dos móviles, dos partidas.
>
> Antes de escribir código, dime cómo lo enfocarías y qué alternativas hay.

---

## Estado

Funciona de punta a punta con GPS simulado: niebla, frío/caliente, sónar,
desbloqueo por etiqueta, medallas, capítulos, modo autor, demo, persistencia
entre recargas, etiqueta repetida, etiqueta adelantada, clave inventada y
pantalla de cierre. Las 69 comprobaciones de `pruebas.py` pasan.

Sin probar en la calle. Sin las imágenes de los mapas. Sin desplegar. Y las
coordenadas de las estaciones son de OpenStreetMap, no de campo: sirven para la
demo y nada más.

## Hecho

### 1 · Tamaño del mapa — por capítulos
Partido en dos: `pueblo` (923 × 597 m, 0,70 % por pisada) y `regalina`
(400 × 404 m, 2,38 %). Contra el 0,13 % del recuadro único. La Regalina sigue
dentro y además es el mapa que más rápido se abre, que para un final está bien.

Montado como lista `CONFIG.capitulos` dentro del mismo archivo, no un `CONFIG`
por capítulo: así las etiquetas apuntan todas a la misma URL y el capítulo
activo se deduce de lo que llevan abierto, sin guardar nada nuevo.

Entre capítulos sale una pantalla de traslado, que es donde se les avisa de que
hay que desplazarse. El texto está en `traslado` del capítulo al que se va.

### 2 · Los puntos sobre el mapa en modo autor
El panel ya no tapa el mapa: se ha bajado al sitio del instrumento. Encima se
ven los puntos marcados en oro con su círculo de `radioZona`, y las estaciones
del `CONFIG` en azul hueco para comparar. Si un punto cae fuera de todos los
recuadros sale un aviso en rojo y en la salida va apartado en un bloque propio.
Los botones de arriba cambian de mapa, y al coger señal salta solo al del sitio
donde estés.

### 6 · Pantalla final
Al abrir la última estación sale el cierre: las tres medallas en fila, el título
y el texto del tesoro, y cuántas estaciones y metros llevan andados. Al pulsar
*Ver el mapa entero* se quita la niebla del todo —los dos mapas quedan
despejados para siempre— y aparece una barra abajo para pasar de uno a otro y
repasar el recorrido de los tres días.

El texto de dónde está el tesoro se ha quitado de la medalla de la última
estación para que la revelación sea sólo del cierre.

### 3 · Dos móviles, dos partidas
Se quedan las dos partidas separadas: cada uno ve abrirse **su** mapa y llena su
medallero, que para el de 6 es medio juego. Los dos tienen que tocar cada
etiqueta, que son seis toques en tres días.

Lo que sí se ha arreglado es el único fallo que no se detecta a tiempo: que a un
móvil se le pase una etiqueta y a partir de ahí vaya desfasado sin que nadie lo
note. Al tocar una etiqueta posterior se le dan por buenas las que se saltó,
pero **sólo si su propio rastro demuestra que pasó por encima de ellas**
(`perdonarSiPasaronCerca`). Eso distingue el despiste de la etiqueta encontrada
antes de tiempo, que sigue rechazándose.

Descartado sincronizar de verdad: sin backend haría falta QR, y leerlo pide
`BarcodeDetector`, que Safari no tiene.

## Tareas, por orden

### 4 · Reparto por edades
El de 6 no lee. Idea: modo `?quien=peque` con la pantalla dominada por el
frío/caliente, sin texto, y `?quien=mayor` con las pistas y el mapa. Que ninguno
avance solo. Dime si merece la pena o si complica más de lo que aporta.

### 5 · Batería
**Hecho la mitad.** El HUD ya no se repinta en cada fotograma: lejos de la
estación no hay anillos girando y el dibujo es idéntico, así que sólo se repinta
al llegar posición nueva. Medido: 5 repintados en 2 s en vez de los ~120 de un
bucle a 60 fps. Hay una comprobación que lo vigila. Lo mismo en modo autor, que
es donde te vas a pasar media hora quieto esperando precisión.

**Falta la parte del GPS, y ahí hay que medir de verdad.** La API no tiene mando
de frecuencia: el único interruptor es `enableHighAccuracy`, y cambiarlo obliga
a `clearWatch` y volver a arrancar. El problema es que en modo impreciso las
lecturas se van a ±100–500 m y la niebla se abriría en el sitio equivocado —y la
niebla no se puede deshacer, que es justo lo que se llevan de recuerdo. Cambiar
el mapa por batería es mal trato.

Cómo medirlo, con el móvil que vayan a llevar y el brillo al que se vaya a jugar:

1. Media hora andando con la app tal cual. Apunta el porcentaje.
2. Otra media hora con `enableHighAccuracy:false` en las dos llamadas a
   `watchPosition`. Apunta.

Si la diferencia baja de un 10 % por hora, no compensa el riesgo: lo que se está
comiendo la batería es la pantalla encendida, y ahí no hay nada que tocar sin
cargarse el juego. Si es mucho mayor, entonces sí merece montar el cambio
automático, y con él un umbral de precisión por debajo del cual no se guarda
pisada, para que el mapa no se ensucie.

### 7 · Pistas dentro de la etiqueta
Las coordenadas y las pistas están en el código de la página. El de 10 podría
abrir el código fuente. No es crítico. Si se hace, que el texto viaje en el
registro NDEF y la página solo lo pinte.

## Cosas que no puede comprobar el simulador

- **Las coordenadas de las tres estaciones.** Son de OpenStreetMap: apuntan al
  apeadero, al nodo del núcleo y a la ermita, no a donde vaya a esconder yo la
  etiqueta. Hay que recapturarlas todas con `?modo=autor`.
- **Los recuadros de los dos capítulos.** Los que hay en `CONFIG` son los que
  pedí, no los que devuelve `mapa.py` tras recortar. Al generar las imágenes hay
  que pegar las esquinas que imprima, o la niebla se abrirá desplazada.
- Precisión real del GPS entre fachadas de piedra. Hay que recorrer la ruta con
  `?modo=autor` y anotar la precisión en cada sitio candidato. Donde no baje de
  25 m, esa estación va a otro lado.
- Que el aviso NFC salte de verdad al acercar el móvil a la etiqueta.
- Consumo de batería real.
- Que se lea el número de metros a pleno sol de agosto.

## Calendario

| | |
|---|---|
| Ya | Pedir las NTAG215 y probar el NFC con una etiqueta suelta |
| Antes de subir | Desplegar con HTTPS |
| En el pueblo | Generar los dos mapas, marcar los puntos, anotar precisiones |
| Después | Rellenar `CONFIG`, grabar las etiquetas, recorrido de prueba yo solo |
| Reserva | Tareas 4, 5 y 7, solo si sobra tiempo |

Si algo va justo, esto se cae por este orden: 7, 5, 4.

Y el plan B de siempre: las pistas impresas en un sobre. Si muere un móvil o
desaparece una etiqueta, la yincana sigue.
