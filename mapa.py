#!/usr/bin/env python3
"""
Prepara el mapa de la yincana.

Descarga las teselas de OpenStreetMap que cubren un recuadro, las cose en una
sola imagen, la recorta al recuadro exacto y te imprime el bloque `esquinas`
listo para pegar en index.html. La imagen y las coordenadas salen del mismo
cálculo, así que no pueden descuadrarse entre sí.

Uso:
    python3 mapa.py 43.5330 -5.6700 43.5400 -5.6600
    python3 mapa.py 43.5330 -5.6700 43.5400 -5.6600 --zoom 18

Los cuatro números son: sur oeste norte este (grados decimales).
Sácalos de openstreetmap.org: encuadra el pueblo, pestaña "Exportar", y ahí
tienes los cuatro límites del recuadro que estás viendo.

Requiere Pillow:  pip install pillow
"""

import argparse, io, math, sys, time, urllib.request
from PIL import Image

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


def main():
    p = argparse.ArgumentParser(description="Prepara mapa.jpg y sus esquinas.")
    p.add_argument("sur", type=float); p.add_argument("oeste", type=float)
    p.add_argument("norte", type=float); p.add_argument("este", type=float)
    p.add_argument("--zoom", type=int, default=None)
    p.add_argument("--salida", default="mapa.jpg")
    a = p.parse_args()

    sur, oeste = min(a.sur, a.norte), min(a.oeste, a.este)
    norte, este = max(a.sur, a.norte), max(a.oeste, a.este)
    z = a.zoom or elegir_zoom(sur, oeste, norte, este)

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

    recorte.save(a.salida, quality=90)

    R = 6371000.0
    def dist(la1, lo1, la2, lo2):
        dla, dlo = math.radians(la2 - la1), math.radians(lo2 - lo1)
        h = (math.sin(dla / 2) ** 2 + math.cos(math.radians(la1))
             * math.cos(math.radians(la2)) * math.sin(dlo / 2) ** 2)
        return 2 * R * math.asin(min(1, math.sqrt(h)))

    ancho = dist(lat_n, lon_o, lat_n, lon_e)
    alto  = dist(lat_n, lon_o, lat_s, lon_o)

    print(f"\nGuardado {a.salida} · {recorte.width}x{recorte.height} px")
    print(f"Cubre {ancho:.0f} m de ancho por {alto:.0f} m de alto "
          f"({ancho/recorte.width:.2f} m por píxel)\n")
    print("Pega esto tal cual en index.html:\n")
    print(f"  esquinas: {{ norte: {lat_n:.6f}, sur: {lat_s:.6f}, "
          f"oeste: {lon_o:.6f}, este: {lon_e:.6f} }},")
    print("\nMapa © colaboradores de OpenStreetMap. Cita la fuente si lo publicas.")


if __name__ == "__main__":
    main()
