"""Onglet Voyages : lecture du CSV de flight-price-tracker, lignes invalides et liens non https écartés, synchronisation
par `git fetch` (1/h, copie de travail jamais touchée), route authentifiée."""
import subprocess
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
    def setUp(self):
        voyages._sync.update(at=0.0, ok=None, error=None)
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
        self.assertEqual(voyages.snapshot(Path(tempfile.mkdtemp())),
                         {"configured": False, "searches": [], "synced_at": None, "sync_error": None})

    def test_sync_lit_origin_main_et_limite_a_une_fois_par_heure(self):
        root = project(HEAD + row("2026-10-03", "Japon", "CDG", 900))
        (root / ".git").mkdir()
        remote = (HEAD + row("2026-10-13", "Japon", "CDG", 750)).encode()
        calls = []
        def git(_root, *args):
            calls.append(args[0])
            return remote if args[0] == "show" else b""
        with mock.patch.object(voyages, "_git", side_effect=git):
            s = voyages.snapshot(root)
            voyages.snapshot(root)
        self.assertEqual((s["searches"][0]["last_run"], s["sync_error"]), ("2026-10-13", None))
        self.assertIsNotNone(s["synced_at"])
        self.assertEqual(calls, ["fetch", "show", "show"])  # second appel dans l'heure : pas de fetch
        self.assertEqual((root / "data" / "prices.csv").read_text(encoding="utf-8").count("2026-10-13"), 0)

    def test_sync_en_echec_garde_la_copie_locale(self):
        root = project(HEAD + row("2026-10-03", "Japon", "CDG", 900))
        (root / ".git").mkdir()
        with mock.patch.object(voyages, "_git", side_effect=subprocess.TimeoutExpired("git", 20)):
            s = voyages.snapshot(root)
        self.assertEqual((s["searches"][0]["last_run"], s["synced_at"]), ("2026-10-03", None))
        self.assertEqual(s["sync_error"], "échec de la synchronisation avec GitHub")

    def test_sortie_git_trop_grosse_coupee(self):
        data = (HEAD + row("2026-10-03", "Ancien", "CDG", 500) * 50 + row("2026-10-04", "Récent", "CDG", 600)).encode()
        with mock.patch.object(voyages, "MAX_BYTES", 300):
            lines = voyages._lines(data)
        self.assertEqual((lines[0], lines[-1].split(",")[1]), (HEAD.strip(), "Récent"))
        self.assertLess(len(lines), 10)

    def test_git_sans_hooks_ni_protocoles_locaux(self):
        with mock.patch("subprocess.run") as run:
            voyages._git(Path("x"), "fetch")
        cmd = run.call_args.args[0]
        self.assertIn("protocol.allow=never", cmd)
        self.assertTrue(any(c.startswith("core.hooksPath=") for c in cmd))
        self.assertEqual(run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

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
