"""Bandeau d'état (météo, réseau) et encart Système : configuration locale, cache, pannes sans erreur à l'écran."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import dashboard as d
from tests.test_server import ServerBase


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def make(config, weather=lambda lat, lon: {"temp_c": 12.0, "sky": "Nuageux"}, ping=lambda: 20, clock=None):
    return d.Dashboard(lambda: {"cpu_percent": 5}, config=lambda: config, weather=weather, ping=ping, clock=clock or Clock())


class DashboardTest(unittest.TestCase):
    def test_nominal(self):
        snap = make({"city": "Lille", "lat": 50.6, "lon": 3.0}).snapshot()
        self.assertEqual((snap["location"], snap["weather"]["temp_c"], snap["network"]["quality"]), ("Lille", 12.0, "Excellente"))
        self.assertEqual(snap["system"], {"cpu_percent": 5})

    def test_uptime_entier_positif_ou_absent(self):
        up = make(None).snapshot()["uptime_s"]
        self.assertTrue(up is None or (isinstance(up, int) and up >= 0))

    def test_sans_config_pas_de_meteo_ni_d_appel(self):
        calls = []
        snap = make(None, weather=lambda *a: calls.append(a)).snapshot()
        self.assertEqual((snap["location"], snap["weather"], calls), (None, None, []))

    def test_meteo_en_panne_ne_casse_pas_et_reseau_coupe(self):
        def boom(lat, lon):
            raise OSError
        snap = make({"city": "Lille", "lat": 50.6, "lon": 3.0}, weather=boom, ping=lambda: None).snapshot()
        self.assertEqual((snap["weather"], snap["network"]), (None, {"ms": None, "quality": "Hors ligne"}))

    def test_echec_meteo_mis_en_cache_60_s(self):
        calls, clock = [], Clock()

        def boom(lat, lon):
            calls.append(1)
            raise OSError
        dash = make({"city": "Lille", "lat": 50.6, "lon": 3.0}, weather=boom, clock=clock)
        dash.snapshot()
        clock.t = 30
        dash.snapshot()
        self.assertEqual(len(calls), 1)
        clock.t = 61
        dash.snapshot()
        self.assertEqual(len(calls), 2)

    def test_temperature_nan_ou_hors_bornes_rejetee(self):
        for bad in ("NaN", "Infinity", "900"):
            body = ('{"current": {"temperature_2m": %s, "weather_code": 0}}' % bad).encode()
            resp = mock.MagicMock()
            resp.__enter__.return_value.read.return_value = body
            with mock.patch("urllib.request.urlopen", return_value=resp):
                with self.assertRaises(ValueError):
                    d.fetch_weather(50.6, 3.0)

    def test_cache_meteo_15_min(self):
        calls, clock = [], Clock()
        dash = make({"city": "Lille", "lat": 50.6, "lon": 3.0}, weather=lambda *a: calls.append(a) or {"temp_c": 1.0, "sky": "x"}, clock=clock)
        dash.snapshot()
        clock.t = 600
        dash.snapshot()
        self.assertEqual(len(calls), 1)
        clock.t = 901
        dash.snapshot()
        self.assertEqual(len(calls), 2)

    def test_config_invalide_refusee(self):
        tmp = Path(tempfile.mkdtemp())
        for name, text in (("a.json", "pas du json"), ("b.json", json.dumps({"city": "X", "lat": 99, "lon": 0})), ("c.json", "{}")):
            (tmp / name).write_text(text)
            self.assertIsNone(d.load_config(tmp / name))
        (tmp / "ok.json").write_text(json.dumps({"city": "Lille", "lat": 50.6, "lon": 3.0}))
        self.assertEqual(d.load_config(tmp / "ok.json")["city"], "Lille")
        self.assertIsNone(d.load_config(tmp / "absent.json"))

    def test_ciel(self):
        self.assertEqual((d.sky(0), d.sky(61), d.sky(95)), ("Dégagé", "Pluie", "Orage"))


class DashboardRouteTest(ServerBase):
    def test_authentification_exigee_et_forme(self):
        self.assertEqual(self.call("GET", "/api/dashboard")[0], 401)
        _, token = self.enroll()
        status, body, _ = self.call("GET", "/api/dashboard", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"location", "weather", "network", "system", "uptime_s"})


if __name__ == "__main__":
    unittest.main()
