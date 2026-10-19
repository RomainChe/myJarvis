"""Inventaire des branches (scripts/etat_branches.py) : chaque état reconnu sur un vrai dépôt temporaire."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "etat_branches.py"
spec = importlib.util.spec_from_file_location("etat_branches", SCRIPT)
etat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(etat)


def run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def commit(cwd, name, text, msg):
    Path(cwd, name).write_text(text, encoding="utf-8")
    run(cwd, "add", name)
    run(cwd, "commit", "-q", "-m", msg)


class EtatBranchesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo, origin = str(self.root / "repo"), str(self.root / "origin.git")
        run(self.root, "init", "-q", "--bare", "-b", "main", origin)
        run(self.root, "init", "-q", "-b", "main", self.repo)
        for k, v in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
            run(self.repo, "config", k, v)
        commit(self.repo, "f.txt", "base\n", "base")
        run(self.repo, "remote", "add", "origin", origin)
        run(self.repo, "push", "-q", "-u", "origin", "main")

    def wt(self, branch):
        path = str(self.root / ".claude" / "worktrees" / branch)
        run(self.repo, "worktree", "add", "-q", "-b", branch, path)
        return path

    def branche(self, name):
        return next(b for b in etat.inventaire(self.repo)["branches"] if b["nom"] == name)

    def test_neuve_et_fusionnee(self):
        self.wt("neuve")
        path = self.wt("finie")
        commit(path, "g.txt", "x\n", "travail")
        run(self.repo, "merge", "-q", "--no-ff", "-m", "fusion", "finie")
        self.assertEqual(self.branche("neuve")["etats"], ["neuve"])
        self.assertEqual(self.branche("finie")["etats"], ["fusionnee"])

    def test_en_retard_avec_conflit_et_non_poussee(self):
        path = self.wt("vieille")
        commit(path, "f.txt", "branche\n", "branche")
        commit(self.repo, "f.txt", "main\n", "main avance")
        b = self.branche("vieille")
        self.assertEqual((b["avance"], b["retard"]), (1, 1))
        self.assertIn("en_retard", b["etats"])
        self.assertIn("non_poussee", b["etats"])
        self.assertEqual(b["conflit_main"], ["f.txt"])

    def test_squash(self):
        path = self.wt("sq")
        commit(path, "g.txt", "x\n", "travail")
        run(self.repo, "merge", "-q", "--squash", "sq")
        run(self.repo, "commit", "-q", "-m", "squash")
        self.assertIn("squash", self.branche("sq")["etats"])

    def test_bloquee_par_merge_en_cours(self):
        path = self.wt("bloc")
        commit(path, "f.txt", "branche\n", "branche")
        commit(self.repo, "f.txt", "main\n", "main avance")
        subprocess.run(["git", "merge", "main"], cwd=path, capture_output=True)
        self.assertIn("bloquee", self.branche("bloc")["etats"])

    def test_orpheline_et_poussee(self):
        path = self.wt("pub")
        commit(path, "g.txt", "x\n", "travail")
        run(path, "push", "-q", "-u", "origin", "pub")
        self.assertNotIn("non_poussee", self.branche("pub")["etats"])
        run(self.repo, "push", "-q", "origin", "main:vieille-distante")
        run(self.repo, "fetch", "-q", "origin")
        self.assertIn({"nom": "vieille-distante", "fusionnee": True}, etat.inventaire(self.repo)["orphelines"])

    def test_contamination_et_conflit_entre_sessions(self):
        a, b = self.wt("a"), self.wt("b")
        commit(a, "f.txt", "a\n", "travail a")
        commit(b, "f.txt", "b\n", "travail b")
        inv = etat.inventaire(self.repo)
        self.assertEqual(inv["conflits"], [{"a": "a", "b": "b", "fichiers": ["f.txt"]}])
        self.assertEqual(inv["contamination"], [])
        subprocess.run(["git", "merge", "--no-edit", "-X", "theirs", "b"], cwd=a, capture_output=True)
        self.assertEqual(etat.inventaire(self.repo)["contamination"], [["a", "b"]])

    def test_principal_hors_convention(self):
        run(self.repo, "worktree", "add", "-q", "-b", "ailleurs", str(self.root / "ailleurs"))
        inv = etat.inventaire(self.repo)
        self.assertEqual(inv["principal"]["vs_origin"], {"avance": 0, "retard": 0})
        self.assertTrue(next(w for w in inv["worktrees"] if w["branche"] == "ailleurs")["hors_convention"])


if __name__ == "__main__":
    unittest.main()
