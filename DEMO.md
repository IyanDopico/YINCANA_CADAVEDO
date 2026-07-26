# Probar la yincana con el servidor

Guía para probar el juego **con el backend delante** (cuentas, contenido
dinámico, spawns) y con un tag NFC. Pensada para hacerlo en casa antes de ir al
pueblo.

## 0 · Por qué hace falta HTTPS

La geolocalización del navegador y el service worker **sólo funcionan en
contexto seguro**: `https://…` o `http://localhost`. En el móvil, `localhost` no
vale (es otro aparato), así que para probar con el teléfono necesitas una URL
`https://`. Lo más rápido sin tocar el router es un **túnel de Cloudflare**.

## 1 · Levantar el servidor

```bash
cd ~/YINCANA_CADAVEDO
python servidor.py --puerto 8000        # juego + API en un origen
python servidor.py publicar contenido.json   # sube el contenido (pistas, spawns)
python servidor.py cuenta "Martina"     # crea un jugador, imprime su URL ?u=
python servidor.py cuenta "Nico"
python servidor.py jugadores            # ver quién va por dónde
```

En el mismo ordenador ya puedes abrir `http://localhost:8000/?demo`.

## 2 · Exponerlo con HTTPS para el móvil (túnel rápido, sin login)

```bash
cloudflared tunnel --url http://localhost:8000
```

Imprime una URL del tipo `https://<algo>.trycloudflare.com`. **Es temporal**:
cambia cada vez que reinicias el túnel y muere al cerrarlo. Perfecta para
probar; para el tag definitivo se usa el dominio de verdad (ver `LEEME.md` y la
sección de despliegue permanente).

> Si `cloudflared` no está: se baja el binario de
> https://github.com/cloudflare/cloudflared/releases/latest y `chmod +x`.

## 3 · Qué probar

Llama `BASE` a tu URL `https://…` (la del túnel, o `http://localhost:8000` en el
propio ordenador).

### a) La demo, sin GPS
`BASE/?demo` — recorre las tres estaciones solo, cambia de mapa y remata en el
cierre. No pide permisos. Los mandos de abajo pausan/aceleran (ponla a x30).

### b) El desbloqueo por NFC (¡esto sí necesita el tag!)
El toque del tag **no depende de estar en el sitio**: abre la URL y desbloquea.
Así que puedes probar el flujo entero en el sofá.

1. Con la app **NFC Tools** (gratis, Android/iOS) escribe en el tag un registro
   **URL** con:  `BASE/?k=a7f3c1`  (la clave de la primera estación, «El apeadero»).
2. Acerca el móvil al tag. Se abre la página, sale la **medalla** 🚂 y la pista
   siguiente. Míralo también en `python servidor.py jugadores`: si abriste con
   `?u=<token>`, el progreso sube al servidor.

Claves de las estaciones del contenido actual:
`a7f3c1` (El apeadero) · `b2e9d4` (Los hórreos) · `c8a05f` (La Regalina).
Como sólo tienes un tag, reescríbelo con la clave que quieras probar; se reescribe
en segundos.

### c) Cuentas y retomar en otro móvil
1. Abre `BASE/?u=7af993` (Martina) y avanza algo (toca el tag, o usa `?demo` no,
   la demo va aparte — mejor toca el tag con `?u=`).
2. Abre esa misma URL `?u=7af993` en **otro navegador o el modo incógnito**:
   retoma el progreso guardado en el servidor. El token se queda guardado en el
   móvil, así que sobrevive a las recargas por tag.

### d) Contenido dinámico (cambiar sin regrabar el tag)
1. Edita `contenido.json` (p.ej. cambia una `pista` o mueve un `spawn`).
2. `python servidor.py publicar contenido.json`
3. En el móvil, recarga la página **con cobertura dos veces** (la primera cachea,
   la segunda aplica). Verás el cambio **sin tocar el tag**: el tag sigue con la
   misma URL `?k=`.

### e) Spawns (la capa tipo Pokémon Go)
El contenido trae un spawn de ejemplo (⛲ «Fuente») en el mapa del pueblo.
Aparece como un punto de oro en el mapa (en modo normal, no en `?demo`) y se
**captura al pasar a menos de 25 m**: suena, vibra y sale un aviso. Eso sólo se
dispara caminando de verdad por Cadavedo (o marcando la posición en
`?modo=autor` cerca de sus coordenadas).

## 4 · Notas

- En casa, el GPS te sitúa fuera de los mapas de Cadavedo: la niebla no se abre
  y el marcador se pega al borde. Es normal — la niebla real se prueba andando
  allí. Para eso están `?demo` (simulado) y `?modo=autor` (GPS en vivo).
- Reset de una partida: `BASE/?reset` (pregunta antes de borrar).
- La partida de la demo va aparte (`yincana.demo`), no pisa la de verdad.
