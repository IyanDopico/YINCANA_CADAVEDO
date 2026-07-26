# Arranque en Claude Code

Pega esto como primer mensaje. `CLAUDE.md` se carga solo, así que no hace falta
repetir lo que ya está ahí.

---

## Mensaje para pegar

> Yincana con niebla de guerra para mis primos de 6 y 10 años, en Cadavedo
> (Valdés, Asturias), en agosto. El código base ya está y las 39 pruebas pasan:
> ejecuta `python3 pruebas.py` antes de nada para confirmarlo. Abre también
> `?demo` en el navegador para ver de qué va sin necesidad de GPS.
>
> Léete `CLAUDE.md` y `LEEME.md`. Las tareas están abajo en este archivo.
> Empieza por la 1: hay que decidir el tamaño del mapa, y de eso depende todo
> lo demás.
>
> Antes de escribir código, dime cómo lo enfocarías y qué alternativas hay.

---

## Estado

Funciona de punta a punta con GPS simulado: niebla, frío/caliente, sónar,
desbloqueo por etiqueta, medallas, modo autor, demo, persistencia entre
recargas, etiqueta repetida, etiqueta adelantada y clave inventada.

Sin probar en la calle. Sin `mapa.jpg`. Sin desplegar. Y las coordenadas de las
estaciones son de OpenStreetMap, no de campo: sirven para la demo y nada más.

## Tareas, por orden

### 1 · Decidir el tamaño del mapa
La que condiciona el resto. Cadavedo está estirado: del apeadero a La Regalina
hay 1 985 m, y del núcleo a La Regalina 1 196 m.

Con el recuadro entero, cada pisada despeja el 0,13 % del mapa. Los críos
caminan un montón y no ven abrirse casi nada, que es justo la gracia del juego.
Ciñéndolo al casco del pueblo sube al 0,83 %, seis veces más, pero se queda
fuera La Regalina, que es el sitio bonito y el mejor final posible.

Opciones que se me ocurren, pero dime si hay más:

- **Solo el casco.** Todo cerca, la niebla se abre a buen ritmo, y La Regalina
  no sale. Lo más sencillo y lo mejor para el de 6 años.
- **Todo en un mapa.** Sale La Regalina pero la última etapa es 1,2 km de tirón
  y el mapa se abre a cuentagotas.
- **Por capítulos.** Un mapa del casco para las sesiones de los días 1 y 2, y
  otro de La Regalina para el final del día 3. Es lo que más me convence, pero
  hay que ver qué supone: ¿un `CONFIG` por capítulo, o varias esquinas y varios
  mapas dentro del mismo archivo?

Compara antes de tocar código.

### 2 · Ver los puntos sobre el mapa en modo autor
Ahora mismo el modo autor da números y hay que fiarse. Si me equivoco en una
esquina del recuadro, no me entero hasta estar en el pueblo con los críos.

Que enseñe el mapa con los puntos ya marcados encima, y avise si uno cae fuera
del recuadro. Es la tarea que me deja salir a marcar.

### 3 · Dos móviles, dos partidas
Cada dispositivo tiene su `localStorage`, así que van por separado: los dos
tendrían que tocar cada etiqueta. Puede que esté bien (cada uno con su mapa y
su medallero) o puede que sea un lío.

Compara las opciones antes de tocar nada. Sin servidor: no quiero backend.

### 4 · Reparto por edades
El de 6 no lee. Idea: modo `?quien=peque` con la pantalla dominada por el
frío/caliente, sin texto, y `?quien=mayor` con las pistas y el mapa. Que ninguno
avance solo. Dime si merece la pena o si complica más de lo que aporta.

### 5 · Batería
El GPS de alta precisión en continuo se come el móvil en dos o tres horas y son
tres días de juego. Mira si se puede bajar el ritmo cuando están lejos de la
estación y subirlo al acercarse. Mide antes de optimizar.

### 6 · Pantalla final
Al abrir la última estación ahora solo sale un texto. Debería cerrar mejor: el
mapa entero despejado, el recorrido de los tres días, las medallas y dónde está
el tesoro de verdad.

### 7 · Pistas dentro de la etiqueta
Las coordenadas y las pistas están en el código de la página. El de 10 podría
abrir el código fuente. No es crítico. Si se hace, que el texto viaje en el
registro NDEF y la página solo lo pinte.

## Cosas que no puede comprobar el simulador

- **Las coordenadas de las tres estaciones.** Son de OpenStreetMap: apuntan al
  apeadero, al nodo del núcleo y a la ermita, no a donde vaya a esconder yo la
  etiqueta. Hay que recapturarlas todas con `?modo=autor`.
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
| Antes de subir | Tareas 1, 2 y 3, desplegar con HTTPS |
| En el pueblo | Generar el mapa, marcar los puntos, anotar precisiones |
| Después | Rellenar `CONFIG`, grabar las etiquetas, recorrido de prueba yo solo |
| Reserva | Tareas 3 a 6, solo si sobra tiempo |

Si algo va justo, esto se cae por este orden: 7, 6, 5, 4. Las tareas 1, 2 y 3 no.

Y el plan B de siempre: las pistas impresas en un sobre. Si muere un móvil o
desaparece una etiqueta, la yincana sigue.
