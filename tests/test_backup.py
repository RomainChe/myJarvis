import sqlite3
import tempfile
import unittest
from pathlib import Path

from jarvis.core.audit import Audit
import os
import time

from scripts.backup import ANCHOR, backup, check, verify


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

    def test_check_absente_puis_recente_puis_perimee(self):
        self.assertIn("aucune", check(self.dest))
        target = backup(self.src, self.dest, keep=3)
        self.assertIsNone(check(self.dest))
        old = time.time() - 26 * 3600
        os.utime(target, (old, old))
        self.assertIn("26 h", check(self.dest))

    def test_verify_copie_saine(self):
        backup(self.src, self.dest, keep=3)
        self.audit.log("cli", "volume", {"value": 40}, 1, "auto", 40)  # le journal a avancé : normal
        self.assertIsNone(verify(self.dest, self.src))

    def test_verify_detecte_un_journal_reecrit_depuis(self):
        backup(self.src, self.dest, keep=3)
        self.audit.db.execute("DROP TRIGGER IF EXISTS audit_no_update")
        self.audit.db.execute("UPDATE audit SET hash = 'x' WHERE id = 1")
        self.assertIn("ancrée", verify(self.dest, self.src))

    def test_verify_apres_archivage_du_journal(self):
        backup(self.src, self.dest, keep=3)
        self.assertEqual(self.audit.archive_before("9999", self.root / "arch"), 1)
        self.audit.log("cli", "volume", {}, 1, "auto", 1)
        self.assertIsNone(verify(self.dest, self.src))

    def test_verify_sans_ancre_ou_sans_copie(self):
        self.assertIn("aucune", verify(self.dest, self.src))
        backup(self.src, self.dest, keep=3)
        (self.dest / ANCHOR).unlink()
        self.assertIn(ANCHOR, verify(self.dest, self.src))


if __name__ == "__main__":
    unittest.main()
