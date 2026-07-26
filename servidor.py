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
import http.server
import json
import secrets
import socketserver
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

RAIZ = Path(__file__).parent.resolve()
BD = RAIZ / "yincana.db"


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
        CREATE TABLE IF NOT EXISTS jugadores(
            token   TEXT PRIMARY KEY,
            nombre  TEXT,
            creado  REAL
        );
        CREATE TABLE IF NOT EXISTS progreso(
            token       TEXT PRIMARY KEY,
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


# ── Cuentas ───────────────────────────────────────────────────────────
def crear_cuenta(c, nombre):
    """Token corto al estilo de las claves NFC (6 hex). Va en la URL como ?u=."""
    nombre = (nombre or "").strip() or "Jugador"
    token = secrets.token_hex(3)
    c.execute("INSERT INTO jugadores(token, nombre, creado) VALUES(?,?,?)",
              (token, nombre, time.time()))
    c.commit()
    return token


def jugador(c, token):
    r = c.execute("SELECT token, nombre, creado FROM jugadores WHERE token=?",
                  (token,)).fetchone()
    return dict(r) if r else None


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


def leer_progreso(c, token):
    r = c.execute(
        "SELECT abiertas, capturas, rastro, actualizado FROM progreso WHERE token=?",
        (token,)).fetchone()
    if not r:
        return {"abiertas": [], "capturas": [], "rastro": [], "actualizado": 0}
    return {
        "abiertas": json.loads(r["abiertas"] or "[]"),
        "capturas": json.loads(r["capturas"] or "[]"),
        "rastro": json.loads(r["rastro"] or "[]"),
        "actualizado": r["actualizado"] or 0,
    }


def fusionar_progreso(c, token, entrante):
    """Merge no destructivo. Dos móviles con el mismo token no se pisan: se
    unen 'abiertas' y 'capturas', y del rastro se queda el más largo (el más
    completo para despejar la niebla). Nunca se borra progreso al sincronizar."""
    actual = leer_progreso(c, token)

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
        (token, json.dumps(abiertas), json.dumps(capturas),
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

    def _token(self):
        return (parse_qs(urlsplit(self.path).query).get("u") or [None])[0]

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

    def _json(self, obj, code=200):
        cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        # Mismo origen en producción (Caddy). El '*' deja que las pruebas y un
        # despliegue con la API en otro puerto sigan funcionando; no hay nada
        # secreto que proteger con CORS aquí, el token ya va en la URL.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    # ── enrutado ──
    def do_GET(self):
        ruta = urlsplit(self.path).path
        if ruta == "/api/contenido":
            with closing(conectar()) as c:
                obj = contenido_actual(c)
            return self._json(obj, 200) if obj else self._json(
                {"error": "sin contenido publicado"}, 404)
        if ruta == "/api/progreso":
            token = self._token()
            if not token:
                return self._json({"error": "falta ?u=<token>"}, 400)
            with closing(conectar()) as c:
                return self._json(leer_progreso(c, token))
        return super().do_GET()

    def do_POST(self):
        ruta = urlsplit(self.path).path
        if ruta == "/api/cuenta":
            nombre = (self._cuerpo() or {}).get("nombre")
            with closing(conectar()) as c:
                token = crear_cuenta(c, nombre)
            return self._json({"token": token})
        if ruta == "/api/progreso":
            token = self._token()
            if not token:
                return self._json({"error": "falta ?u=<token>"}, 400)
            with closing(conectar()) as c:
                if not jugador(c, token):
                    # Un token que nadie creó no debería aparecer, pero si llega
                    # (partida vieja, dedo curioso) lo guardamos igual: perder
                    # progreso es peor que tener una fila de más.
                    c.execute(
                        "INSERT OR IGNORE INTO jugadores(token,nombre,creado) VALUES(?,?,?)",
                        (token, "?", time.time()))
                    c.commit()
                return self._json(fusionar_progreso(c, token, self._cuerpo()))
        self.send_error(404)

    def do_OPTIONS(self):   # preflight de CORS por si la API va en otro origen
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


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


def cmd_cuenta(nombre, base):
    with conectar() as c:
        token = crear_cuenta(c, nombre)
    print(f"Jugador «{nombre}» creado.")
    print(f"  token: {token}")
    print(f"  URL:   {base.rstrip('/')}/?u={token}")


def cmd_jugadores():
    with conectar() as c:
        js = c.execute(
            "SELECT token, nombre, creado FROM jugadores ORDER BY creado").fetchall()
        if not js:
            print("No hay jugadores todavía. Crea uno con: "
                  "python servidor.py cuenta \"Nombre\"")
            return
        for j in js:
            p = leer_progreso(c, j["token"])
            print(f"  {j['token']}  {j['nombre']:<16}  "
                  f"{len(p['abiertas'])} estaciones, {len(p['capturas'])} spawns, "
                  f"{len(p['rastro'])} pisadas")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Servidor de la yincana")
    sub = ap.add_subparsers(dest="orden")

    p_serv = sub.add_parser("servir", help="arranca el servidor (por defecto)")
    p_serv.add_argument("--puerto", type=int, default=8000)

    p_pub = sub.add_parser("publicar", help="sube una versión de contenido")
    p_pub.add_argument("archivo")

    p_cta = sub.add_parser("cuenta", help="crea un jugador")
    p_cta.add_argument("nombre")
    p_cta.add_argument("--base", default="http://localhost:8000",
                       help="origen para componer la URL del jugador")

    sub.add_parser("jugadores", help="lista jugadores y su avance")

    # Sin subcomando, o con --puerto suelto, arranca el servidor.
    ap.add_argument("--puerto", type=int, default=8000,
                    help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.orden == "publicar":
        return cmd_publicar(args.archivo)
    if args.orden == "cuenta":
        return cmd_cuenta(args.nombre, args.base)
    if args.orden == "jugadores":
        return cmd_jugadores()
    servir(getattr(args, "puerto", 8000))


if __name__ == "__main__":
    main()
