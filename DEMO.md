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
YINCANA_PIN=1234 python servidor.py --puerto 8000   # juego + API (con PIN de admin)
python servidor.py publicar contenido.json   # metadatos base (pueblo, radios, spawns)
python servidor.py jugadores            # ver quién va por dónde
python servidor.py estaciones           # ver qué etiquetas están colocadas
```
Los usuarios son fijos (admin/himilce/orian); no se crean. El admin entra con el
PIN de `YINCANA_PIN`.

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

### a) Login
Abre `BASE/` y sale **¿Quién eres?**: Himilce 🦊, Orián 🐢 (botón directo) y
Admin 🧭 (con PIN, el de `YINCANA_PIN`). Al entrar, la sesión queda en una cookie
persistente: al tocar una etiqueta o volver a abrir, no vuelve a pedir quién eres.

### b) Colocar etiquetas (admin) — la herramienta de campo
1. Entra como **Admin**. Pulsa **⚙** → **Nueva etiqueta**: te da una clave y su
   URL (`BASE/?k=<clave>`). Grábala en el tag con **NFC Tools** (registro URL).
   (O usa una etiqueta que ya tengas grabada.)
2. En el sitio donde la escondes: pega el tag, **escanéalo**. Con sesión de admin
   se abre **Colocar etiqueta**: espera a que la precisión baje de 15 m y pulsa
   **Guardar aquí**. Queda su GPS en el servidor.
3. En casa, desde **⚙**, ponle nombre, la pista (dónde está la siguiente) y la
   medalla. `python servidor.py estaciones` lista lo colocado y lo pendiente.

### c) El desbloqueo por NFC (como jugador)
Entra como **Himilce** u **Orián**. El toque del tag **no depende de estar en el
sitio**: abre la URL y desbloquea, así que pruebas el flujo en el sofá. Escanea
un tag colocado → sale la **medalla** y la pista siguiente. Con un solo tag,
reescríbelo con NFC Tools para probar varias claves.

### d) Retomar en otro móvil
Con el mismo usuario logueado en otro navegador/móvil (mismo dominio), el
progreso guardado en el servidor se **retoma solo**. El progreso va por usuario.

### e) Contenido dinámico (cambiar sin regrabar el tag)
Cambiar una pista, mover un spawn o **recolocar una estación** no toca el tag:
la URL `?k=` sigue igual, lo que cambia es lo que el servidor asocia a esa clave.
Los metadatos base (pueblo, radios, spawns) se editan en `contenido.json` +
`python servidor.py publicar contenido.json`; las estaciones, desde el panel ⚙.

### f) Spawns (la capa tipo Pokémon Go)
`contenido.json` trae un spawn de ejemplo (⛲ «Fuente»). Aparece como un punto de
oro en el mapa (modo normal, no en `?demo`) y se **captura al pasar a menos de
25 m**: suena, vibra y sale un aviso. Sólo se dispara caminando de verdad.

## 4 · Notas

- El mapa es **vivo**: en casa te sitúa donde estés (no en Cadavedo), pero la
  niebla y el instrumento funcionan igual. La niebla real de la zona se prueba
  andando por donde coloques las etiquetas. Para verlo sin GPS, `?demo`.
- Reset de una partida: `BASE/?reset` (pregunta antes de borrar).
- La partida de la demo va aparte (`yincana.demo`), no pisa la de verdad, y no
  pide login.
