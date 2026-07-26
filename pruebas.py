#!/usr/bin/env python3
"""
Simulador de yincana: recorre la ruta con un GPS falso y comprueba que todo
responde como debe. Sirve para validar cambios sin salir de casa.

    pip install playwright && playwright install chromium
    python3 pruebas.py
    python3 pruebas.py --capturas    # además guarda pantallazos en capturas/

Devuelve 0 si pasa todo, 1 si algo falla.
"""

import argparse, functools, http.server, os, socketserver, sys, threading, math, json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

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
    mapas = [c["mapa"] for c in caps]
    comprobar(all(mapas) and len(set(mapas)) == len(mapas),
              "cada capítulo tiene su propia imagen de mapa", str(mapas))

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
        pg = ctx.new_page()
        errores = []
        pg.on("pageerror", lambda e: errores.append(str(e)))

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

        # ── 2 · caminar hacia la primera estación ───────────────────────
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

        # ── 3 · alineación niebla / mapa ────────────────────────────────
        # Esta es la que pilló el fallo del object-fit: si la proyección se
        # desvía, el agujero de la niebla no cae donde está el jugador.
        print("\nAlineación")
        alfa = pg.evaluate("""() => {
            const [x, y] = aPixel(pos.lat, pos.lon);
            const g = document.getElementById('niebla').getContext('2d');
            const aqui  = g.getImageData(Math.round(x*dpr), Math.round(y*dpr), 1, 1).data[3];
            const lejos = g.getImageData(2, 2, 1, 1).data[3];
            return { aqui, lejos, x, y, W, H };
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

        pg.goto(f"{BASE}?k=noexiste000")
        pg.wait_for_timeout(600)
        comprobar(pg.is_hidden("#capaLogro"),
                  "una clave inventada no desbloquea nada")

        # ── 6 · cambio de capítulo ──────────────────────────────────────
        if len(caps) > 1:
            print("\nCapítulos")
            ultima = caps[0]["estaciones"][-1][0]
            pg.goto(f"{BASE}?k={ultima}")
            pg.wait_for_timeout(900)
            comprobar(pg.evaluate("capPintado.id") == caps[0]["id"],
                      "la última medalla no cambia el mapa por detrás",
                      pg.evaluate("capPintado.id"))

            pg.click("#btnSeguir")
            pg.wait_for_timeout(500)
            comprobar(not pg.is_hidden("#capaTraslado"),
                      "al acabar el capítulo avisa del traslado")
            comprobar(pg.evaluate("capPintado.id") == caps[0]["id"],
                      "y espera a que pulsen para cambiar de mapa")
            captura("5-traslado")

            pg.click("#btnTraslado")
            pg.wait_for_timeout(700)
            comprobar(pg.evaluate("capPintado.id") == caps[1]["id"],
                      "al pulsar se abre el mapa del capítulo siguiente",
                      pg.evaluate("capPintado.id"))
            comprobar(pg.is_hidden("#capaTraslado"),
                      "la pantalla de traslado se quita")
            comprobar(pg.evaluate("E.norte") == caps[1]["esquinas"]["norte"],
                      "la proyección pasa a las esquinas del capítulo nuevo",
                      str(pg.evaluate("E.norte")))

            # Lo que más fácil se rompe al partir el mapa: que las pisadas del
            # capítulo anterior abran agujeros en el del siguiente, que está a
            # más de un kilómetro.
            claros = pg.evaluate("""() => {
                const c = document.getElementById('niebla');
                const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
                let n = 0;
                for (let i = 3; i < d.length; i += 4) if (d[i] < 40) n++;
                return n;
            }""")
            comprobar(claros == 0,
                      "el mapa nuevo empieza con la niebla entera",
                      f"{claros} píxeles ya despejados")

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

        # El premio: el mapa entero despejado, sin una brizna de niebla.
        opacos = pg.evaluate("""() => {
            const c = document.getElementById('niebla');
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
        if len(caps) > 1:
            comprobar(pg.is_visible("#finBarra"),
                      "y deja la barra para repasar los dos mapas")
            pg.click("#finBarra button:first-of-type")
            pg.wait_for_timeout(500)
            comprobar(pg.evaluate("capPintado.id") == caps[0]["id"],
                      "que devuelve al mapa del primer capítulo",
                      pg.evaluate("capPintado.id"))

        # ── 8 · reinicio ────────────────────────────────────────────────
        pg.goto(f"{BASE}?reset")
        pg.wait_for_timeout(500)
        est = pg.evaluate("JSON.parse(localStorage.getItem('yincana.v1'))")
        comprobar(est["abiertas"] == [] and est["rastro"] == [],
                  "?reset deja la partida a cero", json.dumps(est)[:60])

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
        print("\nModo autor")
        pg.goto(f"{BASE}?modo=autor")
        pg.wait_for_timeout(900)
        comprobar(not pg.is_hidden("#autor"), "se abre el panel de autor")
        comprobar(pg.inner_text("#aLat") != "—", "muestra la posición en vivo")
        pg.fill("#aNombre", "El lavadero")
        pg.click("#aMarcar")
        pg.wait_for_timeout(400)
        salida = pg.inner_text("#aSalida")
        comprobar('nombre:"El lavadero"' in salida,
                  "el punto marcado sale con su nombre")
        comprobar(re.search(r'k:"[0-9a-f]{6}"', salida) is not None,
                  "genera una clave aleatoria de 6 dígitos hex")
        comprobar("?k=" in salida, "incluye la URL para grabar en la etiqueta")

        # Lo que deja salir a marcar: ver el punto sobre el mapa en vez de
        # fiarse de seis decimales.
        comprobar(pg.is_hidden("footer"), "el panel deja sitio al mapa")
        comprobar(pg.is_hidden("#niebla"), "en modo autor el mapa se ve sin niebla")
        alfa_punto = pg.evaluate("""() => {
            const p = JSON.parse(localStorage.getItem('yincana.autor')).slice(-1)[0];
            const [x, y] = aPixel(p.lat, p.lon);
            const g = document.getElementById('hud').getContext('2d');
            return g.getImageData(Math.round(x*dpr), Math.round(y*dpr), 1, 1).data[3];
        }""")
        comprobar(alfa_punto > 200, "el punto marcado se dibuja sobre el mapa",
                  f"alfa={alfa_punto}")
        captura("6-autor")

        # Y el aviso: un punto fuera de todos los recuadros no se vería en el
        # juego, y eso no puedes descubrirlo con los críos delante.
        lejos = (min(c["esquinas"]["sur"] for c in caps) - 0.02,
                 min(c["esquinas"]["oeste"] for c in caps) - 0.02)
        for _ in range(3):
            ctx.set_geolocation({"latitude": lejos[0], "longitude": lejos[1],
                                 "accuracy": 8})
            pg.wait_for_timeout(350)
        pg.fill("#aNombre", "Punto perdido")
        pg.click("#aMarcar")
        pg.wait_for_timeout(400)
        comprobar(not pg.is_hidden("#aAlerta"),
                  "avisa de que un punto cae fuera de todos los recuadros")
        comprobar("FUERA DE TODOS LOS MAPAS" in pg.inner_text("#aSalida"),
                  "y lo aparta en la salida para que no pase inadvertido")

        # ── 11 · modo demo ──────────────────────────────────────────────
        # Tiene que funcionar sin permiso de geolocalización: es su motivo de
        # existir, poder enseñarlo en un portátil.
        print("\nModo demo")
        ctx2 = nav.new_context(viewport={"width": 390, "height": 844},
                               device_scale_factor=2, is_mobile=True,
                               has_touch=True)          # sin permisos ni GPS
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

        pd.click("#demoOtra", force=True)
        pd.wait_for_timeout(600)
        comprobar(pd.evaluate(
            "JSON.parse(localStorage.getItem('yincana.demo')).abiertas") == [],
            "el botón Repetir deja la demo a cero")
        comprobar(not err2, "la demo no suelta errores de JavaScript",
                  "; ".join(err2[:2]))
        ctx2.close()

        # ── 12 · sin errores por el camino ──────────────────────────────
        print("\nConsola")
        comprobar(not errores, "ningún error de JavaScript", "; ".join(errores[:3]))

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
