"""Hook garde des branches (.claude/hooks/garde_branches.py) : deux sessions, deux worktrees, aucun mélange."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "garde_branches.py"
spec = importlib.util.spec_from_file_location("garde_branches", HOOK)
garde = importlib.util.module_from_spec(spec)
spec.loader.exec_module(garde)


def run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class GardeBranchesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.main, self.a, self.b = str(root / "repo"), str(root / "wt-a"), str(root / "wt-b")
        run(root, "init", "-q", "-b", "main", self.main)
        for k, v in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
            run(self.main, "config", k, v)
        run(self.main, "commit", "-q", "--allow-empty", "-m", "base")
        for path, branch in ((self.a, "a"), (self.b, "b")):
            run(self.main, "worktree", "add", "-q", "-b", branch, path)
            run(path, "commit", "-q", "--allow-empty", "-m", f"travail {branch}")

    def test_commit_et_push_normaux_passent(self):
        self.assertIsNone(garde.check("git add -A && git commit -m 'merge b dans le message'", self.a))
        self.assertIsNone(garde.check("git push -u origin a", self.a))
        self.assertIsNone(garde.check("git push origin main", self.a))

    def test_merge_d_une_autre_session_bloque(self):
        self.assertIn("commits de b", garde.check("git merge b", self.a))
        self.assertIn("commits de b", garde.check("git -C ../wt-a merge --no-ff -m x b", self.b))

    def test_merge_dans_main_autorise(self):
        self.assertIsNone(garde.check("git merge --no-ff b", self.main))

    def test_commit_sur_branche_deja_contaminee_bloque(self):
        run(self.a, "merge", "-q", "--no-edit", "b")
        self.assertIn("contient déjà des commits de b", garde.check("git commit -m suite", self.a))

    def test_push_d_une_branche_extraite_ailleurs_bloque(self):
        self.assertIn("extraite dans un autre worktree", garde.check("git push origin HEAD:b", self.a))

    def test_suppression_distante_autorisee(self):
        self.assertIsNone(garde.check("git push origin --delete b", self.a))
        self.assertIsNone(garde.check("git push -d origin b", self.a))
        self.assertIsNone(garde.check("git push origin :b", self.a))

    def test_hook_code_2_et_raison(self):
        event = json.dumps({"tool_input": {"command": "git merge b"}, "cwd": self.a})
        r = subprocess.run([sys.executable, str(HOOK)], input=event, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Garde des branches", r.stderr)
        event = json.dumps({"tool_input": {"command": "ls"}, "cwd": self.a})
        self.assertEqual(subprocess.run([sys.executable, str(HOOK)], input=event, capture_output=True, text=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
