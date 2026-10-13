"""Onglet Bien-être : lecture du dernier bilan, tri, comparaison à la veille, relance quotidienne bornée, route."""
import json
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from jarvis.core import bienetre
from tests.test_server import ServerBase


def c(statut, point="Charge", impact=2, conseil="Rien à faire."):
    return {"composant": "Processeur", "point": point, "statut": statut, "valeur": "26 %", "seuil": "70 %", "conseil": conseil,
            "impact": impact}


def project(files: dict) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "bienetre").mkdir()
    (root / "historique").mkdir()
    for name, data in files.items():
        (root / "historique" / name).write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return root


class BienetreTest(unittest.TestCase):
    def setUp(self):
        bienetre._state.update(tried=0.0, error=None, running=False)

    def test_dernier_bilan_trie_et_compare_a_la_veille(self):
        root = project({
            "2026-10-12_080000.json": [c("problème"), c("OK")],
            "2026-10-13_080000.json": [c("OK"), c("à surveiller", "RAM", 3, "Fermez des onglets."), c("problème", "Disque", 1),
                                       c("non mesuré", "SMART")],
            "2026-10-13_190000.json": [c("OK"), c("à surveiller", "RAM", 3, "Fermez des onglets."), c("problème", "Disque", 1),
                                       c("non mesuré", "SMART")],
        })
        with mock.patch.object(bienetre, "refresh_if_stale"):
            s = bienetre.snapshot(root)
        self.assertEqual([i["statut"] for i in s["items"]], ["problème", "à surveiller", "non mesuré", "OK"])
        self.assertEqual(s["at"], "2026-10-13T19:00")
        self.assertEqual(s["counts"], {"problème": 1, "à surveiller": 1, "non mesuré": 1, "OK": 1})
        self.assertEqual(s["previous"], {"day": "2026-10-12", "counts": {"problème": 1, "à surveiller": 0, "non mesuré": 0, "OK": 1}})

    def test_donnees_hostiles_tronquees_ou_ignorees(self):
        root = project({"2026-10-13_080000.json": [c("OK"), {"statut": "inconnu"}, "x", c("OK", conseil="a" * 5000)],
                        "2026-10-14_080000.json": "pas du json", "2026-10-14_090000.txt": "[]", "x.json": "[]"})
        with mock.patch.object(bienetre, "refresh_if_stale"):
            s = bienetre.snapshot(root)  # le fichier abîmé n'efface pas le bilan précédent
        self.assertEqual(len(s["items"]), 2)
        self.assertEqual(max(len(i["conseil"]) for i in s["items"]), 500)
        self.assertEqual(s["at"], "2026-10-13T08:00")

    def test_projet_absent(self):
        s = bienetre.snapshot(Path(tempfile.mkdtemp()) / "nope")
        self.assertEqual((s["configured"], s["items"], s["counts"]), (False, [], None))

    def test_relance_seulement_si_pas_de_bilan_du_jour_et_une_fois_par_heure(self):
        root = project({"2026-10-12_080000.json": [c("OK")]})
        runs = []
        go = lambda **k: bienetre.refresh_if_stale(root, today=date(2026, 10, 13), runner=lambda r: runs.append(r) or True,
                                                  start=lambda f: f(), **k)
        self.assertTrue(go(now=10000.0))
        self.assertFalse(go(now=10100.0))  # moins d'une heure
        self.assertTrue(go(now=10000.0 + bienetre.RETRY_S))
        self.assertEqual(len(runs), 2)
        self.assertFalse(bienetre.refresh_if_stale(root, today=date(2026, 10, 12), runner=runs.append, start=lambda f: f(),
                                                   now=99999.0))  # bilan du jour déjà là

    def test_echec_de_la_relance_signale_sans_planter(self):
        root = project({})
        bienetre.refresh_if_stale(root, today=date(2026, 10, 13), runner=lambda r: (_ for _ in ()).throw(OSError()),
                                  start=lambda f: f(), now=time.time())
        self.assertEqual(bienetre._state["error"], "le bilan n'a pas pu être lancé")
        self.assertFalse(bienetre._state["running"])

    def test_dossier_sans_projet_jamais_relance(self):
        self.assertFalse(bienetre.refresh_if_stale(Path(tempfile.mkdtemp()), runner=lambda r: True, start=lambda f: f()))

    def test_config(self):
        cfg = Path(tempfile.mkdtemp()) / "b.json"
        cfg.write_text('{"dir": "D:/x"}', encoding="utf-8")
        self.assertEqual(bienetre.project_dir(cfg), Path("D:/x"))
        self.assertEqual(bienetre.project_dir(cfg.with_name("absent.json")), bienetre.DEFAULT_DIR)
        cfg.write_text('{"dir": "relatif/x"}', encoding="utf-8")
        self.assertEqual(bienetre.project_dir(cfg), bienetre.DEFAULT_DIR)  # chemin relatif refusé


class BienetreRouteTest(ServerBase):
    def test_authentification_exigee_lecture_journalisee(self):
        self.assertEqual(self.call("GET", "/api/bienetre")[0], 401)
        _, token = self.enroll()
        with mock.patch("jarvis.server.bienetre_core.snapshot", return_value={"configured": True, "items": []}):
            status, body, _ = self.call("GET", "/api/bienetre", token=token)
        self.assertEqual((status, body), (200, {"configured": True, "items": []}))
        self.assertIn("bienetre_read", str(self.call("GET", "/api/audit?limit=20", token=token)[1]))


if __name__ == "__main__":
    unittest.main()
