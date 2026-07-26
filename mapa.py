#!/usr/bin/env python3
"""
Prepara el mapa de la yincana.

Descarga las teselas de OpenStreetMap que cubren un recuadro, las cose en una
sola imagen, la recorta al recuadro exacto y te imprime el bloque `esquinas`
listo para pegar en index.html. La imagen y las coordenadas salen del mismo
cálculo, así que no pueden descuadrarse entre sí.

Uso:
    python3 mapa.py --capitulos                      # los del CONFIG, todos
    python3 mapa.py --capitulos regalina             # sólo uno
    python3 mapa.py 43.5330 -5.6700 43.5400 -5.6600 --salida mapa.jpg
    python3 mapa.py 43.5330 -5.6700 43.5400 -5.6600 --zoom 18 --salida mapa.jpg

Con `--capitulos` saca los recuadros y los nombres de archivo del propio
`index.html`, que es lo suyo el día que estés en el pueblo: ocho números
tecleados a mano son ocho ocasiones de equivocarse.

A mano, los cuatro números son: sur oeste norte este (grados decimales).
Sácalos de openstreetmap.org: encuadra el pueblo, pestaña "Exportar", y ahí
tienes los cuatro límites del recuadro que estás viendo.

Requiere Pillow:  pip install pillow
"""

import argparse, io, math, re, sys, time, urllib.request
from pathlib import Path
from PIL import Image

RAIZ = Path(__file__).parent.resolve()

TESELA = 256
SERVIDOR = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
# La política de uso de OSM exige identificarse. Pon tu correo o tu web.
AGENTE = "yincana-familiar/1.0 (uso personal puntual)"


def grados_a_tesela(lat, lon, z):
    """Coordenada de tesela en fracciones (Web Mercator)."""
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def tesela_a_grados(x, y, z):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def dist(la1, lo1, la2, lo2):
    R = 6371000.0
    dla, dlo = math.radians(la2 - la1), math.radians(lo2 - lo1)
    h = (math.sin(dla / 2) ** 2 + math.cos(math.radians(la1))
         * math.cos(math.radians(la2)) * math.sin(dlo / 2) ** 2)
    return 2 * R * math.asin(min(1, math.sqrt(h)))


def elegir_zoom(sur, oeste, norte, este, lado_max=2400):
    """El zoom más detallado cuya imagen no pase de lado_max píxeles."""
    for z in range(19, 10, -1):
        x0, y0 = grados_a_tesela(norte, oeste, z)
        x1, y1 = grados_a_tesela(sur, este, z)
        if (x1 - x0) * TESELA <= lado_max and (y1 - y0) * TESELA <= lado_max:
            return z
    return 15


def bajar(url, intentos=3):
    for i in range(intentos):
        try:
            pet = urllib.request.Request(url, headers={"User-Agent": AGENTE})
            with urllib.request.urlopen(pet, timeout=20) as r:
                return Image.open(io.BytesIO(r.read())).convert("RGB")
        except Exception as e:
            if i == intentos - 1:
                raise
            time.sleep(1.5 * (i + 1))


def leer_capitulos():
    """Saca id, archivo de mapa y esquinas de cada capítulo de index.html.

    Trocea por el `id:` que abre cada capítulo, igual que `pruebas.py`, así que
    ese campo tiene que ir primero. Sin ejecutar la página y sin dependencias:
    esto se usa en el pueblo, con lo que haya en el portátil."""
    txt = (RAIZ / "index.html").read_text(encoding="utf-8")
    ini = txt.index("const CONFIG = {")
    cuerpo = txt[ini: txt.index("\n};", ini)]

    cortes = list(re.finditer(r'id:\s*"(\w+)"', cuerpo))
    caps = []
    for i, c in enumerate(cortes):
        trozo = cuerpo[c.start(): cortes[i+1].start() if i+1 < len(cortes)
                       else len(cuerpo)]
        esq  = re.search(r"esquinas:\s*\{([^}]+)\}", trozo)
        mapa = re.search(r'mapa:\s*"([^"]+)"', trozo)
        if not esq or not mapa:
            continue
        nums = {k: float(v) for k, v in
                re.findall(r"(\w+)\s*:\s*(-?[\d.]+)", esq.group(1))}
        caps.append({"id": c.group(1), "mapa": mapa.group(1), **nums})
    return caps


def generar(sur, oeste, norte, este, salida, zoom=None):
    """Descarga, cose y recorta. Devuelve las esquinas REALES del recorte."""
    sur, norte = min(sur, norte), max(sur, norte)
    oeste, este = min(oeste, este), max(oeste, este)
    z = zoom or elegir_zoom(sur, oeste, norte, este)

    # Recuadro en píxeles globales del nivel de zoom
    fx0, fy0 = grados_a_tesela(norte, oeste, z)
    fx1, fy1 = grados_a_tesela(sur, este, z)
    tx0, ty0 = math.floor(fx0), math.floor(fy0)
    tx1, ty1 = math.ceil(fx1),  math.ceil(fy1)
    nx, ny = tx1 - tx0, ty1 - ty0

    if nx * ny > 240:
        sys.exit(f"Serían {nx*ny} teselas, demasiadas. Baja el zoom con --zoom {z-1}.")

    print(f"zoom {z} · {nx}x{ny} = {nx*ny} teselas · imagen provisional "
          f"{nx*TESELA}x{ny*TESELA} px")

    lienzo = Image.new("RGB", (nx * TESELA, ny * TESELA), (235, 232, 224))
    n = 0
    for ix in range(nx):
        for iy in range(ny):
            url = SERVIDOR.format(z=z, x=tx0 + ix, y=ty0 + iy)
            try:
                lienzo.paste(bajar(url), (ix * TESELA, iy * TESELA))
            except Exception as e:
                print(f"  tesela {tx0+ix}/{ty0+iy} falló: {e}")
            n += 1
            print(f"\r  {n}/{nx*ny}", end="", flush=True)
            time.sleep(0.12)          # no martillees el servidor de OSM
    print()

    # Recorte al recuadro pedido, con redondeo a entero
    izq   = int(round((fx0 - tx0) * TESELA))
    arr   = int(round((fy0 - ty0) * TESELA))
    der   = int(round((fx1 - tx0) * TESELA))
    aba   = int(round((fy1 - ty0) * TESELA))
    recorte = lienzo.crop((izq, arr, der, aba))

    # Las esquinas REALES tras el redondeo del recorte: esto es lo que hay que
    # pegar en el HTML, no los números que pediste.
    lat_n, lon_o = tesela_a_grados(tx0 + izq / TESELA, ty0 + arr / TESELA, z)
    lat_s, lon_e = tesela_a_grados(tx0 + der / TESELA, ty0 + aba / TESELA, z)

    recorte.save(salida, quality=90)

    ancho = dist(lat_n, lon_o, lat_n, lon_e)
    alto  = dist(lat_n, lon_o, lat_s, lon_o)

    print(f"\nGuardado {salida} · {recorte.width}x{recorte.height} px")
    print(f"Cubre {ancho:.0f} m de ancho por {alto:.0f} m de alto "
          f"({ancho/recorte.width:.2f} m por píxel)")
    # Cuánto abre cada pisada: es el número que decide si el juego se siente
    # vivo o si caminan un montón sin ver nada.
    huella = math.pi * 35 ** 2
    print(f"Con radioNiebla 35 m, cada pisada despeja el "
          f"{100*huella/(ancho*alto):.2f} % del mapa")

    return lat_n, lat_s, lon_o, lon_e


def esquinas_para_pegar(lat_n, lat_s, lon_o, lon_e):
    return (f"  esquinas: {{ norte: {lat_n:.6f}, sur: {lat_s:.6f}, "
            f"oeste: {lon_o:.6f}, este: {lon_e:.6f} }},")


def main():
    p = argparse.ArgumentParser(
        description="Prepara las imágenes de mapa de la yincana y sus esquinas.")
    p.add_argument("sur", type=float, nargs="?")
    p.add_argument("oeste", type=float, nargs="?")
    p.add_argument("norte", type=float, nargs="?")
    p.add_argument("este", type=float, nargs="?")
    p.add_argument("--zoom", type=int, default=None)
    p.add_argument("--salida", default=None)
    p.add_argument("--capitulos", nargs="*", metavar="ID",
                   help="sacar los recuadros de index.html; sin argumentos, todos")
    a = p.parse_args()

    if a.capitulos is not None:
        caps = leer_capitulos()
        if not caps:
            sys.exit("No encuentro capítulos en el CONFIG de index.html.")
        if a.capitulos:
            pedidos = set(a.capitulos)
            sueltos = pedidos - {c["id"] for c in caps}
            if sueltos:
                sys.exit(f"No existe el capítulo {', '.join(sorted(sueltos))}. "
                         f"Hay: {', '.join(c['id'] for c in caps)}.")
            caps = [c for c in caps if c["id"] in pedidos]

        hechos = []
        for c in caps:
            print(f"\n{'─'*54}\n{c['id']} → {c['mapa']}\n")
            hechos.append((c["id"], generar(c["sur"], c["oeste"], c["norte"],
                                            c["este"], c["mapa"], a.zoom)))

        print(f"\n{'─'*54}")
        print("Pega cada bloque en su capítulo de index.html, tal cual: son las")
        print("esquinas reales del recorte, no las que había puestas.\n")
        for cid, esq in hechos:
            print(f"  // {cid}")
            print(esquinas_para_pegar(*esq))
        print("\nMapa © colaboradores de OpenStreetMap. Cita la fuente si lo publicas.")
        return

    if None in (a.sur, a.oeste, a.norte, a.este):
        sys.exit("Dame los cuatro números (sur oeste norte este) o usa --capitulos.")

    esq = generar(a.sur, a.oeste, a.norte, a.este, a.salida or "mapa.jpg", a.zoom)
    print("\nPega esto tal cual en index.html:\n")
    print(esquinas_para_pegar(*esq))
    print("\nMapa © colaboradores de OpenStreetMap. Cita la fuente si lo publicas.")


if __name__ == "__main__":
    main()
