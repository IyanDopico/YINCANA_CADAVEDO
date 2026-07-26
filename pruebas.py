#!/usr/bin/env python3
"""
Simulador de yincana: recorre la ruta con un GPS falso y comprueba que todo
responde como debe. Sirve para validar cambios sin salir de casa.

    pip install playwright && playwright install chromium
    python pruebas.py
    python pruebas.py --capturas    # además guarda pantallazos en capturas/

Devuelve 0 si pasa todo, 1 si algo falla.
"""

import argparse, base64, contextlib, functools, http.server, os, socketserver, sys, tempfile, threading, math, json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

import servidor   # el backend: se prueba de punta a punta contra el cliente

# Tesela de mentira (PNG gris 1x1) para no llamar a OSM en las pruebas: el juego
# usa el mapa vivo, pero aquí sólo importa la lógica, no la imagen del mapa.
_PNG_TESELA = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

def teselas_falsas(ctx):
    ctx.route("**/tiles/**", lambda r: r.fulfill(
        status=200, content_type="image/png", body=_PNG_TESELA))

RAIZ = Path(__file__).parent.resolve()
BASE = None          # se fija al arrancar el servidor, con puerto libre

fallos, pruebas = [], 0


def comprobar(condicion, descripcion, detalle=""):
    global pruebas
    pruebas += 1
    if condicion:
        print(f"  ok   {descripcion}")
    else:
        print(f"  FALLA {descripcion}" + (f"  ({detalle})" if detalle else ""))
        fallos.append(descripcion)


class _Callado(http.server.SimpleHTTPRequestHandler):
    """Servidor de ficheros sin log: el 404 de mapa.jpg es normal si aún no
    has generado el mapa, y ensucia la salida de las pruebas."""
    def log_message(self, *a):
        pass


class _Servidor(socketserver.TCPServer):
    # Como atributo de clase, no de instancia: si no, se aplica después de
    # bind() y el puerto sigue en TIME_WAIT tras la ejecución anterior.
    allow_reuse_address = True


def servir():
    """Puerto 0 = que lo elija el sistema. Así dos ejecuciones seguidas no
    chocan por TIME_WAIT ni con nada que tengas levantado."""
    global BASE
    h = functools.partial(_Callado, directory=str(RAIZ))
    s = _Servidor(("127.0.0.1", 0), h)
    BASE = f"http://127.0.0.1:{s.server_address[1]}/index.html"
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def leer_config():
    """Saca los capítulos del bloque CONFIG sin ejecutar la página.

    Trocea por el `id:` que abre cada capítulo, así que ese campo tiene que ir
    primero. Devuelve la lista en orden de juego."""
    txt = (RAIZ / "index.html").read_text(encoding="utf-8")
    ini = txt.index("const CONFIG = {")
    fin = txt.index("\n};", ini)
    cuerpo = txt[ini:fin]

    cortes = list(re.finditer(r'id:\s*"(\w+)"', cuerpo))
    if not cortes:
        sys.exit("No encuentro ningún capítulo con 'id' en el CONFIG.")

    caps = []
    for i, c in enumerate(cortes):
        trozo = cuerpo[c.start(): cortes[i+1].start() if i+1 < len(cortes)
                       else len(cuerpo)]
        esq = re.search(r"esquinas:\s*\{([^}]+)\}", trozo)
        if not esq:
            sys.exit(f"El capítulo {c.group(1)} no tiene 'esquinas'.")
        ini_demo = re.search(r"inicioDemo:\s*\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)", trozo)
        mapa = re.search(r'mapa:\s*"([^"]+)"', trozo)
        caps.append({
            "id": c.group(1),
            "mapa": mapa.group(1) if mapa else None,
            "esquinas": {k: float(v) for k, v in
                         re.findall(r"(\w+)\s*:\s*(-?[\d.]+)", esq.group(1))},
            "inicioDemo": (float(ini_demo.group(1)), float(ini_demo.group(2)))
                          if ini_demo else None,
            "estaciones": [(k, float(la), float(lo)) for k, la, lo in re.findall(
                r'k:"(\w+)".*?lat:\s*(-?[\d.]+),\s*lon:\s*(-?[\d.]+)', trozo)],
        })
    return caps


def dentro(esq, la, lo):
    return (esq["sur"] <= la <= esq["norte"] and
            esq["oeste"] <= lo <= esq["este"])


def leer_radios():
    """Los radios del CONFIG, que van antes de los capítulos."""
    txt = (RAIZ / "index.html").read_text(encoding="utf-8")
    ini = txt.index("const CONFIG = {")
    cuerpo = txt[ini: txt.index("capitulos:", ini)]
    return {k: float(v) for k, v in
            re.findall(r"(radio\w+)\s*:\s*(-?[\d.]+)", cuerpo)}


def margen(esq, la, lo):
    """Metros hasta el borde más cercano del recuadro."""
    return min(distancia(la, lo, esq["sur"], lo),
               distancia(la, lo, esq["norte"], lo),
               distancia(la, lo, la, esq["oeste"]),
               distancia(la, lo, la, esq["este"]))


def distancia(la1, lo1, la2, lo2):
    R, r = 6371000.0, math.radians
    dla, dlo = r(la2 - la1), r(lo2 - lo1)
    a = math.sin(dla/2)**2 + math.cos(r(la1))*math.cos(r(la2))*math.sin(dlo/2)**2
    return 2 * R * math.asin(min(1, math.sqrt(a)))


def caminar(ctx, pg, origen, destino, pasos=45, espera=70, precision=9):
    """Interpola el trayecto para que el suavizado exponencial se comporte
    como en la calle. Pasos grandes falsean el resultado: el filtro va con
    retraso y nunca llega a entrar en la zona."""
    for i in range(1, pasos + 1):
        t = i / pasos
        ctx.set_geolocation({
            "latitude":  origen[0] + (destino[0] - origen[0]) * t,
            "longitude": origen[1] + (destino[1] - origen[1]) * t,
            "accuracy":  precision})
        pg.wait_for_timeout(espera)
    for _ in range(6):   # se quedan quietos buscando la etiqueta
        ctx.set_geolocation({"latitude": destino[0], "longitude": destino[1],
                             "accuracy": precision})
        pg.wait_for_timeout(110)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capturas", action="store_true")
    ap.add_argument("--ver", action="store_true", help="navegador visible")
    args = ap.parse_args()

    caps = leer_config()
    todas = [e for c in caps for e in c["estaciones"]]
    if args.capturas:
        (RAIZ / "capturas").mkdir(exist_ok=True)

    print(f"\nCONFIG: {len(caps)} capítulos, {len(todas)} estaciones")
    for c in caps:
        e = c["esquinas"]
        print(f"  {c['id']}: {len(c['estaciones'])} estaciones, recuadro "
              f"{e['sur']}..{e['norte']} x {e['oeste']}..{e['este']}")
    print()

    # ── 0 · el config tiene que ser coherente consigo mismo ──────────────
    print("Configuración")
    for c in caps:
        for k, la, lo in c["estaciones"]:
            comprobar(dentro(c["esquinas"], la, lo),
                      f"la estación {k} cae dentro del mapa de {c['id']}",
                      f"{la}, {lo} está fuera del recuadro")
        comprobar(bool(c["estaciones"]),
                  f"el capítulo {c['id']} tiene alguna estación")
        # Si el arranque de la demo cae fuera, la demo empieza en un mapa que
        # no se ve y parece que está rota.
        comprobar(c["inicioDemo"] is not None and
                  dentro(c["esquinas"], *c["inicioDemo"]),
                  f"el arranque de la demo de {c['id']} cae dentro de su mapa",
                  str(c["inicioDemo"]))
    comprobar(len({k for k, _, _ in todas}) == len(todas),
              "no hay dos estaciones con la misma clave")

    # Pegada al borde, la pisada despeja un círculo cortado y el baile normal
    # del GPS deja al jugador fuera del mapa justo cuando más cerca está.
    radios = leer_radios()
    holgura = radios["radioNiebla"] + radios["radioZona"]
    for c in caps:
        for k, la, lo in c["estaciones"]:
            m = margen(c["esquinas"], la, lo)
            comprobar(m >= holgura,
                      f"la estación {k} no queda pegada al borde del mapa",
                      f"a {m:.0f} m del borde, y hacen falta {holgura:.0f}")
    # v2: el mapa es vivo (teselas), ya no hay imágenes pre-generadas por
    # capítulo. Lo que sí tiene que cachear sw.js es Leaflet, o la página no
    # arranca sin cobertura.
    sw = (RAIZ / "sw.js").read_text(encoding="utf-8")
    comprobar("vendor/leaflet/leaflet.js" in sw,
              "sw.js cachea Leaflet para funcionar sin cobertura")

    srv = servir()
    esquinas = caps[0]["esquinas"]
    origen = (esquinas["sur"] + (esquinas["norte"] - esquinas["sur"]) * 0.25,
              esquinas["oeste"] + (esquinas["este"] - esquinas["oeste"]) * 0.25)
    primera = todas[0]

    with sync_playwright() as p:
        nav = p.chromium.launch(headless=not args.ver)
        ctx = nav.new_context(
            viewport={"width": 390, "height": 844}, device_scale_factor=2,
            is_mobile=True, has_touch=True, permissions=["geolocation"],
            geolocation={"latitude": origen[0], "longitude": origen[1],
                         "accuracy": 9})
        teselas_falsas(ctx)
        pg = ctx.new_page()
        errores = []
        pg.on("pageerror", lambda e: errores.append(str(e)))

        # ?reset ahora pregunta antes de borrar. Aceptamos siempre y guardamos
        # el texto, que hay una comprobación que mira que salga de verdad.
        dialogos = []
        pg.on("dialog", lambda d: (dialogos.append(d.message), d.accept()))

        def captura(nombre):
            if args.capturas:
                pg.screenshot(path=str(RAIZ / "capturas" / f"{nombre}.png"))

        # ── 1 · arranque ────────────────────────────────────────────────
        print("\nArranque")
        pg.goto(BASE)
        pg.wait_for_timeout(600)
        comprobar(not pg.is_hidden("#capaInicio"), "sale la pantalla de inicio")
        captura("1-inicio")
        pg.click("#btnEmpezar")
        pg.wait_for_timeout(500)
        comprobar(pg.is_hidden("#capaInicio"), "el botón oculta la pantalla de inicio")

        # ── 2 · lo que cuesta estar quieto ──────────────────────────────
        # Tres días con la pantalla encendida: lejos de la estación no hay nada
        # animado y el HUD no debería repintarse en cada fotograma. Se cuentan
        # los clearRect parcheando el contexto desde aquí, sin tocar la página.
        print("\nGasto en reposo")
        pg.evaluate("""() => {
            const g = document.getElementById('hud').getContext('2d');
            const orig = g.clearRect.bind(g);
            window.__n = 0;
            g.clearRect = (...a) => { window.__n++; return orig(...a); };
        }""")
        pg.evaluate("distActual = CONFIG.radioAudio * 10")   # como si estuvieran lejos
        pg.wait_for_timeout(2000)
        repintes = pg.evaluate("window.__n")
        comprobar(repintes <= 5,
                  f"repintados del HUD estando quietos y lejos: {repintes} en 2 s",
                  "a 60 fps saldrían ~120: el filtro de repintado no está actuando")

        # ── 3 · caminar hacia la primera estación ───────────────────────
        print("\nRecorrido")
        caminar(ctx, pg, origen, (primera[1], primera[2]))
        captura("2-en-zona")

        rastro = pg.evaluate(
            "JSON.parse(localStorage.getItem('yincana.v1')).rastro.length")
        comprobar(rastro > 3, "el rastro se va guardando", f"{rastro} puntos")

        recorrido = distancia(*origen, primera[1], primera[2])
        comprobar(rastro < recorrido / 5,
                  "el rastro se diezma en vez de guardar cada lectura",
                  f"{rastro} puntos para {recorrido:.0f} m")

        dist = pg.inner_text("#dist")
        comprobar(dist.isdigit() and int(dist) <= 25,
                  "la distancia mostrada llega a la zona", f"marca {dist}")
        comprobar("cerca" in pg.eval_on_selector("#dist", "e=>e.className"),
                  "el número se pone en ámbar al llegar")
        comprobar("ESTÁIS" in pg.inner_text("#pistaTitulo").upper(),
                  "salta el aviso de estar encima",
                  pg.inner_text("#pistaTitulo"))
        # El de 6 no lee: el aviso tiene que verse sin leer nada.
        comprobar("encima" in pg.eval_on_selector("body", "e => e.className"),
                  "y el instrumento lo enseña sin depender del texto",
                  pg.eval_on_selector("body", "e => e.className"))

        # ── 3 · alineación niebla / mapa ────────────────────────────────
        # Con el mapa vivo, la niebla es un canvas anclado a coordenadas: el
        # agujero tiene que caer justo donde está el jugador (lo proyecta
        # Leaflet). Se lee el alfa del canvas de la capa de niebla.
        print("\nAlineación")
        alfa = pg.evaluate("""() => {
            const nube = niebla._image, g = nube.getContext('2d');
            const p = map.project([pos.lat, pos.lon], niebla._zref).subtract(niebla._nwZ);
            const aqui  = g.getImageData(Math.round(p.x), Math.round(p.y), 1, 1).data[3];
            const lejos = g.getImageData(2, 2, 1, 1).data[3];
            const cp = map.latLngToContainerPoint([pos.lat, pos.lon]);
            return { aqui, lejos, x: cp.x, y: cp.y, W, H };
        }""")
        comprobar(alfa["aqui"] < 40,
                  "la niebla está despejada justo donde está el jugador",
                  f"alfa={alfa['aqui']}")
        comprobar(alfa["lejos"] > 200,
                  "la niebla sigue cerrada en una esquina sin pisar",
                  f"alfa={alfa['lejos']}")
        comprobar(0 <= alfa["x"] <= alfa["W"] and 0 <= alfa["y"] <= alfa["H"],
                  "el marcador cae dentro del lienzo",
                  f"({alfa['x']:.0f}, {alfa['y']:.0f}) en {alfa['W']}x{alfa['H']}")

        # Tres días caminando son un par de miles de pisadas. Ahora la niebla no
        # se repinta al mover ni al hacer zoom (Leaflet la desplaza), sólo al
        # (re)montar el mapa: reconstruir con 2000 pisadas tiene que ir sobrado.
        ms = pg.evaluate("""() => {
            const b = niebla._bounds, N = b.getNorth(), S = b.getSouth(),
                  E = b.getEast(), Wt = b.getWest();
            const r = [];
            for (let i = 0; i < 2000; i++)
                r.push([S + Math.random()*(N-S), Wt + Math.random()*(E-Wt)]);
            const t0 = performance.now();
            niebla.reconstruir(r);
            const t = performance.now() - t0;
            niebla.reconstruir(estado.rastro);   // restaura lo real
            return t;
        }""")
        comprobar(ms < 800,
                  f"reconstruir la niebla con 2000 pisadas: {ms:.0f} ms",
                  "sólo pasa al montar el mapa, pero aun así no puede tardar")

        # ── 4 · desbloqueo por etiqueta ─────────────────────────────────
        print("\nEtiquetas NFC")
        pg.goto(f"{BASE}?k={primera[0]}")
        pg.wait_for_timeout(900)
        comprobar(not pg.is_hidden("#capaLogro"), "la etiqueta abre la medalla")
        comprobar(pg.url.endswith("index.html"),
                  "la clave se borra de la barra de direcciones")
        abiertas = pg.evaluate(
            "JSON.parse(localStorage.getItem('yincana.v1')).abiertas")
        comprobar(abiertas == [primera[0]], "queda guardada como abierta",
                  str(abiertas))
        captura("3-logro")

        rastro2 = pg.evaluate(
            "JSON.parse(localStorage.getItem('yincana.v1')).rastro.length")
        comprobar(rastro2 >= rastro,
                  "la niebla despejada sobrevive a la recarga",
                  f"{rastro} -> {rastro2}")

        pg.click("#btnSeguir")
        pg.wait_for_timeout(600)
        comprobar(pg.is_hidden("#capaLogro"), "el botón Seguir cierra la medalla")
        captura("4-siguiente")

        if len(todas) > 1:
            comprobar("2 DE" in pg.inner_text("#pistaTitulo").upper(),
                      "pasa a la pista siguiente",
                      pg.inner_text("#pistaTitulo"))

        # ── 5 · casos raros que van a pasar seguro ──────────────────────
        print("\nCasos raros")
        pg.goto(f"{BASE}?k={primera[0]}")
        pg.wait_for_timeout(600)
        comprobar("YA" in pg.inner_text("#logroNombre").upper(),
                  "una etiqueta repetida avisa en vez de contar dos veces",
                  pg.inner_text("#logroNombre"))

        if len(todas) > 2:
            pg.goto(f"{BASE}?k={todas[2][0]}")
            pg.wait_for_timeout(600)
            comprobar("TODAVÍA" in pg.inner_text("#logroNombre").upper(),
                      "una etiqueta adelantada no rompe el orden",
                      pg.inner_text("#logroNombre"))

        antes = pg.evaluate(
            "JSON.parse(localStorage.getItem('yincana.v1')).abiertas.length")
        pg.goto(f"{BASE}?k=noexiste000")
        pg.wait_for_timeout(600)
        comprobar(pg.evaluate(
            "JSON.parse(localStorage.getItem('yincana.v1')).abiertas.length")
            == antes, "una clave inventada no desbloquea nada")
        comprobar("ESTA NO ES" in pg.inner_text("#logroNombre").upper(),
                  "y lo dice, en vez de quedarse callada",
                  pg.inner_text("#logroNombre"))

        # ── 6 · una sola zona: sin traslado ni cambio de mapa ───────────
        # En la v2 todo es un mapa vivo: abrir una estación no muestra pantalla
        # de traslado ni reinicia la niebla ya despejada.
        if len(todas) > 1:
            print("\nUna sola zona")
            despejado_antes = pg.evaluate("""() => {
                const c = niebla._image, d = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
                let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] < 40) n++; return n;
            }""")
            pg.goto(f"{BASE}?k={todas[1][0]}")
            pg.wait_for_timeout(700)
            if not pg.is_hidden("#capaLogro"):
                pg.click("#btnSeguir")
                pg.wait_for_timeout(500)
            comprobar(pg.is_hidden("#capaTraslado"),
                      "al abrir una estación no sale pantalla de traslado")
            despejado_ahora = pg.evaluate("""() => {
                const c = niebla._image, d = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
                let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] < 40) n++; return n;
            }""")
            comprobar(despejado_ahora >= despejado_antes,
                      "la niebla despejada no se reinicia al abrir una estación",
                      f"{despejado_antes} -> {despejado_ahora}")

        # ── 7 · terminar la yincana ─────────────────────────────────────
        print("\nFinal")
        for k, _, _ in todas[1:]:
            pg.goto(f"{BASE}?k={k}")
            pg.wait_for_timeout(500)
            if not pg.is_hidden("#capaLogro"):
                pg.click("#btnSeguir")
                pg.wait_for_timeout(300)
            if not pg.is_hidden("#capaTraslado"):
                pg.click("#btnTraslado")
                pg.wait_for_timeout(300)
        abiertas = pg.evaluate(
            "JSON.parse(localStorage.getItem('yincana.v1')).abiertas")
        comprobar(len(abiertas) == len(todas),
                  "se pueden abrir todas las estaciones",
                  f"{len(abiertas)} de {len(todas)}")
        comprobar(pg.inner_text("#dist").strip() == "✓",
                  "el instrumento marca expedición completa",
                  pg.inner_text("#dist"))

        comprobar(not pg.is_hidden("#capaFinal"), "sale la pantalla de cierre")
        medallas = pg.eval_on_selector_all("#finMedallas span", "e => e.length")
        comprobar(medallas == len(todas), "con todas las medallas",
                  f"{medallas} de {len(todas)}")
        comprobar("caminados" in pg.inner_text("#finResumen"),
                  "y el resumen del recorrido", pg.inner_text("#finResumen"))
        comprobar(len(pg.inner_text("#finTexto")) > 20,
                  "y dice dónde está el tesoro de verdad")
        captura("5-final")

        # El premio: la niebla se disuelve entera y queda el mapa vivo a la vista.
        opacos = pg.evaluate("""() => {
            const c = niebla._image;
            const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
            let n = 0;
            for (let i = 3; i < d.length; i += 4) if (d[i] > 40) n++;
            return n;
        }""")
        comprobar(opacos == 0, "al terminar el mapa se queda entero a la vista",
                  f"{opacos} píxeles siguen con niebla")

        pg.click("#btnFinal")
        pg.wait_for_timeout(400)
        comprobar(pg.is_hidden("#capaFinal"), "el botón cierra la pantalla final")

        # ── 8 · reinicio ────────────────────────────────────────────────
        dialogos.clear()
        pg.goto(f"{BASE}?reset")
        pg.wait_for_timeout(500)
        est = pg.evaluate("JSON.parse(localStorage.getItem('yincana.v1'))")
        comprobar(est["abiertas"] == [] and est["rastro"] == [],
                  "?reset deja la partida a cero", json.dumps(est)[:60])
        # Es una dirección corta que se queda en el historial, y lo que borra
        # es lo único que se llevan de recuerdo.
        comprobar(any("borrar" in d.lower() for d in dialogos),
                  "pero antes pregunta", str(dialogos)[:70])

        # ── 9 · dos móviles, dos partidas ───────────────────────────────
        # Cada móvil lleva su localStorage. Si a uno se le pasa una etiqueta
        # tiene que poder ponerse al día en la siguiente, o va desfasado el
        # resto del juego sin que nadie se entere.
        if len(todas) > 1 and pg.evaluate("CONFIG.perdonarSiPasaronCerca"):
            print("\nDos móviles")

            # Un móvil que caminó hasta la primera estación pero al que no le
            # llegaron a acercar la etiqueta: al tocar la siguiente tiene que
            # ponerse al día, porque su rastro demuestra que estuvo allí.
            pg.goto(BASE)
            pg.wait_for_timeout(400)
            pg.click("#btnEmpezar")
            pg.wait_for_timeout(300)
            caminar(ctx, pg, origen, (todas[0][1], todas[0][2]))
            pg.goto(f"{BASE}?k={todas[1][0]}")
            pg.wait_for_timeout(800)
            comprobar(pg.evaluate(
                "JSON.parse(localStorage.getItem('yincana.v1')).abiertas")
                == [todas[0][0], todas[1][0]],
                "el móvil que se saltó una etiqueta se pone al día en la siguiente",
                str(pg.evaluate(
                    "JSON.parse(localStorage.getItem('yincana.v1')).abiertas")))
            comprobar("TODAVÍA" not in pg.inner_text("#logroNombre").upper(),
                      "y sin soltarle el aviso de que no toca",
                      pg.inner_text("#logroNombre"))

            # Y sin haber pasado por allí no se perdona: eso es una etiqueta
            # encontrada antes de tiempo, no un despiste.
            pg.goto(f"{BASE}?reset")
            pg.wait_for_timeout(400)
            pg.goto(f"{BASE}?k={todas[1][0]}")
            pg.wait_for_timeout(700)
            comprobar("TODAVÍA" in pg.inner_text("#logroNombre").upper(),
                      "sin rastro que lo justifique se le sigue avisando",
                      pg.inner_text("#logroNombre"))
            comprobar(pg.evaluate(
                "JSON.parse(localStorage.getItem('yincana.v1')).abiertas") == [],
                "y no abre nada")

            pg.goto(f"{BASE}?reset")
            pg.wait_for_timeout(400)

        # ── 10 · modo autor ─────────────────────────────────────────────
        # El modo autor v1 (marcar puntos + copiar URLs) queda aparcado en la
        # v2: la colocación de etiquetas pasa a ser por escaneo + GPS con sesión
        # de admin (F4). Sólo se comprueba que ?modo=autor no revienta.
        print("\nModo autor (aparcado)")
        pg.goto(f"{BASE}?modo=autor")
        pg.wait_for_timeout(700)
        comprobar(not pg.is_hidden("#autor"),
                  "?modo=autor muestra el aviso de que está en preparación")

        # ── 11 · modo demo ──────────────────────────────────────────────
        # Tiene que funcionar sin permiso de geolocalización: es su motivo de
        # existir, poder enseñarlo en un portátil.
        print("\nModo demo")
        ctx2 = nav.new_context(viewport={"width": 390, "height": 844},
                               device_scale_factor=2, is_mobile=True,
                               has_touch=True)          # sin permisos ni GPS
        teselas_falsas(ctx2)
        pd = ctx2.new_page()
        err2 = []
        pd.on("pageerror", lambda e: err2.append(str(e)))
        pd.goto(f"{BASE}?demo")
        pd.wait_for_timeout(500)
        comprobar("demo" in pd.inner_text("#btnEmpezar").lower(),
                  "el botón de inicio avisa de que es una demo",
                  pd.inner_text("#btnEmpezar"))
        pd.click("#btnEmpezar")
        pd.wait_for_timeout(600)
        comprobar(pd.is_visible("#demoBarra"), "salen los mandos de la demo")

        pd.click("#demoVel")                    # acelerar para no esperar
        pd.click("#demoVel")
        pd.wait_for_timeout(11000)
        comprobar(pd.is_visible("#demoBarra"),
                  "los mandos siguen accesibles con la medalla en pantalla")
        abiertas_d = pd.evaluate(
            "JSON.parse(localStorage.getItem('yincana.demo')).abiertas")
        comprobar(len(abiertas_d) >= 1,
                  "la demo camina sola y desbloquea estaciones",
                  f"{len(abiertas_d)} abiertas")
        if args.capturas:
            pd.screenshot(path=str(RAIZ / "capturas" / "7-demo.png"))

        real = pd.evaluate("localStorage.getItem('yincana.v1')")
        comprobar(real is None,
                  "la demo no pisa la partida de verdad", str(real)[:40])

        # Y tiene que llegar sola hasta el final, salto de capítulo incluido:
        # es lo que va a ver quien se la enseñes, y si se atasca en la pantalla
        # de traslado no hay nadie ahí para pulsar.
        completa = False
        for _ in range(60):
            pd.wait_for_timeout(1000)
            if len(pd.evaluate(
                    "JSON.parse(localStorage.getItem('yincana.demo')).abiertas")
                   ) == len(todas):
                completa = True
                break
        comprobar(completa,
                  "la demo llega al final ella sola, cambiando de mapa por el camino",
                  str(pd.evaluate(
                      "JSON.parse(localStorage.getItem('yincana.demo')).abiertas")))
        pd.wait_for_timeout(4000)     # la última medalla antes del cierre
        comprobar(not pd.is_hidden("#capaFinal"),
                  "y remata en la pantalla de cierre")
        if args.capturas:
            pd.screenshot(path=str(RAIZ / "capturas" / "8-demo-final.png"))

        pd.click("#demoOtra", force=True)
        pd.wait_for_timeout(600)
        comprobar(pd.evaluate(
            "JSON.parse(localStorage.getItem('yincana.demo')).abiertas") == [],
            "el botón Repetir deja la demo a cero")
        comprobar(not err2, "la demo no suelta errores de JavaScript",
                  "; ".join(err2[:2]))
        ctx2.close()

        # ── 12 · sin cobertura ──────────────────────────────────────────
        # En el pueblo puede no haber datos. El GPS no los necesita, la web sí,
        # y de eso va el service worker. Es la regla que más caro sale romper y
        # hasta ahora no la comprobaba nadie.
        print("\nSin cobertura")
        pg.goto(f"{BASE}?reset")
        pg.wait_for_timeout(700)
        activo = pg.evaluate("""async () => {
            if (!('serviceWorker' in navigator)) return "sin soporte";
            const reg = await navigator.serviceWorker.ready;
            return reg.active ? "activo" : "sin activar";
        }""")
        comprobar(activo == "activo", "el service worker queda activo", str(activo))

        pg.wait_for_timeout(1200)          # que le dé tiempo a guardar la copia
        ctx.set_offline(True)
        try:
            pg.goto(f"{BASE}?k={primera[0]}")
            pg.wait_for_timeout(1200)
            comprobar(pg.inner_text("#nombrePueblo").strip() not in ("—", ""),
                      "la página carga sin datos",
                      pg.inner_text("#nombrePueblo"))
            comprobar(not pg.is_hidden("#capaLogro"),
                      "y la etiqueta desbloquea igual sin cobertura")
            comprobar(pg.evaluate(
                "JSON.parse(localStorage.getItem('yincana.v1')).abiertas")
                == [primera[0]], "y queda guardada")
        except Exception as e:
            comprobar(False, "la página carga sin datos", str(e)[:90])
        finally:
            ctx.set_offline(False)

        # ── 13 · una partida guardada que no vale ───────────────────────
        # Puede venir de una versión anterior, de un guardado a medias o de un
        # dedo curioso. Lo que no puede es dejar la página en blanco: ahí se
        # acaba la yincana y no hay forma de recuperarla en mitad del monte.
        print("\nPartida corrupta")
        pg.evaluate("""() => localStorage.setItem('yincana.v1',
            JSON.stringify({ rastro: null, abiertas: "no soy una lista" }))""")
        pg.goto(BASE)
        pg.wait_for_timeout(700)
        comprobar(pg.inner_text("#nombrePueblo").strip() not in ("—", ""),
                  "no deja la página en blanco", pg.inner_text("#nombrePueblo"))
        forma = pg.evaluate(
            "({r: Array.isArray(estado.rastro), a: Array.isArray(estado.abiertas)})")
        comprobar(forma["r"] and forma["a"], "y el estado queda con la forma buena",
                  str(forma))

        # Esta pasa seguro: recapturas las coordenadas con ?modo=autor, salen
        # claves nuevas, y el móvil aún tiene guardadas las de la prueba.
        pg.evaluate("""() => localStorage.setItem('yincana.v1',
            JSON.stringify({ rastro: [], abiertas: ["claveinventada"] }))""")
        pg.goto(BASE)
        pg.wait_for_timeout(700)
        comprobar(pg.evaluate("estado.abiertas.length") == 0,
                  "las claves de una partida vieja se descartan",
                  str(pg.evaluate("estado.abiertas")))
        comprobar(pg.evaluate("capPintado.id") == caps[0]["id"],
                  "y se vuelve al primer capítulo, no a la yincana terminada",
                  pg.evaluate("capPintado.id"))

        # ── 14 · sin errores por el camino ──────────────────────────────
        print("\nConsola")
        comprobar(not errores, "ningún error de JavaScript", "; ".join(errores[:3]))

        # ── 15 · servidor: contenido dinámico y sincronización ──────────
        # Con el servidor delante, el contenido puede cambiar sin regrabar
        # etiquetas y el progreso se retoma en otro móvil. Sin servidor (el
        # resto de la suite corre contra uno sin /api) se juega con el CONFIG
        # integrado: esa es la regla que no se toca, y ya la prueban las 92.
        print("\nServidor")
        tmpdb = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmpdb.close()
        bd_orig = servidor.BD
        servidor.BD = servidor.Path(tmpdb.name)
        try:
            with contextlib.closing(servidor.conectar()) as c:
                contenido = json.loads(
                    (RAIZ / "contenido.json").read_text(encoding="utf-8"))
                # marca reconocible: si aparece, el contenido del servidor se aplicó
                contenido["pueblo"] = "Cadavedo (servidor)"
                servidor.publicar_contenido(c, contenido)
                token = servidor.crear_cuenta(c, "Martina")
                servidor.fusionar_progreso(c, token, {"abiertas": [todas[0][0]]})

            api = servidor.Servidor(("127.0.0.1", 0), servidor.Handler)
            api_port = api.server_address[1]
            threading.Thread(target=api.serve_forever, daemon=True).start()
            api_url = f"http://127.0.0.1:{api_port}/index.html"

            # Contenido dinámico: se cachea en la primera carga y se aplica en la
            # siguiente (no se reordena el mapa bajo los pies del que juega).
            ctx3 = nav.new_context(
                viewport={"width": 390, "height": 844}, device_scale_factor=2,
                is_mobile=True, has_touch=True, permissions=["geolocation"],
                geolocation={"latitude": origen[0], "longitude": origen[1],
                             "accuracy": 9})
            teselas_falsas(ctx3)
            pe = ctx3.new_page()
            err3 = []
            pe.on("pageerror", lambda e: err3.append(str(e)))
            pe.goto(api_url); pe.wait_for_timeout(900)   # cachea el contenido
            pe.goto(api_url); pe.wait_for_timeout(900)   # lo aplica
            comprobar(pe.inner_text("#nombrePueblo").strip() == "Cadavedo (servidor)",
                      "el contenido del servidor se aplica en la carga siguiente",
                      pe.inner_text("#nombrePueblo"))
            comprobar(pe.evaluate("SPAWNS.length") >= 1,
                      "los spawns del contenido llegan al cliente",
                      str(pe.evaluate("SPAWNS.length")))

            # Y una vez cacheado, sigue sin cobertura: el contenido tampoco
            # puede depender de la red una vez descargado.
            pe.evaluate("""async () => {
                if ('serviceWorker' in navigator) await navigator.serviceWorker.ready;
            }""")
            pe.wait_for_timeout(800)
            ctx3.set_offline(True)
            try:
                pe.goto(api_url); pe.wait_for_timeout(1000)
                comprobar(pe.inner_text("#nombrePueblo").strip() == "Cadavedo (servidor)",
                          "y el contenido cacheado sigue sin cobertura",
                          pe.inner_text("#nombrePueblo"))
            finally:
                ctx3.set_offline(False)
            ctx3.close()

            # Retomar en otro móvil: un contexto limpio con el mismo token
            # rehidrata el progreso guardado en el servidor.
            ctx4 = nav.new_context(
                viewport={"width": 390, "height": 844}, device_scale_factor=2,
                is_mobile=True, has_touch=True, permissions=["geolocation"],
                geolocation={"latitude": origen[0], "longitude": origen[1],
                             "accuracy": 9})
            teselas_falsas(ctx4)
            pf = ctx4.new_page()
            err4 = []
            pf.on("pageerror", lambda e: err4.append(str(e)))
            pf.goto(f"http://127.0.0.1:{api_port}/index.html?u={token}")
            pf.wait_for_timeout(1600)
            abiertas_srv = pf.evaluate(
                "JSON.parse(localStorage.getItem('yincana.v1') || '{}').abiertas || []")
            comprobar(abiertas_srv == [todas[0][0]],
                      "un móvil nuevo con el token retoma el progreso del servidor",
                      str(abiertas_srv))

            # Y el camino de vuelta: lo que abra este móvil sube al servidor.
            pf.goto(f"http://127.0.0.1:{api_port}/index.html?u={token}&k={todas[1][0]}"
                    if len(todas) > 1 else
                    f"http://127.0.0.1:{api_port}/index.html?u={token}")
            pf.wait_for_timeout(2000)   # deja que el sync (debounce 4 s no, forzado) suba
            if len(todas) > 1:
                # el push va con debounce de 4 s; esperamos a que salga
                pf.wait_for_timeout(4000)
                with contextlib.closing(servidor.conectar()) as c:
                    guardado = servidor.leer_progreso(c, token)["abiertas"]
                comprobar(todas[1][0] in guardado,
                          "el progreso de este móvil sube al servidor",
                          str(guardado))
            comprobar(not err3 and not err4,
                      "el cliente con servidor no suelta errores de JavaScript",
                      "; ".join((err3 + err4)[:2]))
            ctx4.close()
            api.shutdown(); api.server_close()
        finally:
            servidor.BD = bd_orig
            for suf in ("", "-wal", "-shm"):
                try:
                    os.unlink(tmpdb.name + suf)
                except OSError:
                    pass

        nav.close()
    srv.shutdown()

    print(f"\n{'─'*54}")
    if fallos:
        print(f"{len(fallos)} de {pruebas} comprobaciones fallan:")
        for f in fallos:
            print(f"  · {f}")
        return 1
    print(f"Las {pruebas} comprobaciones pasan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
