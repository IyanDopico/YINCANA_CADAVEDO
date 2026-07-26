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
from http.client import HTTPConnection

import servidor


def bd_memoria():
    c = servidor.sqlite3.connect(":memory:")
    c.row_factory = servidor.sqlite3.Row
    servidor.crear_tablas(c)
    return c


class Cuentas(unittest.TestCase):
    def setUp(self):
        self.c = bd_memoria()

    def tearDown(self):
        self.c.close()

    def test_token_corto_y_unico(self):
        t1 = servidor.crear_cuenta(self.c, "Martina")
        t2 = servidor.crear_cuenta(self.c, "Nico")
        self.assertEqual(len(t1), 6)
        self.assertNotEqual(t1, t2)
        self.assertEqual(servidor.jugador(self.c, t1)["nombre"], "Martina")

    def test_nombre_vacio_cae_en_defecto(self):
        t = servidor.crear_cuenta(self.c, "   ")
        self.assertEqual(servidor.jugador(self.c, t)["nombre"], "Jugador")

    def test_token_desconocido_es_none(self):
        self.assertIsNone(servidor.jugador(self.c, "nohay0"))


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
        for malo in [None, {}, {"capitulos": []},
                     {"capitulos": [{"estaciones": []}]},          # sin esquinas
                     {"capitulos": [{"esquinas": {}}]}]:           # sin estaciones
            with self.assertRaises(ValueError):
                servidor.publicar_contenido(self.c, malo)


class Progreso(unittest.TestCase):
    def setUp(self):
        self.c = bd_memoria()
        self.t = servidor.crear_cuenta(self.c, "Martina")

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
        import os
        import shutil
        for suf in ("", "-wal", "-shm"):
            try:
                os.unlink(cls.tmp.name + suf)
            except OSError:
                pass
        shutil.rmtree(cls.dir_cache, ignore_errors=True)

    def pedir(self, metodo, ruta, cuerpo=None):
        con = HTTPConnection("127.0.0.1", self.puerto, timeout=5)
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        cabeceras = {"Content-Type": "application/json"} if datos else {}
        con.request(metodo, ruta, body=datos, headers=cabeceras)
        r = con.getresponse()
        texto = r.read().decode()
        con.close()
        try:
            return r.status, (json.loads(texto) if texto else None)
        except json.JSONDecodeError:
            return r.status, texto   # respuesta no-JSON (el estático)

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

    def test_contenido_sin_publicar_da_404(self):
        code, _ = self.pedir("GET", "/api/contenido")
        self.assertEqual(code, 404)

    def test_flujo_cuenta_progreso_contenido(self):
        # crear cuenta
        code, r = self.pedir("POST", "/api/cuenta", {"nombre": "Nico"})
        self.assertEqual(code, 200)
        token = r["token"]
        self.assertEqual(len(token), 6)

        # progreso arranca vacío
        code, p = self.pedir("GET", f"/api/progreso?u={token}")
        self.assertEqual(code, 200)
        self.assertEqual(p["abiertas"], [])

        # subir progreso y recuperarlo fusionado
        code, p = self.pedir("POST", f"/api/progreso?u={token}",
                             {"abiertas": ["a7f3c1"], "rastro": [[43.5, -6.3]]})
        self.assertEqual(code, 200)
        self.assertEqual(p["abiertas"], ["a7f3c1"])
        code, p = self.pedir("GET", f"/api/progreso?u={token}")
        self.assertEqual(p["abiertas"], ["a7f3c1"])

        # publicar contenido y leerlo
        contenido = {"pueblo": "Cadavedo",
                     "capitulos": [{"esquinas": {"norte": 1, "sur": 0,
                                                 "oeste": 0, "este": 1},
                                    "estaciones": []}]}
        from contextlib import closing
        with closing(servidor.conectar()) as c:
            servidor.publicar_contenido(c, contenido)
        code, r = self.pedir("GET", "/api/contenido")
        self.assertEqual(code, 200)
        self.assertEqual(r["pueblo"], "Cadavedo")

    def test_progreso_sin_token_da_400(self):
        code, _ = self.pedir("GET", "/api/progreso")
        self.assertEqual(code, 400)

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
