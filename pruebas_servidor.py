#!/usr/bin/env python3
"""
Pruebas del servidor. Sin red ni ficheros: SQLite en memoria, y un arranque
HTTP en un puerto libre para comprobar el enrutado de /api de punta a punta.

    python pruebas_servidor.py

Devuelve 0 si pasa todo, 1 si algo falla.

`python`, no `python3`: ver CLAUDE.md.
"""

import json
import unittest
import urllib.request
from contextlib import closing
from http.client import HTTPConnection

import servidor


def bd_memoria():
    c = servidor.sqlite3.connect(":memory:")
    c.row_factory = servidor.sqlite3.Row
    servidor.crear_tablas(c)
    return c


class Sesiones(unittest.TestCase):
    def setUp(self):
        self.c = bd_memoria()

    def tearDown(self):
        self.c.close()

    def test_crear_y_leer(self):
        sid = servidor.crear_sesion(self.c, "himilce")
        self.assertGreater(len(sid), 20)
        self.assertEqual(servidor.usuario_de_sesion(self.c, sid), "himilce")

    def test_sesiones_distintas(self):
        s1 = servidor.crear_sesion(self.c, "himilce")
        s2 = servidor.crear_sesion(self.c, "orian")
        self.assertNotEqual(s1, s2)

    def test_sid_desconocido_es_none(self):
        self.assertIsNone(servidor.usuario_de_sesion(self.c, "nohay"))
        self.assertIsNone(servidor.usuario_de_sesion(self.c, None))

    def test_borrar_invalida(self):
        sid = servidor.crear_sesion(self.c, "admin")
        servidor.borrar_sesion(self.c, sid)
        self.assertIsNone(servidor.usuario_de_sesion(self.c, sid))


class Contenido(unittest.TestCase):
    def setUp(self):
        self.c = bd_memoria()

    def tearDown(self):
        self.c.close()

    def test_publica_y_versiona(self):
        base = {"pueblo": "Cadavedo",
                "capitulos": [{"esquinas": {}, "estaciones": []}]}
        v1 = servidor.publicar_contenido(self.c, base)
        v2 = servidor.publicar_contenido(self.c, {**base, "pueblo": "Otro"})
        self.assertEqual(v1, 1)
        self.assertEqual(v2, 2)
        # Devuelve la última publicada, no la primera.
        self.assertEqual(servidor.contenido_actual(self.c)["pueblo"], "Otro")

    def test_sin_publicar_devuelve_none(self):
        self.assertIsNone(servidor.contenido_actual(self.c))

    def test_rechaza_contenido_invalido(self):
        # En v2 las 'esquinas' ya no se exigen (mapa vivo); sí una lista de
        # estaciones por capítulo.
        for malo in [None, {}, {"capitulos": []},
                     {"capitulos": [{"nombre": "x"}]}]:   # capítulo sin estaciones
            with self.assertRaises(ValueError):
                servidor.publicar_contenido(self.c, malo)


class Progreso(unittest.TestCase):
    def setUp(self):
        self.c = bd_memoria()
        self.t = "himilce"   # el progreso se indexa por usuario

    def tearDown(self):
        self.c.close()

    def test_vacio_por_defecto(self):
        p = servidor.leer_progreso(self.c, self.t)
        self.assertEqual(p["abiertas"], [])
        self.assertEqual(p["capturas"], [])
        self.assertEqual(p["rastro"], [])

    def test_merge_une_sin_duplicar(self):
        servidor.fusionar_progreso(self.c, self.t,
                                   {"abiertas": ["a", "b"], "capturas": ["x"]})
        servidor.fusionar_progreso(self.c, self.t,
                                   {"abiertas": ["b", "c"], "capturas": ["x", "y"]})
        p = servidor.leer_progreso(self.c, self.t)
        self.assertEqual(p["abiertas"], ["a", "b", "c"])
        self.assertEqual(p["capturas"], ["x", "y"])

    def test_merge_conserva_el_rastro_mas_largo(self):
        largo = [[43.5, -6.3], [43.6, -6.4], [43.7, -6.5]]
        servidor.fusionar_progreso(self.c, self.t, {"rastro": largo})
        # Un push posterior con menos pisadas no puede acortar el rastro.
        servidor.fusionar_progreso(self.c, self.t, {"rastro": [[43.5, -6.3]]})
        self.assertEqual(servidor.leer_progreso(self.c, self.t)["rastro"], largo)

    def test_merge_no_borra_al_sincronizar_vacio(self):
        servidor.fusionar_progreso(self.c, self.t, {"abiertas": ["a"]})
        servidor.fusionar_progreso(self.c, self.t, {})   # sync sin datos
        self.assertEqual(servidor.leer_progreso(self.c, self.t)["abiertas"], ["a"])

    def test_campos_basura_no_rompen(self):
        servidor.fusionar_progreso(self.c, self.t,
                                   {"abiertas": "no soy lista", "rastro": None})
        p = servidor.leer_progreso(self.c, self.t)
        self.assertEqual(p["abiertas"], [])
        self.assertEqual(p["rastro"], [])


class Estaciones(unittest.TestCase):
    def setUp(self):
        self.c = bd_memoria()

    def tearDown(self):
        self.c.close()

    def test_colocar_crea_y_actualiza(self):
        servidor.colocar_estacion(self.c, "k1", 43.5, -6.3)
        est = servidor.listar_estaciones(self.c)
        self.assertEqual(len(est), 1)
        self.assertEqual(est[0]["lat"], 43.5)
        # recolocar mueve la posición
        servidor.colocar_estacion(self.c, "k1", 43.6, -6.4)
        self.assertEqual(servidor.listar_estaciones(self.c)[0]["lat"], 43.6)

    def test_guardar_metadatos_no_borra_posicion(self):
        servidor.colocar_estacion(self.c, "k1", 43.5, -6.3)
        servidor.guardar_estacion(self.c, {"k": "k1", "nombre": "El faro"})
        e = servidor.listar_estaciones(self.c)[0]
        self.assertEqual(e["nombre"], "El faro")
        self.assertEqual(e["lat"], 43.5)   # la ubicación se conserva

    def test_contenido_solo_lleva_las_colocadas(self):
        servidor.guardar_estacion(self.c, {"k": "sin", "nombre": "sin colocar"})
        servidor.colocar_estacion(self.c, "con", 43.5, -6.3)
        est = servidor.contenido_para_cliente(self.c)["capitulos"][0]["estaciones"]
        self.assertEqual([e["k"] for e in est], ["con"])

    def test_borrar(self):
        servidor.colocar_estacion(self.c, "k1", 43.5, -6.3)
        servidor.borrar_estacion(self.c, "k1")
        self.assertEqual(servidor.listar_estaciones(self.c), [])

    def test_colocar_sin_coords_falla(self):
        with self.assertRaises(ValueError):
            servidor.colocar_estacion(self.c, "k1", None, None)

    def test_hallazgo_marca_y_lista(self):
        servidor.marcar_hallazgo(self.c, "himilce", "t1")
        servidor.marcar_hallazgo(self.c, "himilce", "t1")   # idempotente
        servidor.marcar_hallazgo(self.c, "orian", "t1")
        h = servidor.listar_hallazgos(self.c)
        self.assertEqual(len(h), 2)   # (himilce,t1) y (orian,t1)
        self.assertIn("t1", servidor.leer_progreso(self.c, "himilce")["abiertas"])


class HTTP(unittest.TestCase):
    """Arranque real en un puerto libre. Comprueba el enrutado de /api; usa la
    misma BD en fichero que el resto (el servidor no sabe de :memory:), así que
    trabaja sobre una copia temporal para no tocar la de verdad."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        cls._bd_original = servidor.BD
        servidor.BD = servidor.Path(cls.tmp.name)
        # Caché de teselas en un directorio temporal, no en el real del repo.
        cls.dir_cache = tempfile.mkdtemp(prefix="teselas_")
        cls._cache_original = servidor.CACHE_TESELAS
        servidor.CACHE_TESELAS = servidor.Path(cls.dir_cache)
        cls._pin_original = servidor.PIN_ADMIN
        servidor.PIN_ADMIN = "1234"     # PIN de admin para las pruebas
        cls.srv = servidor.Servidor(("127.0.0.1", 0), servidor.Handler)
        cls.puerto = cls.srv.server_address[1]
        import threading
        cls.hilo = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.hilo.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        servidor.BD = cls._bd_original
        servidor.CACHE_TESELAS = cls._cache_original
        servidor.PIN_ADMIN = cls._pin_original
        import os
        import shutil
        for suf in ("", "-wal", "-shm"):
            try:
                os.unlink(cls.tmp.name + suf)
            except OSError:
                pass
        shutil.rmtree(cls.dir_cache, ignore_errors=True)

    def pedir(self, metodo, ruta, cuerpo=None, cookie=None, origen="same-origin"):
        con = HTTPConnection("127.0.0.1", self.puerto, timeout=5)
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        cab = {}
        if datos:
            cab["Content-Type"] = "application/json"
        if origen is not None:        # imita el fetch de la página (mismo origen)
            cab["Sec-Fetch-Site"] = origen
        if cookie:
            cab["Cookie"] = cookie
        con.request(metodo, ruta, body=datos, headers=cab)
        r = con.getresponse()
        self.ultima_cookie = r.getheader("Set-Cookie")
        texto = r.read().decode()
        con.close()
        try:
            return r.status, (json.loads(texto) if texto else None)
        except json.JSONDecodeError:
            return r.status, texto   # respuesta no-JSON (el estático)

    def login(self, usuario, pin=None, origen="same-origin"):
        cuerpo = {"usuario": usuario}
        if pin is not None:
            cuerpo["pin"] = pin
        code, body = self.pedir("POST", "/api/login", cuerpo, origen=origen)
        cookie = self.ultima_cookie.split(";", 1)[0] if self.ultima_cookie else None
        return code, body, cookie

    def pedir_bin(self, ruta):
        """Como pedir(), pero para respuestas binarias: devuelve
        (status, content_type, bytes)."""
        con = HTTPConnection("127.0.0.1", self.puerto, timeout=5)
        con.request("GET", ruta)
        r = con.getresponse()
        cuerpo = r.read()
        ct = r.getheader("Content-Type")
        con.close()
        return r.status, ct, cuerpo

    def test_contenido_sin_estaciones(self):
        # /api/contenido siempre compone algo (metadatos + estaciones colocadas).
        code, r = self.pedir("GET", "/api/contenido")
        self.assertEqual(code, 200)
        self.assertEqual(r["capitulos"][0]["estaciones"], [])

    def test_login_crio_sin_pin(self):
        code, body, cookie = self.login("himilce")
        self.assertEqual(code, 200)
        self.assertEqual(body["usuario"], "himilce")
        self.assertTrue(cookie.startswith("__Host-sesion="))
        # /api/me con y sin cookie
        _, me = self.pedir("GET", "/api/me", cookie=cookie)
        self.assertEqual(me["usuario"], "himilce")
        _, me = self.pedir("GET", "/api/me")
        self.assertIsNone(me["usuario"])

    def test_login_usuario_desconocido(self):
        code, _, _ = self.login("intruso")
        self.assertEqual(code, 400)

    def test_admin_pin(self):
        self.assertEqual(self.login("admin", "1234")[0], 200)
        self.assertEqual(self.login("admin", "0000")[0], 403)   # PIN incorrecto
        self.assertEqual(self.login("admin")[0], 403)           # sin PIN

    def test_logout_invalida(self):
        _, _, cookie = self.login("orian")
        self.pedir("POST", "/api/logout", cookie=cookie)
        _, me = self.pedir("GET", "/api/me", cookie=cookie)
        self.assertIsNone(me["usuario"])

    def test_progreso_por_sesion(self):
        _, _, cookie = self.login("himilce")
        code, p = self.pedir("GET", "/api/progreso", cookie=cookie)
        self.assertEqual(code, 200)
        self.assertEqual(p["abiertas"], [])
        code, p = self.pedir("POST", "/api/progreso",
                             {"abiertas": ["a7f3c1"]}, cookie=cookie)
        self.assertEqual(code, 200)
        self.assertEqual(p["abiertas"], ["a7f3c1"])
        # sin cookie no hay sesión
        self.assertEqual(self.pedir("GET", "/api/progreso")[0], 401)

    def test_csrf_bloquea_escritura_de_otro_origen(self):
        _, _, cookie = self.login("himilce")
        # con cookie válida pero petición de otro sitio -> 403
        self.assertEqual(
            self.pedir("POST", "/api/progreso", {"abiertas": ["x"]},
                       cookie=cookie, origen="cross-site")[0], 403)
        # sin señal de origen -> también 403
        self.assertEqual(
            self.pedir("POST", "/api/progreso", {"abiertas": ["x"]},
                       cookie=cookie, origen=None)[0], 403)

    def test_contenido_via_http(self):
        contenido = {"pueblo": "Cadavedo",
                     "capitulos": [{"esquinas": {"norte": 1, "sur": 0,
                                                 "oeste": 0, "este": 1},
                                    "estaciones": []}]}
        with closing(servidor.conectar()) as c:
            servidor.publicar_contenido(c, contenido)
        code, r = self.pedir("GET", "/api/contenido")
        self.assertEqual(code, 200)
        self.assertEqual(r["pueblo"], "Cadavedo")

    def test_provision_de_estaciones(self):
        _, _, admin = self.login("admin", "1234")
        _, _, crio = self.login("himilce")
        # colocar (crea la estación con su GPS)
        code, r = self.pedir("POST", "/api/estacion/colocar",
                             {"k": "t1", "lat": 43.545, "lon": -6.389}, cookie=admin)
        self.assertEqual(code, 200)
        self.assertEqual(len(r["estaciones"]), 1)
        # aparece en el contenido del jugador, con sus coordenadas de campo
        _, cont = self.pedir("GET", "/api/contenido")
        est = cont["capitulos"][0]["estaciones"]
        self.assertEqual(est[0]["k"], "t1")
        self.assertEqual(est[0]["lat"], 43.545)
        # editar metadatos
        self.pedir("POST", "/api/estaciones",
                   {"k": "t1", "nombre": "El lavadero", "pista": "junto al río"},
                   cookie=admin)
        _, cont = self.pedir("GET", "/api/contenido")
        self.assertEqual(cont["capitulos"][0]["estaciones"][0]["nombre"], "El lavadero")
        # borrar
        self.pedir("POST", "/api/estacion/borrar", {"k": "t1"}, cookie=admin)
        _, r = self.pedir("GET", "/api/estaciones", cookie=admin)
        self.assertEqual(r["estaciones"], [])
        # un crío no puede colocar ni listar
        self.assertEqual(self.pedir("POST", "/api/estacion/colocar",
                         {"k": "x", "lat": 1, "lon": 1}, cookie=crio)[0], 403)
        self.assertEqual(self.pedir("GET", "/api/estaciones", cookie=crio)[0], 403)

    def test_encontrado_y_hallazgos(self):
        # usa 'orian' para no pisar el progreso de himilce de otros tests (la BD
        # es compartida en esta clase).
        _, _, ori = self.login("orian")
        _, _, admin = self.login("admin", "1234")
        code, _ = self.pedir("POST", "/api/encontrado", {"k": "h1"}, cookie=ori)
        self.assertEqual(code, 200)
        # el admin ve el hallazgo
        _, r = self.pedir("GET", "/api/hallazgos", cookie=admin)
        self.assertTrue(any(x["usuario"] == "orian" and x["k"] == "h1"
                            for x in r["hallazgos"]))
        # sin sesión no se marca; un crío no ve la lista (sólo admin)
        self.assertEqual(self.pedir("POST", "/api/encontrado", {"k": "x"})[0], 401)
        self.assertEqual(self.pedir("GET", "/api/hallazgos", cookie=ori)[0], 403)

    def test_sirve_el_estatico(self):
        code, _ = self.pedir("GET", "/index.html")
        self.assertEqual(code, 200)

    # ── proxy-caché de teselas ──
    def _mock_descarga(self, datos=None, error=None):
        """Sustituye descargar_tesela por un doble que cuenta llamadas."""
        llamadas = {"n": 0}
        original = servidor.descargar_tesela

        def falso(url):
            llamadas["n"] += 1
            if error:
                raise error
            return datos

        servidor.descargar_tesela = falso
        self.addCleanup(lambda: setattr(servidor, "descargar_tesela", original))
        return llamadas

    def test_tesela_rango_invalido(self):
        # z fuera de rango y coordenada fuera del mundo -> 404, sin descargar.
        ll = self._mock_descarga(datos=b"x")
        self.assertEqual(self.pedir_bin("/tiles/99/0/0.png")[0], 404)
        self.assertEqual(self.pedir_bin("/tiles/15/99999999/0.png")[0], 404)
        self.assertEqual(ll["n"], 0)

    def test_tesela_descarga_y_cachea(self):
        png = b"\x89PNG\r\n\x1a\nTESELA-DE-PRUEBA"
        ll = self._mock_descarga(datos=png)
        code, ct, cuerpo = self.pedir_bin("/tiles/15/16000/12000.png")
        self.assertEqual(code, 200)
        self.assertEqual(ct, "image/png")
        self.assertEqual(cuerpo, png)
        # Segunda petición: sale de disco, no vuelve a descargar.
        code2, _, cuerpo2 = self.pedir_bin("/tiles/15/16000/12000.png")
        self.assertEqual(code2, 200)
        self.assertEqual(cuerpo2, png)
        self.assertEqual(ll["n"], 1, "la segunda debería servirse de caché")

    def test_tesela_404_upstream_cachea_negativo(self):
        err = servidor.urllib.error.HTTPError(
            "u", 404, "Not Found", hdrs=None, fp=None)
        ll = self._mock_descarga(error=err)
        self.assertEqual(self.pedir_bin("/tiles/15/16001/12001.png")[0], 404)
        # Caché negativa: no se vuelve a pedir el mar/borde.
        self.assertEqual(self.pedir_bin("/tiles/15/16001/12001.png")[0], 404)
        self.assertEqual(ll["n"], 1)

    def test_tesela_ruta_no_numerica_no_sirve(self):
        # No casa con la regex de teselas: no debe servir nada raro (ni 200).
        ll = self._mock_descarga(datos=b"x")
        self.assertNotEqual(self.pedir_bin("/tiles/15/abc/1.png")[0], 200)
        self.assertEqual(ll["n"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
