"""Recette QA de l'étape 3 Consommation (conso_conseils) : cas limites, division par zéro, journal N0, intentions."""
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import jarvis.core.chat  # noqa: F401  (enregistre tous les outils)
import jarvis.tools.conso as conso_tool
from jarvis.core import conseils, conso
from jarvis.core.audit import Audit
from jarvis.core.permissions import execute
from jarvis.core.router import Router
from jarvis.core.tools import REGISTRY, Level
from tests.test_conseils import snaps

NOW = datetime(2026, 10, 14, 9, 0, 0)


def store(tmp: Path, home: dict[str, float]):
    db, cfg = tmp / "conso.db", tmp / "conso.json"
    conso.store_home(home, NOW, db)
    return db, cfg


def week(cur: float, prev: float) -> dict[str, float]:
    return {(date(2026, 10, 13) - timedelta(days=i)).isoformat(): (cur if i < 7 else prev) / 7 for i in range(14)}


class QaEvaluableTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_periode_precedente_a_zero_n_est_pas_un_rien_d_anormal(self):  # BUG-CO-01
        db, cfg = store(self.tmp, week(50.0, 0.0))
        s = conseils.snapshot(db, NOW, cfg)
        self.assertEqual(s["items"], [])
        self.assertFalse(s["evaluable"])  # comparaison impossible (÷ 0) : pas de faux rassurant
        self.assertIn("Pas assez de relevés", conso_tool.advice_summary(s))

    def test_part_plafonnee_n_est_pas_evaluable(self):  # BUG-CO-02
        home = {k: v for k, v in week(70.0, 70.0).items() if k >= "2026-10-07"}  # 7 jours, aucune semaine d'avant
        db, cfg = store(self.tmp, home)
        with closing(sqlite3.connect(db)) as cx, cx:
            cx.execute("CREATE TABLE IF NOT EXISTS pc_energy (day TEXT PRIMARY KEY, wh REAL, sec REAL)")
            cx.executemany("INSERT INTO pc_energy VALUES (?, ?, ?)", [(d, 99000.0, 86400.0) for d in home])
        self.assertTrue(conso.home_snapshot(db, NOW, cfg)["periods"]["semaine"]["pc_capped"])
        s = conseils.snapshot(db, NOW, cfg)
        self.assertEqual(s["items"], [])
        self.assertFalse(s["evaluable"])

    def test_semaine_complete_stable_est_rien_d_anormal(self):
        db, cfg = store(self.tmp, week(70.0, 70.0))
        s = conseils.snapshot(db, NOW, cfg)
        self.assertTrue(s["evaluable"])
        self.assertEqual(s["items"], [])
        self.assertIn("Rien d'anormal", conso_tool.advice_summary(s))

    def test_seuil_hausse_15_pct_et_5_kwh(self):
        self.assertEqual(conseils.advice(*snaps({"kwh": 40.0, "prev_kwh": 34.8})), [])  # +5,2 kWh, +14,9 %
        out = conseils.advice(*snaps({"kwh": 40.0, "prev_kwh": 34.0}))  # +6 kWh, +17,6 %
        self.assertEqual([a["id"] for a in out], ["hausse_logement"])

    def test_pas_de_conseil_de_baisse_ni_prev_nul(self):
        self.assertEqual(conseils.advice(*snaps({"kwh": 10.0, "prev_kwh": 70.0})), [])
        self.assertEqual(conseils.advice(*snaps({"kwh": 70.0, "prev_kwh": 0.0})), [])

    def test_prix_nul_ou_absent_pas_de_cout(self):
        for price in (None, 0, 0.0):
            self.assertNotIn("€", conseils.advice(*snaps({"kwh": 90.0}), price)[0]["text"])

    def test_texte_francais_unites(self):
        t = conseils.advice(*snaps({"kwh": 90.0}), 0.2516)[0]["text"]
        self.assertIn("20,0 kWh", t)
        self.assertIn("5,03 €", t)  # virgule décimale
        self.assertNotRegex(t, r"\d\.\d")


class QaToolTest(unittest.TestCase):
    def audit(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        audit = Audit(path)
        self.addCleanup(os.unlink, path)
        self.addCleanup(audit.db.close)
        return audit

    def test_journal_n0_sans_confirmation(self):
        audit = self.audit()
        self.assertEqual(REGISTRY["conso_conseils"].level, Level.N0)
        empty = {"available": False, "evaluable": False, "items": []}  # hermétique : pas la vraie base du propriétaire
        with mock.patch.object(conseils, "snapshot", return_value=empty):
            out = execute("conso_conseils", {}, source="cli", audit=audit,
                          confirm=lambda t, a: self.fail("N0 ne demande aucune confirmation"),
                          strong_auth=lambda t, a: self.fail("N0 : pas d'authentification forte"))
        self.assertIn("donnée indisponible", out)
        rows = audit.db.execute("SELECT * FROM audit").fetchall()
        self.assertEqual(len(rows), 2)  # « en cours » puis le résultat
        self.assertTrue(all(r[3] == "conso_conseils" and r[6] == "auto" for r in rows))

    def test_resultat_absent_du_journal(self):  # constat Sécurité 1 : kWh et € ne vont pas en clair au journal
        audit = self.audit()
        for name in ("conso_conseils", "conso_pc", "conso_totale"):
            self.assertTrue(REGISTRY[name].private, name)
        snap = {"available": True, "evaluable": True, "items": [{"text": "Hausse de 12,3 kWh."}]}
        with mock.patch.object(conseils, "snapshot", return_value=snap):
            out = execute("conso_conseils", {}, source="cli", audit=audit,
                          confirm=lambda t, a: False, strong_auth=lambda t, a: False)
        self.assertIn("12,3 kWh", out)  # l'appelant (LLM, voix, PWA) reçoit toujours le texte
        logged = " ".join(str(r) for r in audit.db.execute("SELECT * FROM audit").fetchall())
        self.assertNotIn("12,3", logged)

    def test_parametre_inconnu_refuse(self):
        with self.assertRaises(Exception):
            execute("conso_conseils", {"periode": "mois"}, source="cli", audit=self.audit(),
                    confirm=lambda t, a: False, strong_auth=lambda t, a: False)

    def test_sortie_non_externe(self):
        self.assertFalse(REGISTRY["conso_conseils"].external)  # nombres calculés par le Core, jamais du texte tiers


class QaIntentTest(unittest.TestCase):
    def test_variantes_accentuees_et_ponctuation(self):
        r = Router()
        for text in ("Des conseils pour économiser l'électricité", "comment réduire ma consommation électrique",
                     "Comment baisser ma conso ?", "COMMENT CONSOMMER MOINS", "des conseils sur la consommation"):
            self.assertEqual((r.route(text) or ("",))[0], "conso_conseils", text)

    def test_ne_vole_pas_les_autres_intentions(self):
        r = Router()
        for text, tool in (("combien consomme le pc cette semaine", "conso_pc"),
                           ("la conso de la maison hier", "conso_totale")):
            self.assertEqual(r.route(text)[0], tool, text)
