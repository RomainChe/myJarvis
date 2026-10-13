"""Onglet Voyages : lecture du CSV de flight-price-tracker, lignes invalides et liens non https écartés, route authentifiée."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import voyages
from tests.test_server import ServerBase

HEAD = "run_date,search,source,kind,origin,dest,return_from,return_to,depart_date,return_date,price,airlines,stops,duration_min,link\n"


def row(day, search, origin, price, link="https://www.google.com/travel/flights/x"):
    return f"{day},{search},Google Flights,aller-retour,{origin},NRT,NRT,{origin},2027-05-05,2027-05-22,{price},ANA,1,900,{link}\n"


def project(text: str) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "data").mkdir()
    (root / "data" / "prices.csv").write_text(text, encoding="utf-8")
    return root


class VoyagesTest(unittest.TestCase):
    def test_nominal(self):
        s = voyages.snapshot(project(HEAD + row("2026-10-03", "Japon", "CDG", 950) + row("2026-10-03", "Japon", "BCN", 800)
                                     + row("2026-10-04", "Japon", "CDG", 870) + row("2026-10-04", "Japon", "LYS", 990)
                                     + row("2026-10-04", "Japon", "CDG", 900)))
        self.assertTrue(s["configured"])
        j = s["searches"][0]
        self.assertEqual((j["name"], j["last_run"], j["best"]["price"], j["previous"], j["lowest"]), ("Japon", "2026-10-04", 870, 800, 800))
        self.assertEqual([(o["origin"], o["price"]) for o in j["by_origin"]], [("CDG", 870), ("LYS", 990)])
        self.assertEqual([h["price"] for h in j["history"]], [800, 870])
        self.assertEqual((j["best"]["stops"], j["best"]["duration_min"]), (1, 900))

    def test_nouvelle_destination_en_tete(self):
        s = voyages.snapshot(project(HEAD + row("2026-10-03", "Japon", "CDG", 800) + row("2026-12-01", "Corée du Sud", "CDG", 700)))
        self.assertEqual([x["name"] for x in s["searches"]], ["Corée du Sud", "Japon"])

    def test_lignes_invalides_et_lien_non_https(self):
        s = voyages.snapshot(project(HEAD + row("2026-10-03", "Japon", "CDG", "abc") + row("2026-10-03", "Japon", "CDG", -5)
                                     + row("hier", "Japon", "CDG", 500) + row("2026-10-03", "", "CDG", 500)
                                     + row("2026-10-03", "Japon", "ORY", 900, "javascript:alert(1)")))
        j = s["searches"][0]
        self.assertEqual((len(s["searches"]), j["best"]["price"], j["best"]["link"]), (1, 900, None))

    def test_absent(self):
        self.assertEqual(voyages.snapshot(Path(tempfile.mkdtemp())), {"configured": False, "searches": []})

    def test_gros_fichier_garde_les_lignes_recentes(self):
        root = project(HEAD + row("2026-10-03", "Ancien", "CDG", 500) * 50 + row("2026-10-04", "Récent", "CDG", 600))
        with mock.patch.object(voyages, "MAX_BYTES", 300):
            s = voyages.snapshot(root)
        self.assertEqual(s["searches"][0]["name"], "Récent")

    def test_config(self):
        cfg = Path(tempfile.mkdtemp()) / "voyages.json"
        cfg.write_text('{"dir": "D:/ft"}', encoding="utf-8")
        self.assertEqual(voyages.tracker_dir(cfg), Path("D:/ft"))
        cfg.write_text("pas du json", encoding="utf-8")
        self.assertEqual(voyages.tracker_dir(cfg), voyages.DEFAULT_DIR)


class VoyagesRouteTest(ServerBase):
    def test_authentification_exigee(self):
        self.assertEqual(self.call("GET", "/api/voyages")[0], 401)
        _, token = self.enroll()
        with mock.patch("jarvis.server.voyages_snapshot", return_value={"configured": True, "searches": []}):
            status, body, _ = self.call("GET", "/api/voyages", token=token)
        self.assertEqual((status, body), (200, {"configured": True, "searches": []}))


if __name__ == "__main__":
    unittest.main()
