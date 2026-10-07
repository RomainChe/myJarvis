import sqlite3
import tempfile
import unittest
from pathlib import Path

from jarvis.core.audit import Audit
from scripts.backup import backup


class BackupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src = self.root / "jarvis.db"
        self.dest = self.root / "backups"
        self.audit = Audit(str(self.src))  # connexion ouverte : copie à chaud
        self.addCleanup(self.audit.db.close)
        self.audit.log("cli", "volume", {"value": 30}, 1, "auto", 30)

    def test_copie_a_chaud_contient_le_journal_et_ses_triggers(self):
        target = backup(self.src, self.dest, keep=3)
        db = sqlite3.connect(target)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("SELECT tool, decision FROM audit").fetchall(), [("volume", "auto")])
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("DELETE FROM audit")

    def test_rotation_garde_les_n_plus_recentes(self):
        targets = [backup(self.src, self.dest, keep=2) for _ in range(4)]
        self.assertEqual(sorted(self.dest.glob("jarvis-*.db")), targets[-2:])

    def test_rotation_ignore_les_autres_fichiers(self):
        self.dest.mkdir()
        other = self.dest / "notes.txt"
        other.write_text("x")
        backup(self.src, self.dest, keep=1)
        self.assertTrue(other.exists())

    def test_source_absente_ne_cree_rien(self):
        with self.assertRaises(FileNotFoundError):
            backup(self.root / "absente.db", self.dest, keep=3)
        self.assertFalse((self.root / "absente.db").exists())
        self.assertFalse(self.dest.exists())

    def test_keep_invalide_refuse(self):
        with self.assertRaises(ValueError):
            backup(self.src, self.dest, keep=0)
        self.assertFalse(self.dest.exists())


if __name__ == "__main__":
    unittest.main()
