import json
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jarvis.core import audit as audit_mod, retention
from jarvis.core.audit import Audit

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


def old(path: Path, days: int):
    t = NOW.timestamp() - days * 86400
    os.utime(path, (t, t))


class RetentionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.audit = Audit(str(self.root / "jarvis.db"))
        self.addCleanup(self.audit.db.close)

    def log_at(self, days_ago: int, n: int = 1):
        """Lignes datées dans le passé : on fixe l'horloge du module le temps de l'écriture."""
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW - timedelta(days=days_ago)
        real, audit_mod.datetime = audit_mod.datetime, Clock
        try:
            for i in range(n):
                self.audit.log("cli", "volume", {"v": i}, 1, "auto", i)
        finally:
            audit_mod.datetime = real

    def test_fichiers_perimes_supprimes_et_recents_gardes(self):
        d = self.root / "captures"
        d.mkdir()
        for name, age in (("capture-a.png", 8), ("capture-b.png", 6), ("notes.txt", 400)):
            (d / name).write_bytes(b"x")
            old(d / name, age)
        n = retention.purge_dir(d, "capture-*.png", 7, NOW.timestamp())
        self.assertEqual(n, 1)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["capture-b.png", "notes.txt"])

    def test_dry_run_ne_supprime_rien(self):
        f = self.root / "veille-1.eml"
        f.write_bytes(b"x")
        old(f, 200)
        self.assertEqual(retention.purge_dir(self.root, "veille-*.eml", 120, NOW.timestamp(), dry=True), 1)
        self.assertTrue(f.exists())

    def test_dossier_absent_ou_social_absent(self):
        self.assertEqual(retention.purge_dir(self.root / "rien", "*.png", 7), 0)
        self.assertEqual(retention.purge_social(self.root / "social.db", 365), 0)

    def test_social_purge_les_vieux_releves(self):
        db = self.root / "social.db"
        cx = sqlite3.connect(db)
        cx.execute("CREATE TABLE yt (day TEXT PRIMARY KEY, subs INT, views INT, videos INT)")
        cx.executemany("INSERT INTO yt VALUES (?,1,1,1)", [("2025-01-01",), ("2026-10-10",)])
        cx.commit()
        cx.close()
        self.assertEqual(retention.purge_social(db, 365, NOW.date()), 1)
        cx = sqlite3.connect(db)
        self.addCleanup(cx.close)
        self.assertEqual(cx.execute("SELECT day FROM yt").fetchall(), [("2026-10-10",)])

    def test_archivage_garde_la_chaine_verifiable(self):
        self.log_at(400, 3)
        self.log_at(1, 2)
        dest = self.root / "arch"
        cutoff = (NOW - timedelta(days=365)).isoformat(timespec="seconds")
        self.assertEqual(self.audit.archive_before(cutoff, dest), 3)
        self.assertTrue(self.audit.verify())
        self.assertEqual(self.audit.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 2)
        seg = next(dest.glob("audit-*.jsonl"))
        self.assertEqual(len(seg.read_text(encoding="utf-8").splitlines()), 3)
        self.assertEqual(json.loads(seg.read_text().splitlines()[0])[0], 1)
        self.audit.log("cli", "volume", {}, 1, "auto", 0)  # le journal continue après la purge
        self.assertTrue(self.audit.verify())

    def test_triggers_toujours_en_place_apres_archivage(self):
        self.log_at(400, 1)
        self.audit.archive_before(NOW.isoformat(), self.root / "arch")
        with self.assertRaises(sqlite3.IntegrityError):
            self.audit.db.execute("DELETE FROM audit_checkpoint")
        self.log_at(1, 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.audit.db.execute("DELETE FROM audit")

    def test_chaine_rompue_refuse_l_archivage(self):
        self.log_at(400, 2)
        self.audit.db.execute("DROP TRIGGER audit_no_update")
        self.audit.db.execute("UPDATE audit SET tool = 'x' WHERE id = 1")
        with self.assertRaises(RuntimeError):
            self.audit.archive_before(NOW.isoformat(), self.root / "arch")
        self.assertEqual(self.audit.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 2)
        self.assertFalse((self.root / "arch").exists())

    def test_rien_a_archiver(self):
        self.log_at(1, 2)
        self.assertEqual(self.audit.archive_before(
            (NOW - timedelta(days=365)).isoformat(), self.root / "arch"), 0)
        self.assertFalse((self.root / "arch").exists())

    def test_run_complet(self):
        cap, fin, vei = (self.root / n for n in ("cap", "fin", "vei"))
        for d, name, age in ((cap, "capture-1.png", 9), (fin, "semaine-2026-01.eml", 130),
                             (vei, "veille-2026-01.eml", 130), (vei, "veille-2026-40.eml", 5)):
            d.mkdir(exist_ok=True)
            (d / name).write_bytes(b"x")
            old(d / name, age)
        self.log_at(400, 2)
        out = retention.run(self.audit, now=NOW, archive_dir=self.root / "arch", captures=(cap,),
                            finance=fin, veille=vei, social=self.root / "social.db")
        self.assertEqual(out, {"captures": 1, "finance": 1, "veille": 1, "social": 0, "audit": 2})
        self.assertEqual([p.name for p in vei.iterdir()], ["veille-2026-40.eml"])


if __name__ == "__main__":
    unittest.main()
