"""Conseils de consommation : règles déterministes, seuils, périodes partielles, outil `conso_conseils`, intention."""
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import jarvis.core.chat  # noqa: F401  (charge tous les outils)
import jarvis.tools.conso as conso_tool
from jarvis.core import conseils, conso
from jarvis.core.router import Router
from jarvis.core.tools import REGISTRY, Level

NOW = datetime(2026, 10, 14, 9, 0, 0)


def period(**kw):
    return {"kwh": 70.0, "prev_kwh": 70.0, "partial": False, "prev_partial": False, "pc_share": None, "pc_partial": False,
            "pc_days": 7, "pc_base_kwh": 70.0, "pc_capped": False} | kw


def snaps(home=None, pc=None):
    return ({"periods": {"semaine": period(**(home or {}))}}, {"periods": {"semaine": period(**(pc or {}))}})


class AdviceTest(unittest.TestCase):
    def ids(self, home=None, pc=None, price=None):
        return [a["id"] for a in conseils.advice(*snaps(home, pc), price)]

    def test_rien_d_anormal(self):
        self.assertEqual(self.ids(), [])

    def test_hausse_logement_cite_les_chiffres_et_le_cout(self):
        out = conseils.advice(*snaps({"kwh": 90.0}), 0.2)
        self.assertEqual([a["id"] for a in out], ["hausse_logement"])
        self.assertIn("20,0 kWh", out[0]["text"])
        self.assertIn("90,0 kWh contre 70,0 kWh", out[0]["text"])
        self.assertIn("4,00 €", out[0]["text"])

    def test_seuils_pourcentage_et_kwh(self):
        self.assertEqual(self.ids({"kwh": 72.0}), [])  # +2 kWh : sous les deux seuils
        self.assertEqual(self.ids({"kwh": 10.0, "prev_kwh": 4.0}), ["hausse_logement"])  # +6 kWh et +150 % : les deux seuils
        self.assertEqual(self.ids({"kwh": 100.0, "prev_kwh": 90.0}), [])  # +10 kWh mais +11 % : sous 15 %

    def test_periode_partielle_ne_declenche_pas(self):
        self.assertEqual(self.ids({"kwh": 90.0, "partial": True}), [])
        self.assertEqual(self.ids({"kwh": 90.0, "prev_partial": True}), [])
        self.assertEqual(self.ids({"kwh": None}), [])
        self.assertEqual(self.ids({"prev_kwh": None, "kwh": 90.0}), [])

    def test_part_du_pc(self):
        out = conseils.advice(*snaps({"pc_share": 0.3}))
        self.assertEqual([a["id"] for a in out], ["part_pc"])
        self.assertIn("30 %", out[0]["text"])
        self.assertNotIn("au moins", out[0]["text"])
        self.assertIn("au moins 30 %", conseils.advice(*snaps({"pc_share": 0.3, "pc_partial": True}))[0]["text"])
        self.assertEqual(self.ids({"pc_share": 0.2}), [])

    def test_part_du_pc_exige_des_jours_mesures(self):  # BUG-CO4-01
        self.assertEqual(self.ids({"pc_share": 0.4, "pc_days": 1}), [])
        out = conseils.advice(*snaps({"pc_share": 0.4, "pc_days": 5, "pc_base_kwh": 50.0}))
        self.assertIn("sur 5 jours mesurés (50,0 kWh au total)", out[0]["text"])

    def test_part_plafonnee_non_conseillee(self):  # BUG-CO4-06
        self.assertEqual(self.ids({"pc_share": 1.0, "pc_capped": True}), [])

    def test_conseil_veille_sans_extinction(self):
        self.assertNotIn("Éteins", conseils.advice(*snaps({"pc_share": 0.3}))[0]["text"])

    def test_flottants_aux_seuils(self):  # BUG-CO4-03
        self.assertEqual(self.ids(pc={"kwh": 2.3, "prev_kwh": 1.3}), ["hausse_pc"])  # +1,0 exact : 2.3 - 1.3 < 1.0 en flottant

    def test_delta_coherent_avec_les_chiffres_affiches(self):  # BUG-CO4-04
        out = conseils.advice(*snaps({"kwh": 90.06, "prev_kwh": 70.04}))
        self.assertIn("20,1 kWh", out[0]["text"])  # 90,1 - 70,0 : le delta suit les chiffres cités
        self.assertIn("90,1 kWh contre 70,0 kWh", out[0]["text"])

    def test_hausse_pc(self):
        self.assertEqual(self.ids(pc={"kwh": 10.0, "prev_kwh": 6.0}), ["hausse_pc"])
        self.assertEqual(self.ids(pc={"kwh": 10.0, "prev_kwh": 9.0}), [])  # +11 % seulement


class SnapshotTest(unittest.TestCase):
    def test_sans_donnee_indisponible(self):
        d = Path(tempfile.mkdtemp())
        s = conseils.snapshot(d / "absente.db", NOW, d / "c.json")
        self.assertEqual(s, {"available": False, "evaluable": False, "items": []})

    def test_donnees_insuffisantes_pas_rien_d_anormal(self):  # BUG-CO4-02
        d = Path(tempfile.mkdtemp())
        db, cfg = d / "conso.db", d / "conso.json"
        conso.store_home({"2026-10-05": 10.0, "2026-10-04": 10.0}, NOW, db)  # 2 jours anciens
        s = conseils.snapshot(db, NOW, cfg)
        self.assertTrue(s["available"])
        self.assertFalse(s["evaluable"])
        self.assertIn("Pas assez de relevés", conso_tool.advice_summary(s))

    def test_de_bout_en_bout(self):
        d = Path(tempfile.mkdtemp())
        db, cfg = d / "conso.db", d / "conso.json"
        days = {(date(2026, 10, 13) - timedelta(days=i)).isoformat(): 15.0 if i < 7 else 10.0 for i in range(14)}
        conso.store_home(days, NOW, db)
        s = conseils.snapshot(db, NOW, cfg)
        self.assertTrue(s["available"])
        self.assertTrue(s["evaluable"])
        self.assertEqual([a["id"] for a in s["items"]], ["hausse_logement"])  # 105 kWh contre 70


class ToolTest(unittest.TestCase):
    def test_niveau_n0(self):
        self.assertEqual(REGISTRY["conso_conseils"].level, Level.N0)

    def test_phrases(self):
        self.assertIn("donnée indisponible", conso_tool.advice_summary({"available": False, "evaluable": False, "items": []}))
        self.assertIn("Rien d'anormal", conso_tool.advice_summary({"available": True, "evaluable": True, "items": []}))
        out = conso_tool.advice_summary({"available": True, "evaluable": True,
                                         "items": [{"id": "a", "text": "Un."}, {"id": "b", "text": "Deux."}]})
        self.assertEqual(out, "Un. Deux.")

    def test_intention_sans_llm(self):
        r = Router()
        for text in ("des conseils pour consommer moins", "comment réduire ma consommation", "conseils conso"):
            self.assertEqual(r.route(text)[0], "conso_conseils", text)
        for text in ("combien consomme le pc", "conseils pour mon voyage"):
            self.assertNotEqual((r.route(text) or ("",))[0], "conso_conseils", text)
