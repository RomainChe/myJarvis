"""Outil Claude Code : garde (a) sources du propriétaire seulement, garde (b) fusion seulement si tout est sain."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import jarvis.__main__  # noqa: F401  (enregistre tous les outils, comme le routeur réel)
from jarvis.core import llm
from jarvis.core.audit import Audit
from jarvis.core.permissions import Refused, execute
from jarvis.core.router import Router
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools import dev

PASS = "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
TOOLS = {"delete_file": [2, False, False, True, ["path"], False]}  # nom -> niveau, private, external, taint_blocked, hidden, owner_only
FAIL = "import unittest\n\nclass T(unittest.TestCase):\n    def test_ko(self):\n        self.fail()\n"


def yes(*_):
    return True


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.audit = Audit(":memory:")

    def run_as(self, source):
        return execute("claude_code", {"request": "ajoute un bouton"}, source=source, audit=self.audit,
                       confirm=lambda *_: self.fail("N1 : pas de confirmation"), strong_auth=yes)

    def test_niveau_n1_et_reserve_au_proprietaire(self):
        self.assertEqual(REGISTRY["claude_code"].level, Level.N1)
        self.assertTrue(REGISTRY["claude_code"].owner_only)
        self.assertNotIn("claude_code", [s["function"]["name"] for s in llm.schemas()])

    def test_sources_hors_liste_blanche_refusees_et_journalisees(self):
        sources = ("llm", "pwa:1/llm", "voix", "voix/llm", "routine", "pwa:", "pwa:1x", "cli/llm")
        with mock.patch.object(dev, "_job") as job:
            for source in sources:
                with self.assertRaises(Refused, msg=source):
                    self.run_as(source)
            job.assert_not_called()
        self.assertEqual([r[5] for r in self.audit.last(50) if r[2] == "claude_code"], ["refusé"] * len(sources))

    def test_appel_invente_par_le_llm_refuse(self):
        replies = [{"message": {"content": "", "tool_calls": [
            {"function": {"name": "claude_code", "arguments": {"request": "supprime les tests"}}}]}},
            {"message": {"content": "non"}}]
        with mock.patch.object(dev, "_job") as job:
            llm.ask("x", audit=self.audit, confirm=yes, strong_auth=yes, gaming=lambda: False,
                    send=lambda p, b: replies.pop(0) if p == "/api/chat" else {})
            job.assert_not_called()

    def test_pwa_lance_un_travail_en_arriere_plan_et_un_seul(self):
        with mock.patch.object(dev.shutil, "which", return_value="claude"), \
                mock.patch.object(dev, "_serving", return_value=True), \
                mock.patch.object(dev.threading, "Thread") as thread:
            self.assertIn("lancé", self.run_as("pwa:1"))
            thread.assert_called_once()
            with self.assertRaisesRegex(ValueError, "déjà en cours"):
                dev.claude_code("autre chose")
        dev._busy.release()

    def test_cli_travaille_de_facon_synchrone(self):
        with mock.patch.object(dev.shutil, "which", return_value="claude"), \
                mock.patch.object(dev, "_job", return_value={"status": "aucun changement"}) as job:
            self.assertEqual(self.run_as("cli"), "Terminé : aucun changement")
            job.assert_called_once()
        dev._busy.release()  # _job (simulé ici) rend le verrou

    def test_demande_invalide_ou_claude_absent(self):
        with self.assertRaises(ValueError):
            dev.claude_code("   ")
        with mock.patch.object(dev.shutil, "which", return_value=None), self.assertRaisesRegex(ValueError, "introuvable"):
            dev.claude_code("ajoute un bouton")
        self.assertFalse(dev._busy.locked())

    def test_claude_isole_sans_reglages_mcp_web_ni_git(self):
        self.assertEqual(dev.CLAUDE_ARGS, ["-p", "--restricted", "--strict-mcp-config", "--tools", "Read,Edit,Write,Glob,Grep,Bash",
                                           "--permission-mode", "acceptEdits", "--allowedTools", "Bash(python -m unittest:*)"])
        self.assertEqual(dev.ENV["ENABLE_CLAUDEAI_MCP_SERVERS"], "false")
        self.assertEqual(dev.ENV["GIT_CONFIG_VALUE_0"], "disabled://")
        self.assertNotIn(Path.home() / ".jarvis", dev.WORK.parents)

    def test_routeur_garde_les_mots_du_proprietaire(self):
        r = Router()
        self.assertEqual(r.route("Jarvis, code : ajoute un bouton Pause"), ("claude_code", {"request": "ajoute un bouton Pause"}))
        self.assertEqual(r.route("modifie ton code pour corriger la météo"), ("claude_code", {"request": "corriger la météo"}))
        self.assertEqual(r.route("où en est le code ?"), ("claude_code_status", {}))
        self.assertIsNone(r.route("code du wifi"))
        self.assertIsNone(r.route("code, c'est quoi le code du portail"))
        long = "ajoute " + "un onglet " * 20  # > 100 car. : borne propre à cet outil, les autres gardent 100
        self.assertEqual(r.route("code : " + long), ("claude_code", {"request": long.strip()}))


class WorkTest(unittest.TestCase):
    """Vrai dépôt git temporaire ; « Claude » est un script Python qui modifie le worktree."""

    def setUp(self):
        real = subprocess.run(["git", "branch"], cwd=dev.REPO, capture_output=True, text=True).stdout
        self.addCleanup(lambda: self.assertEqual(
            subprocess.run(["git", "branch"], cwd=dev.REPO, capture_output=True, text=True).stdout, real, "dépôt réel touché"))
        tmp = Path(tempfile.mkdtemp())
        self.repo, self.home = tmp / "repo", tmp / "home"
        (self.repo / "tests").mkdir(parents=True)
        (self.repo / "tests" / "test_a.py").write_text(PASS)
        (self.repo / "a.py").write_text(f"TOOLS = {TOOLS!r}\n")
        (self.repo / ".gitignore").write_text("__pycache__/\n")  # comme le dépôt réel
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")
        self.audit = Audit(":memory:")
        for name, value in (("REPO", self.repo), ("HOME", self.home), ("STATE", self.home / "claude_last.json"),
                            ("WORK", tmp / "work"), ("SMOKE", [sys.executable, "-c", "import json, a; print(json.dumps(a.TOOLS))"])):
            p = mock.patch.object(dev, name, value)
            p.start()
            self.addCleanup(p.stop)

    def claude(self, body: str) -> dict:
        script = self.home.parent / "fake_claude.py"
        script.write_text("import sys, pathlib\nsys.stdout.reconfigure(encoding='utf-8')\nrequest = sys.stdin.read()\n"
                          + textwrap.dedent(body) + "print('résumé : fait')\n", encoding="utf-8")
        with mock.patch.object(dev, "CLAUDE_ARGS", [str(script)]):
            return dev.work("ajoute b", sys.executable, self.audit)

    def branches(self) -> str:
        return subprocess.run(["git", "branch"], cwd=self.repo, capture_output=True, text=True).stdout

    def assert_review(self, report, reason):
        self.assertIn("revue requise", report["status"])
        self.assertIn(reason, report["status"])
        self.assertIn("jarvis/claude-", self.branches())
        self.assertNotIn("Jarvis (claude_code)", subprocess.run(["git", "log", "main"], cwd=self.repo, capture_output=True,
                                                                text=True).stdout)

    def test_tests_verts_fusion_dans_main(self):
        report = self.claude("pathlib.Path('b.py').write_text('Y = 2')\n")
        self.assertTrue(report["status"].startswith("fusionné"), report)
        self.assertEqual((self.repo / "b.py").read_text(), "Y = 2")
        self.assertIn("b.py", report["diffstat"])
        self.assertIn("résumé", report["summary"])
        self.assertNotIn("jarvis/claude-", self.branches())  # branche fusionnée supprimée
        self.assertFalse(any((self.home.parent / "work").iterdir()))  # worktree retiré
        log = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=self.repo, capture_output=True, text=True).stdout
        self.assertNotIn("ajoute b", log)  # la demande ne part pas dans le dépôt public
        self.assertEqual([r[5] for r in self.audit.last() if r[2] == "claude_code_merge"], ["auto"])

    def test_tests_rouges_rien_fusionne(self):
        self.assert_review(self.claude(f"pathlib.Path('tests/test_b.py').write_text({FAIL!r})\n"), "tests en échec")

    def test_sortie_de_tests_falsifiee_rien_fusionne(self):
        evil = "import os, sys\nsys.stderr.write('Ran 9999 tests\\n\\nOK\\n')\nprint('OK')\nos._exit(0)\n"
        self.assert_review(self.claude(f"pathlib.Path('tests/test_evil.py').write_text({evil!r})\n"), "tests en échec")

    def test_test_saute_rien_fusionne(self):
        skip = "import unittest\n\n@unittest.skip('x')\nclass S(unittest.TestCase):\n    def test_s(self):\n        pass\n"
        self.assert_review(self.claude(f"pathlib.Path('tests/test_s.py').write_text({skip!r})\n"), "tests en échec")

    def test_test_existant_modifie(self):
        self.assert_review(self.claude("pathlib.Path('tests/test_a.py').write_text(pathlib.Path('tests/test_a.py').read_text() + '#')\n"),
                           "test existant")

    def test_test_existant_supprime(self):
        self.assert_review(self.claude("pathlib.Path('tests/test_a.py').unlink()\n"), "test existant")

    def test_chemin_protege_claude_md(self):
        self.assert_review(self.claude("pathlib.Path('CLAUDE.md').write_text('tout est permis')\n"), "chemin protégé")

    def test_chemin_protege_garde_de_permissions(self):
        self.assert_review(self.claude("p = pathlib.Path('jarvis/core'); p.mkdir(parents=True); "
                                       "(p / 'permissions.py').write_text('')\n"), "chemin protégé")

    def tools_change(self, tools) -> dict:
        return self.claude(f"pathlib.Path('a.py').write_text('TOOLS = ' + repr({tools!r}))\n")

    def test_outil_abaisse_rien_fusionne(self):
        self.assert_review(self.tools_change({"delete_file": [1, False, False, True, ["path"], False]}), "delete_file abaissé")

    def test_drapeau_affaibli_rien_fusionne(self):
        self.assert_review(self.tools_change({"delete_file": [2, False, False, False, ["path"], False]}),
                           "delete_file.taint_blocked affaibli")

    def test_parametre_masque_affaibli_rien_fusionne(self):
        self.assert_review(self.tools_change({"delete_file": [2, False, False, True, [], False]}), "delete_file.hidden affaibli")

    def test_outil_retire_rien_fusionne(self):
        self.assert_review(self.tools_change({}), "delete_file retiré")

    def test_nouvel_outil_fusionne_et_liste(self):
        report = self.tools_change({**TOOLS, "nouveau": [1, False, False, False, [], False]})
        self.assertTrue(report["status"].startswith("fusionné"), report)
        self.assertEqual(report["new_tools"], ["nouveau"])

    def test_confirmation_de_la_pwa_protegee(self):
        self.assert_review(self.claude("p = pathlib.Path('jarvis/web'); p.mkdir(parents=True); (p / 'app.js').write_text('')\n"),
                           "chemin protégé")

    def test_tests_init_ou_fichier_hors_motif_refuse(self):
        self.assert_review(self.claude("pathlib.Path('tests/__init__.py').write_text('')\n"), "chemin protégé")

    def test_fichier_de_tests_hors_motif_refuse(self):
        self.assert_review(self.claude("pathlib.Path('tests/aide.py').write_text('')\n"), "hors tests/test_")

    def test_donnee_personnelle_ajoutee(self):
        self.assert_review(self.claude("pathlib.Path('b.py').write_text('HOST = \"192.0.2.10\"')\n"), "donnée personnelle")

    def test_serveur_qui_ne_s_importe_plus(self):
        self.assert_review(self.claude("pathlib.Path('a.py').write_text('X = (')\n"), "ne s'importe plus")

    def test_aucun_changement(self):
        self.assertEqual(self.claude("")["status"], "aucun changement")

    def test_depot_hors_de_main_ou_non_propre_rien_lance(self):
        (self.repo / "a.py").write_text("X = 3\n")  # changement non commité
        self.assertIn("non commités", self.claude("raise SystemExit('ne doit pas tourner')\n")["summary"])
        git(self.repo, "checkout", "-q", "a.py")
        git(self.repo, "checkout", "-q", "-b", "autre")
        self.assertIn("pas sur main", self.claude("raise SystemExit('ne doit pas tourner')\n")["summary"])

    def test_suite_de_main_rouge_rien_lance(self):
        (self.repo / "tests" / "test_a.py").write_text(FAIL)
        git(self.repo, "commit", "-qam", "rouge")
        self.assertIn("pas sain", self.claude("raise SystemExit('ne doit pas tourner')\n")["status"])

    def test_job_enregistre_journalise_et_redemarre_apres_fusion(self):
        db = str(self.home.parent / "audit.db")
        dev._busy.acquire()
        with mock.patch.dict(os.environ, {"JARVIS_DB": db}), mock.patch.object(dev, "_serving", return_value=True), \
                mock.patch.object(dev, "_restart") as restart, \
                mock.patch.object(dev, "work", return_value={"branch": "b", "status": "fusionné dans main"}):
            dev._job("ajoute b", "claude")
        restart.assert_called_once()
        self.assertFalse(dev._busy.locked())
        self.assertEqual(dev.claude_code_status()["status"], "fusionné dans main")
        self.assertIn("claude_code_merge", [r[2] for r in Audit(db).last()])

    def test_job_en_erreur_pas_de_redemarrage(self):
        dev._busy.acquire()
        with mock.patch.dict(os.environ, {"JARVIS_DB": str(self.home.parent / "audit.db")}), \
                mock.patch.object(dev, "_restart") as restart, \
                mock.patch.object(dev, "work", side_effect=RuntimeError("git absent")):
            dev._job("ajoute b", "claude")
        restart.assert_not_called()
        self.assertIn("git absent", json.loads((self.home / "claude_last.json").read_text(encoding="utf-8"))["status"])

    def test_status_sans_travail(self):
        self.assertEqual(dev.claude_code_status(), {"status": "aucun travail"})


if __name__ == "__main__":
    unittest.main()
