"""Onglet Voyages, étape 3 : `voyage_destination` (N2) réécrit config.yaml à partir de origin/main, commit + push par la
plomberie git (copie de travail et branche locale intactes), course avec le workflow rattrapée, confirmation web exigée."""
import dataclasses
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from jarvis.core import voyages
from jarvis.core.tools import REGISTRY, Level, _registry
from jarvis.tools import voyages as tool
from test_chat import ChatBase

CONFIG = """# Configuration
email:
  subject: "Vols Japon"

searches:
  - name: Japon 5-22 mai 2027
    # Départs : Barcelone ou France
    origins: [Paris, Lyon]
    destination: Japon
    alert_below: 700

  # - name: Corée juin 2027
  #   origins: [Paris]

google:
  max_requests: 150
"""
ARGS = {"destination": "Corée du Sud", "depart_from": "2027-06-01", "depart_to": "2027-06-30", "stay_days": "14, 10",
        "return_date": "", "origins": "Paris, Lyon", "alert_below": 650}
TODAY = date(2026, 10, 13)
SPEC = tool._spec  # vrai _spec, même quand CommitTest le remplace


def spec(**kw):
    return SPEC(**{**ARGS, **kw}, today=TODAY)


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, check=True, encoding="utf-8").stdout.strip()


class SpecTest(unittest.TestCase):
    def test_nominal(self):
        s = spec()
        self.assertEqual((s["name"], s["origins"], s["stays"], s["back"]), ("Corée du Sud 2027-06-01", ["Paris", "Lyon"], [10, 14], None))

    def test_entrees_invalides(self):
        for kw in ({"origins": "evil@mail.fr"}, {"destination": "x: y"}, {"origins": ""}, {"depart_from": "2026-10-13"},
                   {"depart_to": "2027-05-01"}, {"depart_to": "2028-12-01"}, {"return_date": "2027-07-10"},
                   {"stay_days": ""}, {"stay_days": "0"}, {"stay_days": "a"}, {"alert_below": -1},
                   {"stay_days": "", "return_date": "2027-06-15"}, {"depart_from": "demain"},
                   {"destination": "-rf"}, {"origins": "Paris, -x"}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                spec(**kw)

    def test_retour_fixe(self):
        self.assertEqual(spec(stay_days="", return_date="2027-07-10")["back"], date(2027, 7, 10))


class EditTest(unittest.TestCase):
    def test_nouvelle_recherche_en_tete_et_anciennes_commentees(self):
        out = tool.edit(CONFIG, spec())
        lines = out.splitlines()
        at = lines.index("searches:")
        self.assertEqual(lines[at + 1:at + 8], [
            '  - name: "Corée du Sud 2027-06-01"', '    origins: ["Paris", "Lyon"]', '    destination: "Corée du Sud"',
            "    depart_from: 2027-06-01", "    depart_to: 2027-06-30", "    stay_days: [10, 14]", "    alert_below: 650"])
        self.assertIn("  # - name: Japon 5-22 mai 2027", lines)
        self.assertIn("  #   origins: [Paris, Lyon]", lines)
        self.assertIn("    # Départs : Barcelone ou France", lines)  # commentaire gardé tel quel
        self.assertIn("  # - name: Corée juin 2027", lines)  # déjà en pause : inchangé
        self.assertEqual(lines[-2:], ["google:", "  max_requests: 150"])  # section suivante intacte

    def test_crlf_garde(self):
        self.assertNotIn("\n", tool.edit(CONFIG.replace("\n", "\r\n"), spec()).replace("\r\n", ""))

    def test_sans_section(self):
        with self.assertRaises(ValueError):
            tool.edit("email: {}\n", spec())


class CommitTest(unittest.TestCase):
    """Vrai git : dépôt « GitHub » nu, clone du propriétaire, second clone qui joue le workflow quotidien."""

    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.remote, self.clone, self.bot = base / "remote.git", base / "clone", base / "bot"
        git(base, "init", "--bare", "-b", "main", str(self.remote))
        git(base, "clone", "-q", str(self.remote), str(self.bot))
        (self.bot / "config.yaml").write_bytes(CONFIG.encode())
        git(self.bot, "add", "config.yaml")
        git(self.bot, "commit", "-qm", "init")
        git(self.bot, "push", "-q", "origin", "HEAD:main")
        git(base, "clone", "-q", str(self.remote), str(self.clone))
        (self.clone / "config.yaml").write_bytes(b"travail en cours du proprietaire\n")
        self.patches = [mock.patch.object(voyages, "GIT", ["git", "-c", "user.name=t", "-c", "user.email=t@t"]),  # file:// en test
                        mock.patch.object(voyages, "tracker_dir", return_value=self.clone),
                        mock.patch.object(tool, "_validate"),
                        mock.patch.object(tool, "_spec", lambda *a: spec())]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def bot_commit(self):
        (self.bot / "prices.csv").write_text("relevé\n", encoding="utf-8")
        git(self.bot, "add", "prices.csv")
        git(self.bot, "commit", "-qm", "data")
        git(self.bot, "push", "-q", "origin", "HEAD:main")

    def test_push_sur_main_sans_toucher_la_copie_de_travail(self):
        local = git(self.clone, "rev-parse", "main")
        self.bot_commit()  # le workflow a poussé depuis le clone : le fetch le rattrape
        answer = tool.voyage_destination(**ARGS)
        remote = git(self.remote, "show", "main:config.yaml")
        self.assertIn('  - name: "Corée du Sud 2027-06-01"', remote)
        self.assertIn("  # - name: Japon 5-22 mai 2027", remote)
        self.assertEqual(git(self.remote, "show", "main:prices.csv"), "relevé")  # commit du workflow gardé
        self.assertIn(git(self.remote, "rev-parse", "--short=7", "main"), answer)
        self.assertEqual((self.clone / "config.yaml").read_bytes(), b"travail en cours du proprietaire\n")
        self.assertEqual(git(self.clone, "rev-parse", "main"), local)

    def test_course_avec_le_workflow_rattrapee(self):
        real, pushes = voyages._git, []
        def racing(root, *args, **kw):
            if args[0] == "push" and not pushes:
                pushes.append(1)
                self.bot_commit()  # le workflow pousse entre notre fetch et notre push
            return real(root, *args, **kw)
        with mock.patch.object(voyages, "_git", racing):
            tool.voyage_destination(**ARGS)
        self.assertEqual(git(self.remote, "show", "main:prices.csv"), "relevé")
        self.assertIn("Corée du Sud", git(self.remote, "show", "main:config.yaml"))

    def test_validation_refusee_rien_pousse(self):
        before = git(self.remote, "rev-parse", "main")
        with mock.patch.object(tool, "_validate", side_effect=ValueError("configuration refusée")), self.assertRaises(ValueError):
            tool.voyage_destination(**ARGS)
        self.assertEqual(git(self.remote, "rev-parse", "main"), before)


class ValidateTest(unittest.TestCase):
    def test_sans_venv(self):
        with self.assertRaisesRegex(ValueError, "venv"):
            tool._validate(Path(tempfile.mkdtemp()), CONFIG)


class RouteTest(ChatBase):
    def test_outil_n2_bloque_apres_contenu_externe(self):
        t = REGISTRY["voyage_destination"]
        self.assertEqual((t.level, t.taint_blocked), (Level.N2, True))

    def test_plancher_n2_meme_abaisse(self):
        from jarvis.core import levels
        self.assertEqual(levels.floor(REGISTRY["voyage_destination"]), Level.N2)
        with self.assertRaises(ValueError):
            levels.set_level("voyage_destination", 1, strong_auth=True)

    def test_authentification_exigee(self):
        self.assertEqual(self.call("POST", "/api/voyages/destination", ARGS)[0], 401)

    def test_champs_invalides(self):
        self.assertEqual(self.call("POST", "/api/voyages/destination", {**ARGS, "alert_below": "650"}, token=self.token)[0], 422)

    def test_confirmation_puis_execution(self):
        for approve in (False, True):
            run = mock.Mock(return_value="fait")
            with mock.patch.dict(_registry, {"voyage_destination": dataclasses.replace(REGISTRY["voyage_destination"], run=run)}), \
                 mock.patch.object(tool, "date", mock.Mock(today=lambda: TODAY, fromisoformat=date.fromisoformat)):
                status, body, _ = self.call("POST", "/api/voyages/destination", ARGS, token=self.token)
                self.assertEqual(status, 202)
                p = self.pending(body["job"])
                self.assertIn("Corée du Sud 2027-06-01", p["preview"])
                self.decide(p["id"], approve)
                self.done(body["job"])
            self.assertEqual(run.call_count, int(approve))
            if approve:
                run.assert_called_once_with(**ARGS)


if __name__ == "__main__":
    unittest.main()
