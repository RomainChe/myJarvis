"""scripts/update.py : redémarre le Core seulement si le commit a changé depuis le dernier déploiement."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import update


class UpdateTest(unittest.TestCase):
    def run_update(self, branch="main", head="b", pull_ok=True):
        def git(*a):
            if a[0] == "branch":
                return branch
            if a[0] == "pull" and not pull_ok:
                raise RuntimeError("conflit")
            return head
        restart = mock.Mock()
        with mock.patch.object(update, "git", git):
            return update.main(restart), restart

    def setUp(self):
        self.mark = Path(tempfile.mkdtemp()) / "deployed-head"
        patch = mock.patch.object(update, "MARK", self.mark)
        patch.start()
        self.addCleanup(patch.stop)

    def test_premier_passage_memorise_sans_redemarrer(self):
        done, restart = self.run_update()
        self.assertFalse(done)
        restart.assert_not_called()
        self.assertEqual(self.mark.read_text(), "b")

    def test_commit_inchange_pas_de_redemarrage(self):
        self.mark.write_text("b")
        self.assertFalse(self.run_update()[0])

    def test_nouveau_commit_redemarre(self):
        self.mark.write_text("a")
        done, restart = self.run_update()
        self.assertTrue(done)
        restart.assert_called_once()
        self.assertEqual(self.mark.read_text(), "b")

    def test_hors_main_rien(self):
        self.mark.write_text("a")
        done, restart = self.run_update(branch="feat/x")
        self.assertFalse(done)
        restart.assert_not_called()

    def test_pull_impossible_sans_nouveau_commit_ne_fait_rien(self):
        self.mark.write_text("b")
        self.assertFalse(self.run_update(pull_ok=False)[0])


if __name__ == "__main__":
    unittest.main()
