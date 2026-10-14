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

    def test_periode_precedente_quasi_vide_signalee(self):  # BUG-CO-01
        conso._last = None
        for sec in range(0, 7201, 60):
            conso.sample(100, NOON - timedelta(days=8) + timedelta(seconds=sec), self.db)  # 2 h seulement, il y a 8 jours
        self.feed([(0, 100), (60, 100)])  # une mesure aujourd'hui : la fenêtre courante existe
        s = conso.snapshot(self.db, NOON, self.cfg)["periods"]["semaine"]
        self.assertTrue(s["prev_partial"])
        self.assertEqual(s["prev_hours"], 2.0)

    def test_prix_booleen_refuse(self):  # BUG-CO-04
        self.cfg.write_text('{"price_kwh": true}', encoding="utf-8")
        self.assertIsNone(conso.load_price(self.cfg))

    def test_donnee_indisponible_sans_base(self):
        s = conso.snapshot(self.dir / "absente.db", NOON, self.cfg)
        self.assertFalse(s["configured"])
        self.assertTrue(all(p["kwh"] is None for p in s["periods"].values()))

    def test_serie_calendaire_jours_vides(self):
        self.feed([(m * 60, 1000) for m in range(61)])
        series = conso.snapshot(self.db, NOON + timedelta(hours=1), self.cfg)["series"]
        self.assertEqual(len(series), 30)
        self.assertEqual((series[-1]["day"], series[-1]["kwh"], series[0]["kwh"]), (NOON.date().isoformat(), 1.0, None))

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

    def test_minuit_pendant_un_intervalle(self):
        mid = datetime(2026, 10, 14, 0, 0, 0)
        conso._last = None
        for sec in (-30, 30):  # 1 000 W de part et d'autre de minuit : 60 s = 16,67 Wh au total
            conso.sample(1000, mid + timedelta(seconds=sec), self.db)
        wh = dict(sqlite3.connect(self.db).execute("SELECT day, wh FROM pc_energy").fetchall())
        self.assertAlmostEqual(sum(wh.values()), 1000 / 60, places=3)  # rien perdu ni compté deux fois

    def test_horloge_qui_recule(self):
        self.feed([(0, 1000), (60, 1000)])  # 16,67 Wh
        before = sqlite3.connect(self.db).execute("SELECT wh, sec FROM pc_energy").fetchone()
        self.feed([(-3600, 1000), (-3540, 1000)])  # NTP / changement d'heure : le temps repart en arrière
        after = sqlite3.connect(self.db).execute("SELECT SUM(wh), SUM(sec) FROM pc_energy").fetchone()
        self.assertGreaterEqual(after[0], before[0])  # jamais de Wh négatif ni d'énergie retirée
        self.assertLessEqual(after[1], before[1] + 60)  # au plus l'intervalle réellement mesuré

    def test_deux_ecritures_sur_la_meme_base(self):
        for _ in range(2):  # deux Core (ou un redémarrage) : chaque processus ajoute, personne n'écrase
            conso._last = None
            self.feed([(0, 600), (60, 600)])
        wh = sqlite3.connect(self.db).execute("SELECT wh FROM pc_energy").fetchone()[0]
        self.assertAlmostEqual(wh, 2 * 10.0, places=3)

    def test_base_corrompue(self):
        self.db.write_bytes(b"ceci n'est pas une base sqlite" * 50)
        s = conso.snapshot(self.db, NOON, self.cfg)  # lecture : « donnée indisponible », pas d'exception
        self.assertFalse(s["configured"])
        self.assertIsNone(s["periods"]["jour"]["kwh"])

    def test_valeurs_non_numeriques_ignorees(self):
        for bad in ("12", None, float("nan"), float("-inf"), conso.MAX_W + 1):
            conso._last = None
            conso.sample(500, NOON, self.db)
            conso.sample(bad, NOON + timedelta(seconds=60), self.db)
            conso.sample(500, NOON + timedelta(seconds=120), self.db)  # repart de zéro après la rupture
        self.assertFalse(self.db.exists())

    def test_prix_json_hors_bornes(self):
        for raw in ('{"price_kwh": NaN}', '{"price_kwh": Infinity}', '{"price_kwh": -0.2}', '{"price_kwh": 7}', '[]', '"x"', 'null'):
            self.cfg.write_text(raw, encoding="utf-8")
            self.assertIsNone(conso.load_price(self.cfg), raw)

    def test_retention_compte_en_jours_et_garde_la_limite(self):
        self.feed([(0, 100), (60, 100)], start=NOON - timedelta(days=conso.KEEP_DAYS))
        conso._last = None
        self.feed([(0, 100), (60, 100)])
        self.assertEqual(sqlite3.connect(self.db).execute("SELECT COUNT(*) FROM pc_energy").fetchone()[0], 2)  # J-400 gardé


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

    def test_precedent_partiel_signale(self):
        out = conso_tool.summary(self.snap(prev_partial=True, prev_hours=2.0), "jour")
        self.assertIn("mesurés sur 2.0 h seulement", out)

    def test_source_indisponible(self):
        self.assertIn("donnée indisponible", conso_tool.summary(self.snap(kwh=None), "mois"))

    def test_periode_invalide(self):
        with self.assertRaises(ValueError):
            REGISTRY["conso_pc"].run(periode="annee")

    def test_alias_aujourdhui(self):
        with mock.patch.object(conso, "snapshot", return_value=self.snap()):
            self.assertIn("aujourd'hui", REGISTRY["conso_pc"].run(periode="Aujourd'hui"))

    def test_apostrophe_typographique(self):  # la reconnaissance vocale et le LLM produisent souvent « ’ »
        with mock.patch.object(conso, "snapshot", return_value=self.snap()):
            self.assertIn("aujourd'hui", REGISTRY["conso_pc"].run(periode="aujourd’hui"))


class RouterTest(unittest.TestCase):
    def test_intentions_sans_llm(self):
        r = Router()
        for text, periode in (("combien consomme le pc", "jour"), ("Jarvis, combien le PC a consommé aujourd'hui ?", "jour"),
                              ("la consommation du pc cette semaine", "semaine"), ("combien a consommé le pc ce mois-ci", "mois")):
            self.assertEqual(r.route(text), ("conso_pc", {"periode": periode}), text)

    def test_pas_de_faux_positif(self):
        r = Router()
        for text in ("combien consomme le frigo", "consommation du pc portable de Paul", "la conso du pc de Paul",
                     "combien consomme mon pc portable", "consommation de la tv", "combien consomme la clim",
                     "combien consomme le pc et éteins le", "éteins le pc", "consommation du pc cette année"):
            self.assertNotEqual((r.route(text) or ("",))[0], "conso_pc", text)

    def test_autres_intentions_inchangees(self):
        r = Router()
        for text in ("éteins le pc", "volume à 20", "prix des hotels", "mode cinéma"):
            self.assertNotEqual((r.route(text) or ("",))[0], "conso_pc", text)


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
