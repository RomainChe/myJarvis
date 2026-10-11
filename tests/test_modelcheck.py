import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import modelcheck

DATA = b"poids factices"
SHA = hashlib.sha256(DATA).hexdigest()


class ModelCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.file = self.dir / "m.bin"
        self.file.write_bytes(DATA)
        modelcheck._verified.clear()

    def test_fichier_inchange_pas_rehache(self):
        self.assertTrue(modelcheck.is_good(self.file, len(DATA), SHA))
        with mock.patch.object(modelcheck, "sha256_of", side_effect=AssertionError("re-haché")):
            self.assertTrue(modelcheck.is_good(self.file, len(DATA), SHA))

    def test_fichier_remplace_apres_verification_refuse(self):
        self.assertTrue(modelcheck.is_good(self.file, len(DATA), SHA))
        self.file.write_bytes(b"x" * len(DATA))  # même taille, contenu différent
        st = self.file.stat()
        os.utime(self.file, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
        self.assertFalse(modelcheck.is_good(self.file, len(DATA), SHA))
        self.assertFalse(modelcheck.is_good(self.file, len(DATA), SHA))  # l'échec n'est pas mémorisé comme un succès

    def test_taille_fausse_ou_absent(self):
        self.assertFalse(modelcheck.is_good(self.file, len(DATA) + 1, SHA))
        self.assertFalse(modelcheck.is_good(self.dir / "absent.bin", 1, SHA))

    def test_check_manifest_signale_les_fichiers_presents_modifies(self):
        (self.dir / "ok.bin").write_bytes(DATA)
        (self.dir / "mauvais.bin").write_bytes(b"autre contenu")
        manifest = self.dir / "MANIFEST.json"
        manifest.write_text(json.dumps({"files": [
            {"path": "ok.bin", "size": len(DATA), "sha256": SHA},
            {"path": "mauvais.bin", "size": len(DATA), "sha256": SHA},
            {"path": "absent.bin", "size": 1, "sha256": SHA}]}), encoding="utf-8")
        self.assertEqual(modelcheck.check_manifest(manifest, self.dir), ["mauvais.bin"])


if __name__ == "__main__":
    unittest.main()
