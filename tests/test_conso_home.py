"""Total du logement (MyElectricalData) : client borné, rafraîchissement, fenêtres, part du PC, outil `conso_totale`."""
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import jarvis.tools.conso as conso_tool
from jarvis.core import conso, enedis
from jarvis.core.tools import REGISTRY, Level

NOW = datetime(2026, 10, 14, 9, 0, 0)
PDL = "12345678901234"  # PDL factice


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(payload, seen=None):
    def _open(req, timeout=None):
        if seen is not None:
            seen.append((req, timeout))
        if isinstance(payload, Exception):
            raise payload
        return Resp(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    return _open


def body(*pairs):
    return {"meter_reading": {"interval_reading": [{"date": d, "value": str(v)} for d, v in pairs]}}


class FetchTest(unittest.TestCase):
    first, end = date(2026, 9, 14), date(2026, 10, 14)

    def test_nominal_wh_vers_kwh(self):
        seen = []
        out = enedis.fetch("tok", PDL, self.first, self.end, opener(body(("2026-10-13", 8500), ("2026-10-12", 0)), seen))
        self.assertEqual(out, {"2026-10-13": 8.5, "2026-10-12": 0.0})
        req, timeout = seen[0]
        self.assertTrue(req.full_url.endswith(f"/daily_consumption/{PDL}/start/2026-09-14/end/2026-10-14/"))
        self.assertEqual(req.get_header("Authorization"), "tok")
        self.assertEqual(timeout, enedis.TIMEOUT_S)

    def test_valeurs_invalides_ignorees(self):
        rows = (("2026-10-13", 600_000), ("2026-10-12", -5), ("2026-10-11", "nan"), ("pas-une-date", 100),
                ("2026-10-14", 100), ("2026-10-10", "abc"), ("2026-10-09", 4000))  # 600 kWh, négatif, NaN, hors fenêtre
        out = enedis.fetch("tok", PDL, self.first, self.end, opener(body(*rows)))
        self.assertEqual(out, {"2026-10-09": 4.0})

    def test_pdl_invalide_sans_appel_reseau(self):
        seen = []
        for bad in ("", "123", "../etc", PDL + "0"):
            with self.assertRaises(enedis.Unavailable):
                enedis.fetch("tok", bad, self.first, self.end, opener(body(), seen))
        self.assertEqual(seen, [])

    def test_source_indisponible_sans_fuite(self):
        for payload in (OSError("boom tok"), b"pas du json", {"detail": "token invalide"}, {"meter_reading": 3}):
            with self.assertRaises(enedis.Unavailable) as cm:
                enedis.fetch("tok", PDL, self.first, self.end, opener(payload))
            self.assertNotIn("tok", str(cm.exception))
            self.assertNotIn(PDL, str(cm.exception))


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "conso.db"
        self.calls = []

    def fake(self, days):
        def f(token, pdl, first, end):
            self.calls.append((token, pdl, first, end))
            if isinstance(days, Exception):
                raise days
            return days
        return f

    @staticmethod
    def secrets_ok(name):
        return {"med_token": "tok", "med_pdl": PDL}[name]

    def test_ok_puis_a_jour_dans_les_24h(self):
        self.assertEqual(enedis.refresh(self.db, NOW, self.fake({"2026-10-13": 9.0}), self.secrets_ok), "ok")
        self.assertEqual(enedis.refresh(self.db, NOW + timedelta(hours=5), self.fake({}), self.secrets_ok), "à jour")
        self.assertEqual(len(self.calls), 1)
        later = NOW + timedelta(hours=25)
        self.assertEqual(enedis.refresh(self.db, later, self.fake({"2026-10-14": 7.0}), self.secrets_ok), "ok")

    def test_non_configure_sans_appel(self):
        def broken(name):
            raise RuntimeError("pas de coffre")
        for secret in (lambda n: None, broken):
            self.assertEqual(enedis.refresh(self.db, NOW, self.fake({}), secret), "non configuré")
        self.assertEqual(self.calls, [])

    def test_indisponible_ecrit_rien(self):
        self.assertEqual(enedis.refresh(self.db, NOW, self.fake(enedis.Unavailable("x")), self.secrets_ok), "indisponible")
        self.assertEqual(enedis.refresh(self.db, NOW, self.fake({}), self.secrets_ok), "indisponible")  # réponse vide
        self.assertFalse(self.db.exists())


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db, self.cfg = self.dir / "conso.db", self.dir / "conso.json"
        conso._last = None

    def test_fenetres_finissent_hier_et_precedent(self):
        days = {(date(2026, 10, 13) - timedelta(days=i)).isoformat(): 10.0 for i in range(14)}  # 14 jours à 10 kWh
        conso.store_home(days, NOW, self.db)
        self.cfg.write_text('{"price_kwh": 0.2}', encoding="utf-8")
        p = conso.home_snapshot(self.db, NOW, self.cfg)["periods"]
        self.assertEqual((p["jour"]["kwh"], p["jour"]["prev_kwh"], p["jour"]["eur"]), (10.0, 10.0, 2.0))
        self.assertEqual((p["semaine"]["kwh"], p["semaine"]["prev_kwh"], p["semaine"]["partial"]), (70.0, 70.0, False))
        self.assertTrue(p["mois"]["partial"])  # 14 jours sur 30 : annoncé, pas extrapolé
        self.assertEqual(p["mois"]["days"], 14)

    def test_part_du_pc_sur_jours_communs(self):
        conso.store_home({"2026-10-13": 10.0, "2026-10-12": 10.0}, NOW, self.db)
        for sec in range(0, 3601, 60):  # PC : 1 kWh le 12 uniquement
            conso.sample(1000, datetime(2026, 10, 12, 12) + timedelta(seconds=sec), self.db)
        p = conso.home_snapshot(self.db, NOW, self.cfg)["periods"]
        self.assertEqual(p["semaine"]["pc_share"], 0.1)  # 1 / 10 sur le seul jour commun
        self.assertIsNone(p["jour"]["pc_share"])  # le 13 : pas de mesure du PC

    def test_sans_base_ou_sans_releve(self):
        s = conso.home_snapshot(self.dir / "absente.db", NOW, self.cfg)
        self.assertFalse(s["configured"])
        self.assertTrue(all(p["kwh"] is None for p in s["periods"].values()))
        for sec in (0, 60):
            conso.sample(100, datetime(2026, 10, 13, 12) + timedelta(seconds=sec), self.db)  # base de la prise seule
        self.assertFalse(conso.home_snapshot(self.db, NOW, self.cfg)["configured"])

    def test_retention(self):
        old = (NOW.date() - timedelta(days=conso.KEEP_DAYS + 1)).isoformat()
        conso.store_home({old: 5.0, "2026-10-13": 8.0}, NOW, self.db)
        self.assertEqual(sqlite3.connect(self.db).execute("SELECT COUNT(*) FROM home_energy").fetchone()[0], 1)


class ToolTest(unittest.TestCase):
    def snap(self, **period):
        base = {"kwh": 12.0, "eur": 3.0, "prev_kwh": 10.0, "days": 1, "partial": False, "pc_share": 0.25} | period
        return {"periods": {"jour": base, "semaine": base, "mois": base}, "last_day": "2026-10-13"}

    def test_niveau_n0(self):
        self.assertEqual(REGISTRY["conso_totale"].level, Level.N0)

    def test_resume_nominal(self):
        out = conso_tool.home_summary(self.snap(), "jour")
        self.assertEqual(out, "Le logement a consommé 12,00 kWh hier (environ 3,00 €), contre 10,00 kWh la veille. "
                              "Le PC en représente 25 %.")

    def test_partiel_et_sans_part(self):
        out = conso_tool.home_summary(self.snap(partial=True, days=5, pc_share=None, eur=None), "semaine")
        self.assertIn("5 jours relevés seulement", out)
        self.assertNotIn("PC en représente", out)

    def test_source_indisponible(self):
        self.assertIn("donnée indisponible", conso_tool.home_summary(self.snap(kwh=None), "mois"))

    def test_periode_invalide(self):
        with self.assertRaises(ValueError):
            conso_tool.conso_totale("année")
