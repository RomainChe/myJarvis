"""Onglet Finances : lecture des rapports .eml (montants inventés), valeurs hostiles ignorées, route authentifiée et journalisée."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import finance
from tests.test_server import ServerBase

NB = "\u00a0"


def report(week=40, spent="604,77", extra="") -> bytes:
    html = (
        f"<div>Dépenses — Semaine {week}</div><div>Du lundi 28 septembre au dimanche 4 octobre · comparé</div>"
        f"<div>💸 Dépenses</div><div>{spent}{NB}€</div><div>+10,00{NB}€ (+69{NB}%) vs S39</div>"
        f"<div>🌱 dont épargne</div><div>300,00{NB}€</div><div>-5,00{NB}€ (-3{NB}%) vs S39</div>"
        f"<div>🛍️ Consommation</div><div>285,89{NB}€</div><div>+8,00{NB}€ (+41{NB}%) vs S39</div>"
        f"<div>💰 Entrées</div><div>2 000,00{NB}€</div><div>Paie</div>"
        "<div>Reste à vivre</div><div>≈ 200,50 €</div><div>≈ 9,73 €/jour</div>"
        "<div>Consommation de la semaine</div><div>🔁  </div><div>Abonnements</div><div>76 %</div><div>216,00 €</div>"
        "<div>🛒  </div><div>Courses</div><div>24 %</div><div>69,89 €</div><div>Total consommation</div>"
        f"<div>Total disponible</div><div>1 000,00 €</div>{extra}"
    )
    return (f"Date: Mon, 5 Oct 2026 00:00:10 -0700\nSubject: =?UTF-8?Q?[D=C3=A9penses]_Semaine_{week}?=\n"
            "MIME-Version: 1.0\nContent-Type: text/html; charset=UTF-8\n\n" + html).encode("utf-8")


def folder(files: dict) -> Path:
    root = Path(tempfile.mkdtemp())
    for name, raw in files.items():
        (root / name).write_bytes(raw)
    return root


class FinanceTest(unittest.TestCase):
    def test_nominal(self):
        s = finance.snapshot(folder({"a.eml": report(39, "400,00"), "b.eml": report(40)}))
        d = s["latest"]
        self.assertEqual((d["week"], d["year"]), (40, 2026))
        self.assertEqual(d["period"], "Du lundi 28 septembre au dimanche 4 octobre")
        self.assertEqual(d["spent"], {"amount": 604.77, "vs_pct": 69})
        self.assertEqual(d["saved"], {"amount": 300.0, "vs_pct": -3})
        self.assertEqual(d["income"]["amount"], 2000.0)
        self.assertEqual((d["left_to_live"], d["per_day"], d["balance"]), (200.5, 9.73, 1000.0))
        self.assertEqual(d["categories"], [{"name": "Abonnements", "pct": 76, "amount": 216.0},
                                           {"name": "Courses", "pct": 24, "amount": 69.89}])
        self.assertEqual([(t["week"], t["spent"]) for t in s["trend"]], [(39, 400.0), (40, 604.77)])

    def test_rapport_illisible_ou_hostile_ignore(self):
        s = finance.snapshot(folder({
            "a.eml": b"pas un mail", "b.eml": report(99), "c.eml": b"Subject: Semaine 12\n\nsans date ni html",
            "d.eml": report(40).replace(b"Date: Mon, 5 Oct 2026 00:00:10 -0700", b"Date: n'importe quoi"),
            "e.txt": report(41), "gros.eml": report(42, extra="x" * (finance.MAX_BYTES + 1)),
        }))
        self.assertEqual(s["trend"], [])
        self.assertIsNone(s["latest"])

    def test_entrees_pathologiques_en_temps_borne(self):
        for extra in ("<" * 190_000, "Consommation de la semaine" * 7000):
            t = time.monotonic()
            finance.snapshot(folder({"a.eml": report(40, extra=extra)}))
            self.assertLess(time.monotonic() - t, 1.0)

    def test_semaines_recentes_gardees_au_dela_du_plafond(self):
        files = {f"{i:03}.eml": report(1 + i % 50) for i in range(finance.MAX_FILES + 5)}
        root = folder(files)
        newest = root / "000.eml"  # premier par nom, mais le plus récent
        os.utime(newest, (time.time() + 100, time.time() + 100))
        raw = report(52)
        newest.write_bytes(raw)
        os.utime(newest, (time.time() + 100, time.time() + 100))
        self.assertEqual(finance.snapshot(root)["latest"]["week"], 52)

    def test_champ_manquant_vaut_none(self):
        raw = b"Date: Mon, 5 Oct 2026 00:00:10 -0700\nSubject: Semaine 7\nContent-Type: text/html\n\n<p>rien</p>"
        d = finance.snapshot(folder({"a.eml": raw}))["latest"]
        self.assertEqual((d["week"], d["spent"], d["left_to_live"], d["categories"]), (7, None, None, []))

    def test_dossier_absent_et_config(self):
        self.assertEqual(finance.snapshot(Path(tempfile.mkdtemp()) / "nope"), {"configured": False, "latest": None, "trend": []})
        cfg = Path(tempfile.mkdtemp()) / "f.json"
        cfg.write_text('{"dir": "D:/x"}', encoding="utf-8")
        self.assertEqual(finance.finance_dir(cfg), Path("D:/x"))
        self.assertEqual(finance.finance_dir(cfg.with_name("absent.json")), finance.DEFAULT_DIR)


class FinanceRouteTest(ServerBase):
    def test_authentification_exigee_lecture_journalisee(self):
        self.assertEqual(self.call("GET", "/api/finance")[0], 401)
        _, token = self.enroll()
        with mock.patch("jarvis.server.finance_snapshot", return_value={"configured": True, "latest": None, "trend": []}):
            status, body, _ = self.call("GET", "/api/finance", token=token)
        self.assertEqual((status, set(body)), (200, {"configured", "latest", "trend"}))
        status, body, _ = self.call("GET", "/api/audit?limit=20", token=token)
        self.assertIn("finance_read", str(body))


if __name__ == "__main__":
    unittest.main()
