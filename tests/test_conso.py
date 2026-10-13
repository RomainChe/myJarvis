"""Consommation de la prise du PC : intégration W -> Wh par jour, trous, bornes, outil `conso_pc`, route, intentions."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import jarvis.tools.conso as conso_tool
from jarvis.core import conso
from jarvis.core.router import Router
from jarvis.core.tools import REGISTRY, Level
from tests.test_server import ServerBase

NOON = datetime(2026, 10, 13, 12, 0, 0)


class SampleTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db, self.cfg = self.dir / "conso.db", self.dir / "conso.json"
        conso._last = None

    def feed(self, points, start=NOON):
        for sec, watts in points:
            conso.sample(watts, start + timedelta(seconds=sec), self.db)

    def test_puissance_constante_une_heure(self):
        self.feed([(m * 60, 1000) for m in range(61)])  # 1 000 W pendant 60 min = 1 kWh
        s = conso.snapshot(self.db, NOON + timedelta(hours=1), self.cfg)["periods"]["jour"]
        self.assertEqual((s["kwh"], s["hours"], s["partial"]), (1.0, 1.0, True))  # 1 h mesurée sur 13 h écoulées

    def test_trapeze_entre_deux_echantillons(self):
        self.feed([(0, 0), (60, 6000 / 2)])  # 0 -> 3 000 W en 60 s : moyenne 1 500 W = 25 Wh
        s = conso.snapshot(self.db, NOON + timedelta(minutes=1), self.cfg)["periods"]["jour"]
        self.assertEqual(s["kwh"], 0.025)

    def test_trou_non_compte_et_mesure_illisible(self):
        self.feed([(0, 3000), (60, 3000)])  # 50 Wh = 0,05 kWh
        self.feed([(60 + 600, 3000)])  # Core éteint 10 min : l'intervalle n'est pas compté
        conso.sample(float("inf"), NOON + timedelta(seconds=720), self.db)  # prise illisible : rupture
        self.feed([(780, 3000)])  # premier échantillon après la rupture : rien
        s = conso.snapshot(self.db, NOON + timedelta(minutes=14), self.cfg)
        self.assertEqual(s["periods"]["jour"]["kwh"], 0.05)

    def test_valeur_absurde_ignoree(self):
        self.feed([(0, 100), (60, 999_999), (120, -5), (180, 100)])
        self.assertFalse(self.db.exists())

    def test_fenetres_et_periode_precedente(self):
        for n, w in ((0, 200), (1, 100), (9, 50)):  # 2 h par jour, à puissance constante
            conso._last = None
            for sec in range(0, 7201, 60):
                conso.sample(w, NOON - timedelta(days=n) + timedelta(seconds=sec), self.db)
        s = conso.snapshot(self.db, NOON + timedelta(hours=2), self.cfg)["periods"]
        self.assertAlmostEqual(s["jour"]["kwh"], 0.4, places=3)
        self.assertAlmostEqual(s["jour"]["prev_kwh"], 0.2, places=3)
        self.assertAlmostEqual(s["semaine"]["kwh"], 0.6, places=3)
        self.assertAlmostEqual(s["mois"]["kwh"], 0.7, places=3)
        self.assertAlmostEqual(s["semaine"]["prev_kwh"], 0.1, places=3)  # J-9 tombe dans les 7 jours d'avant
        self.assertIsNone(s["mois"]["prev_kwh"])  # rien entre J-59 et J-30

    def test_donnee_indisponible_sans_base(self):
        s = conso.snapshot(self.dir / "absente.db", NOON, self.cfg)
        self.assertFalse(s["configured"])
        self.assertTrue(all(p["kwh"] is None for p in s["periods"].values()))

    def test_base_sans_table(self):
        sqlite3.connect(self.db).close()
        self.assertFalse(conso.snapshot(self.db, NOON, self.cfg)["configured"])

    def test_retention_bornee(self):
        self.feed([(0, 100), (60, 100)], start=NOON - timedelta(days=conso.KEEP_DAYS + 5))
        conso._last = None
        self.feed([(0, 100), (60, 100)])
        rows = sqlite3.connect(self.db).execute("SELECT day FROM pc_energy").fetchall()
        self.assertEqual(rows, [(NOON.date().isoformat(),)])

    def test_prix_borne_et_euros(self):
        self.assertIsNone(conso.load_price(self.cfg))
        for bad in (0, -1, 5.01, float("nan"), "0.2"):
            with self.assertRaises(ValueError):
                conso.save_price(bad, self.cfg)
        conso.save_price(0.25, self.cfg)
        self.feed([(m * 60, 1000) for m in range(61)])  # 1 kWh
        s = conso.snapshot(self.db, NOON + timedelta(hours=1), self.cfg)
        self.assertEqual((s["price_kwh"], s["periods"]["jour"]["eur"]), (0.25, 0.25))

    def test_sans_prix_pas_de_montant(self):
        self.feed([(m * 60, 1000) for m in range(61)])
        self.assertIsNone(conso.snapshot(self.db, NOON + timedelta(hours=1), self.cfg)["periods"]["jour"]["eur"])

    def test_prix_illisible_ignore(self):
        self.cfg.write_text('{"price_kwh": "beaucoup"}', encoding="utf-8")
        self.assertIsNone(conso.load_price(self.cfg))
        self.cfg.write_text("{{", encoding="utf-8")
        self.assertIsNone(conso.load_price(self.cfg))


class ToolTest(unittest.TestCase):
    def snap(self, **period):
        base = {"kwh": 1.5, "eur": 0.38, "prev_kwh": 2.0, "hours": 12.0, "partial": False} | period
        return {"periods": {"jour": base, "semaine": base, "mois": base}}

    def test_niveau_n0(self):
        self.assertEqual(REGISTRY["conso_pc"].level, Level.N0)

    def test_resume_nominal(self):
        out = conso_tool.summary(self.snap(), "jour")
        self.assertEqual(out, "Le PC a consommé 1,50 kWh aujourd'hui (environ 0,38 €), contre 2,00 kWh hier.")

    def test_sans_prix_ni_precedent_et_partiel(self):
        out = conso_tool.summary(self.snap(eur=None, prev_kwh=None, partial=True, hours=3.0), "semaine")
        self.assertNotIn("€", out)
        self.assertIn("Mesuré sur 3.0 h seulement", out)

    def test_source_indisponible(self):
        self.assertIn("donnée indisponible", conso_tool.summary(self.snap(kwh=None), "mois"))

    def test_periode_invalide(self):
        with self.assertRaises(ValueError):
            REGISTRY["conso_pc"].run(periode="annee")

    def test_alias_aujourdhui(self):
        with mock.patch.object(conso, "snapshot", return_value=self.snap()):
            self.assertIn("aujourd'hui", REGISTRY["conso_pc"].run(periode="Aujourd'hui"))


class RouterTest(unittest.TestCase):
    def test_intentions_sans_llm(self):
        r = Router()
        for text, periode in (("combien consomme le pc", "jour"), ("Jarvis, combien le PC a consommé aujourd'hui ?", "jour"),
                              ("la consommation du pc cette semaine", "semaine"), ("combien a consommé le pc ce mois-ci", "mois")):
            self.assertEqual(r.route(text), ("conso_pc", {"periode": periode}), text)


class RouteTest(ServerBase):
    def setUp(self):
        super().setUp()
        tmp = Path(tempfile.mkdtemp())  # jamais le ~/.jarvis du propriétaire
        for name, value in (("CONFIG", tmp / "conso.json"), ("DB", tmp / "conso.db")):
            patcher = mock.patch.object(conso, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_authentification_et_tarif(self):
        self.assertEqual(self.call("GET", "/api/conso")[0], 401)
        self.assertEqual(self.call("PUT", "/api/conso/tarif", {"price_kwh": 0.2})[0], 401)
        _, token = self.enroll()
        status, body, _ = self.call("GET", "/api/conso", token=token)
        self.assertEqual(status, 200)
        self.assertIsNone(body["periods"]["jour"]["kwh"])  # aucune mesure : indisponible, pas zéro
        for bad in (0, -1, 9, "x"):
            self.assertEqual(self.call("PUT", "/api/conso/tarif", {"price_kwh": bad}, token=token)[0], 422, bad)
        status, body, _ = self.call("PUT", "/api/conso/tarif", {"price_kwh": 0.2516}, token=token)
        self.assertEqual((status, body), (200, {"price_kwh": 0.2516}))
        self.assertEqual(self.call("GET", "/api/conso", token=token)[1]["price_kwh"], 0.2516)


if __name__ == "__main__":
    unittest.main()
