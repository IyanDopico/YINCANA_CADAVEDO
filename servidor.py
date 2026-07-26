#!/usr/bin/env python3
"""
Servidor de la yincana: cuentas, progreso y contenido dinámico.

Sirve también los ficheros estáticos, así que con esto solo ya tienes el juego
entero en un origen (útil para probar en local sin Caddy). En producción va
Caddy delante para el HTTPS, que la geolocalización lo exige — ver Caddyfile.

La regla de oro no cambia: el juego tiene que poder jugarse sin este servidor.
El cliente guarda todo en localStorage y trae de aquí lo que haya cuando hay
cobertura; sin señal tira de su copia y del CONFIG integrado. Este servidor es
la fuente que *actualiza*, no de la que se *depende*.

    python servidor.py                          # arranca en :8000
    python servidor.py --puerto 9000
    python servidor.py publicar contenido.json  # sube una versión de contenido
    python servidor.py cuenta "Martina"         # crea un jugador, imprime su URL
    python servidor.py jugadores                # lista los jugadores y su avance

`python`, no `python3`: ver CLAUDE.md.
"""

import argparse
import http.cookies
import http.server
import json
import os
import re
import secrets
import socketserver
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

RAIZ = Path(__file__).parent.resolve()
BD = RAIZ / "yincana.db"

# ── Usuarios y sesiones ─────────────────────────────────────────────────
# Tres usuarios fijos, sin registro. Los críos entran sólo con su botón; admin
# (Iyán) con un PIN que se pone en el entorno (YINCANA_PIN en el systemd, nunca
# en git). Login persistente por cookie de sesión.
USUARIOS = ("admin", "himilce", "orian")
PIN_ADMIN = os.environ.get("YINCANA_PIN", "")
ORIGEN = os.environ.get("YINCANA_ORIGEN", "https://yincana.iyando.qzz.io")
COOKIE = "__Host-sesion"     # prefijo __Host-: exige Secure + Path=/ y sin Domain
DIAS_SESION = 180

# ── Proxy-caché de teselas del mapa ─────────────────────────────────────
# El mapa vivo tira de teselas de OSM, pero el cliente sólo habla con esta
# máquina: las servimos desde aquí y las cacheamos en disco. La política de OSM
# obliga a un User-Agent identificable (el que pone urllib por defecto está
# bloqueado, así que fijarlo NO es opcional) y a mostrar la atribución en el
# mapa. Nada de descargas masivas: la caché se calienta paseando la vista.
CACHE_TESELAS = RAIZ / "cache_teselas"
TESELAS_UPSTREAM = os.environ.get(
    "YINCANA_TESELAS", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
TESELAS_UA = ("YincanaCadavedo/2.0 "
              "(+https://yincana.iyando.qzz.io; iyan.dopico@gmail.com)")
_TESELA_RE = re.compile(r"^/tiles/(\d+)/(\d+)/(\d+)\.png$")
_teselas_sem = threading.Semaphore(2)   # tope de descargas simultáneas a upstream


def descargar_tesela(url):
    """Baja una tesela de upstream. Aislada para poder sustituirla en pruebas."""
    req = urllib.request.Request(url, headers={"User-Agent": TESELAS_UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()


# ══════════════════════════════════════════════════════════════════════
# 1 · BASE DE DATOS
# Tres tablas y ninguna dependencia: sqlite3 viene con Python. Las funciones
# de dominio reciben la conexión para poder probarlas contra una BD en memoria.
# ══════════════════════════════════════════════════════════════════════
def conectar(bd=None):
    # Se lee BD en tiempo de llamada, no como valor por defecto: si se fijara
    # `bd=BD` en la firma, quedaría clavado al import y reasignar servidor.BD
    # (las pruebas lo hacen para no tocar la BD de verdad) no tendría efecto.
    if bd is None:
        bd = BD
    c = sqlite3.connect(bd)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")   # varios lectores + un escritor
    crear_tablas(c)
    return c


def crear_tablas(c):
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS sesiones(
            id      TEXT PRIMARY KEY,   -- token aleatorio de 256 bits
            usuario TEXT NOT NULL,      -- 'admin' | 'himilce' | 'orian'
            creada  REAL
        );
        CREATE TABLE IF NOT EXISTS progreso(
            token       TEXT PRIMARY KEY,  -- clave del jugador: en v2 es el usuario
            abiertas    TEXT,   -- JSON: claves de estación tocadas
            capturas    TEXT,   -- JSON: claves de spawn capturadas
            rastro      TEXT,   -- JSON: lista de [lat, lon]
            actualizado REAL
        );
        CREATE TABLE IF NOT EXISTS contenido(
            version     INTEGER PRIMARY KEY AUTOINCREMENT,
            json        TEXT,
            publicado   REAL
        );
        """
    )
    c.commit()


# ── Sesiones ──────────────────────────────────────────────────────────
def crear_sesion(c, usuario):
    sid = secrets.token_urlsafe(32)
    c.execute("INSERT INTO sesiones(id, usuario, creada) VALUES(?,?,?)",
              (sid, usuario, time.time()))
    c.commit()
    return sid


def usuario_de_sesion(c, sid):
    if not sid:
        return None
    r = c.execute("SELECT usuario FROM sesiones WHERE id=?", (sid,)).fetchone()
    return r["usuario"] if r else None


def borrar_sesion(c, sid):
    if sid:
        c.execute("DELETE FROM sesiones WHERE id=?", (sid,))
        c.commit()


def _cookie_sesion(sid):
    return (f"{COOKIE}={sid}; Max-Age={DIAS_SESION*86400}; Path=/; "
            "HttpOnly; Secure; SameSite=Lax")


def _cookie_fuera():
    return f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax"


# ── Contenido ─────────────────────────────────────────────────────────
def validar_contenido(obj):
    """Lo mínimo para que el cliente no se quede sin mapa. El resto lo sanea el
    propio cliente antes de tocar nada (sanearContenido en index.html)."""
    if not isinstance(obj, dict):
        raise ValueError("el contenido tiene que ser un objeto JSON")
    caps = obj.get("capitulos")
    if not isinstance(caps, list) or not caps:
        raise ValueError("el contenido necesita una lista 'capitulos' no vacía")
    for i, cap in enumerate(caps):
        if not isinstance(cap, dict) or "esquinas" not in cap:
            raise ValueError(f"el capítulo {i} no tiene 'esquinas'")
        if not isinstance(cap.get("estaciones"), list):
            raise ValueError(f"el capítulo {i} no tiene lista 'estaciones'")
    return obj


def publicar_contenido(c, obj):
    validar_contenido(obj)
    c.execute("INSERT INTO contenido(json, publicado) VALUES(?,?)",
              (json.dumps(obj, ensure_ascii=False), time.time()))
    c.commit()
    return c.execute("SELECT MAX(version) AS v FROM contenido").fetchone()["v"]


def contenido_actual(c):
    r = c.execute(
        "SELECT json FROM contenido ORDER BY version DESC LIMIT 1").fetchone()
    return json.loads(r["json"]) if r else None


# ── Progreso ──────────────────────────────────────────────────────────
def _lista(x):
    return x if isinstance(x, list) else []


def leer_progreso(c, usuario):
    r = c.execute(
        "SELECT abiertas, capturas, rastro, actualizado FROM progreso WHERE token=?",
        (usuario,)).fetchone()
    if not r:
        return {"abiertas": [], "capturas": [], "rastro": [], "actualizado": 0}
    return {
        "abiertas": json.loads(r["abiertas"] or "[]"),
        "capturas": json.loads(r["capturas"] or "[]"),
        "rastro": json.loads(r["rastro"] or "[]"),
        "actualizado": r["actualizado"] or 0,
    }


def fusionar_progreso(c, usuario, entrante):
    """Merge no destructivo. Dos móviles del mismo usuario no se pisan: se unen
    'abiertas' y 'capturas', y del rastro se queda el más largo (el más completo
    para despejar la niebla). Nunca se borra progreso al sincronizar."""
    actual = leer_progreso(c, usuario)

    def union(a, b):
        return list(dict.fromkeys(_lista(a) + _lista(b)))

    abiertas = union(actual["abiertas"], entrante.get("abiertas"))
    capturas = union(actual["capturas"], entrante.get("capturas"))

    r_ent = _lista(entrante.get("rastro"))
    rastro = r_ent if len(r_ent) >= len(actual["rastro"]) else actual["rastro"]

    c.execute(
        """INSERT INTO progreso(token, abiertas, capturas, rastro, actualizado)
           VALUES(?,?,?,?,?)
           ON CONFLICT(token) DO UPDATE SET
             abiertas=excluded.abiertas, capturas=excluded.capturas,
             rastro=excluded.rastro,     actualizado=excluded.actualizado""",
        (usuario, json.dumps(abiertas), json.dumps(capturas),
         json.dumps(rastro), time.time()))
    c.commit()
    return {"abiertas": abiertas, "capturas": capturas, "rastro": rastro}


# ══════════════════════════════════════════════════════════════════════
# 2 · HTTP
# Extiende el servidor de ficheros estático y le añade /api. Así un solo
# `python servidor.py` da el juego entero en un origen.
# ══════════════════════════════════════════════════════════════════════
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(RAIZ), **k)

    def log_message(self, *a):
        pass   # el 404 del mapa sin generar ensucia la salida; igual que en pruebas.py

    # ── utilidades ──
    def _cuerpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}

    def _sid(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            ck = http.cookies.SimpleCookie(raw)
        except http.cookies.CookieError:
            return None
        m = ck.get(COOKIE)
        return m.value if m else None

    def _usuario(self):
        sid = self._sid()
        if not sid:
            return None
        with closing(conectar()) as c:
            return usuario_de_sesion(c, sid)

    def _origen_ok(self):
        """Defensa CSRF para las escrituras. La cookie ya es SameSite=Lax (no
        viaja en POST de otro sitio), pero esto es cinturón y tirantes: se exige
        que la petición venga del mismo origen."""
        sfs = self.headers.get("Sec-Fetch-Site")
        if sfs is not None:
            return sfs in ("same-origin", "none")
        origin = self.headers.get("Origin")
        if origin is not None:
            return origin == ORIGEN
        return False   # sin ninguna señal de origen, no se fía

    def end_headers(self):
        # Detrás de Cloudflare, el edge cachea el estático por extensión. Con el
        # sw.js eso es veneno: seguirías sirviendo un service worker viejo aunque
        # subas VERSION —el "te vuelves loco" del CLAUDE.md, pero en el edge—.
        # Comprobado en vivo: `no-cache` NO basta (Cloudflare lo cachea y
        # revalida), pero `no-store` sí lo deja fuera de la caché (igual que
        # /api). Por eso el sw.js va con no-store; el html con no-cache basta
        # (Cloudflare no cachea html por defecto).
        ruta = urlsplit(self.path).path
        if ruta.endswith("sw.js"):
            self.send_header("Cache-Control", "no-store")
        elif ruta.endswith(".html") or ruta == "/":
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, obj, code=200, cookies=()):
        cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        # Sin CORS: en la v2 todo es mismo origen (tras Cloudflare), y un
        # 'Access-Control-Allow-Origin: *' sería incompatible con cookies de
        # credenciales. La autenticación va por cookie de sesión.
        for ck in cookies:
            self.send_header("Set-Cookie", ck)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    # ── teselas ──
    def _tesela(self, z, x, y):
        # Rango razonable + coordenadas dentro del mundo. Esto acota zooms
        # absurdos y, como la ruta se arma sólo con los enteros validados, cierra
        # cualquier path traversal.
        if not (12 <= z <= 19 and 0 <= x < (1 << z) and 0 <= y < (1 << z)):
            return self.send_error(404)
        destino = CACHE_TESELAS / str(z) / str(x) / f"{y}.png"
        neg = destino.parent / f"{y}.png.404"     # caché negativa (mar/borde)
        if destino.exists():
            return self._enviar_tesela(destino.read_bytes())
        if neg.exists():
            return self.send_error(404)
        url = TESELAS_UPSTREAM.format(z=z, x=x, y=y)
        try:
            with _teselas_sem:
                if destino.exists():   # otra petición la trajo mientras esperábamos
                    return self._enviar_tesela(destino.read_bytes())
                datos = descargar_tesela(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                neg.parent.mkdir(parents=True, exist_ok=True)
                neg.write_bytes(b"")
                return self.send_error(404)
            return self.send_error(502)
        except Exception:
            return self.send_error(504)
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.parent / f"{y}.png.{secrets.token_hex(4)}.tmp"
        tmp.write_bytes(datos)
        os.replace(tmp, destino)   # escritura atómica: nada de teselas a medias
        self._enviar_tesela(datos)

    def _enviar_tesela(self, datos):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(datos)

    # ── enrutado ──
    def do_GET(self):
        ruta = urlsplit(self.path).path
        m = _TESELA_RE.match(ruta)
        if m:
            return self._tesela(int(m[1]), int(m[2]), int(m[3]))
        if ruta == "/api/contenido":
            with closing(conectar()) as c:
                obj = contenido_actual(c)
            return self._json(obj, 200) if obj else self._json(
                {"error": "sin contenido publicado"}, 404)
        if ruta == "/api/me":
            return self._json({"usuario": self._usuario()})
        if ruta == "/api/progreso":
            usuario = self._usuario()
            if not usuario:
                return self._json({"error": "sin sesión"}, 401)
            with closing(conectar()) as c:
                return self._json(leer_progreso(c, usuario))
        return super().do_GET()

    def do_POST(self):
        ruta = urlsplit(self.path).path
        if ruta == "/api/login":
            if not self._origen_ok():
                return self._json({"error": "origen no permitido"}, 403)
            d = self._cuerpo() or {}
            u = str(d.get("usuario") or "").strip().lower()
            if u not in USUARIOS:
                return self._json({"error": "usuario desconocido"}, 400)
            if u == "admin":
                if not PIN_ADMIN:
                    return self._json(
                        {"error": "PIN de admin sin configurar (YINCANA_PIN)"}, 403)
                if not secrets.compare_digest(str(d.get("pin") or ""), PIN_ADMIN):
                    return self._json({"error": "PIN incorrecto"}, 403)
            with closing(conectar()) as c:
                sid = crear_sesion(c, u)
            return self._json({"usuario": u}, cookies=[_cookie_sesion(sid)])

        if ruta == "/api/logout":
            with closing(conectar()) as c:
                borrar_sesion(c, self._sid())
            return self._json({"ok": True}, cookies=[_cookie_fuera()])

        if ruta == "/api/progreso":
            if not self._origen_ok():
                return self._json({"error": "origen no permitido"}, 403)
            usuario = self._usuario()
            if not usuario:
                return self._json({"error": "sin sesión"}, 401)
            with closing(conectar()) as c:
                return self._json(fusionar_progreso(c, usuario, self._cuerpo()))

        self.send_error(404)


class Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def servir(puerto=8000):
    with closing(conectar()):
        pass   # crea la BD y las tablas antes de aceptar peticiones
    s = Servidor(("0.0.0.0", puerto), Handler)
    print(f"Yincana en http://0.0.0.0:{puerto}  (Ctrl-C para parar)")
    print(f"Base de datos: {BD}")
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        print("\nParado.")
    finally:
        s.server_close()


# ══════════════════════════════════════════════════════════════════════
# 3 · LÍNEA DE ÓRDENES
# ══════════════════════════════════════════════════════════════════════
def cmd_publicar(ruta):
    obj = json.loads(Path(ruta).read_text(encoding="utf-8"))
    with conectar() as c:
        v = publicar_contenido(c, obj)
    caps = obj.get("capitulos", [])
    est = sum(len(x.get("estaciones", [])) for x in caps)
    spw = sum(len(x.get("spawns", [])) for x in caps)
    print(f"Publicada la versión {v}: {len(caps)} capítulos, "
          f"{est} estaciones, {spw} spawns.")


def cmd_jugadores():
    with closing(conectar()) as c:
        print(f"PIN de admin: {'configurado' if PIN_ADMIN else 'SIN CONFIGURAR (YINCANA_PIN)'}")
        for u in USUARIOS:
            p = leer_progreso(c, u)
            print(f"  {u:<10} {len(p['abiertas'])} estaciones, "
                  f"{len(p['capturas'])} spawns, {len(p['rastro'])} pisadas")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Servidor de la yincana")
    sub = ap.add_subparsers(dest="orden")

    p_serv = sub.add_parser("servir", help="arranca el servidor (por defecto)")
    p_serv.add_argument("--puerto", type=int, default=8000)

    p_pub = sub.add_parser("publicar", help="sube una versión de contenido")
    p_pub.add_argument("archivo")

    sub.add_parser("jugadores", help="lista los usuarios y su avance")

    # Sin subcomando, o con --puerto suelto, arranca el servidor.
    ap.add_argument("--puerto", type=int, default=8000,
                    help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.orden == "publicar":
        return cmd_publicar(args.archivo)
    if args.orden == "jugadores":
        return cmd_jugadores()
    servir(getattr(args, "puerto", 8000))


if __name__ == "__main__":
    main()
