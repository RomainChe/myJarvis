import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import fetch_models as fm

DATA = b"poids factices"
SHA = hashlib.sha256(DATA).hexdigest()
URL = "https://huggingface.co/x/y/resolve/abc/f.bin"


def _opener(payload, calls):
    def open_(req, timeout=None):
        calls.append(req.full_url)
        return io.BytesIO(payload)
    return mock.Mock(open=open_)


class FetchModelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest = Path(self.tmp.name) / "sub" / "f.bin"

    def test_telecharge_puis_ne_retelecharge_pas(self):
        calls = []
        with mock.patch.object(fm, "_opener", _opener(DATA, calls)):
            self.assertEqual(fm.fetch(URL, self.dest, len(DATA), SHA), "téléchargé")
            self.assertEqual(fm.fetch(URL, self.dest, len(DATA), SHA), "ok")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.dest.read_bytes(), DATA)

    def test_hash_different_refuse_et_rien_ne_reste(self):
        with mock.patch.object(fm, "_opener", _opener(b"corrompu!!!!!!", [])):
            with self.assertRaises(ValueError):
                fm.fetch(URL, self.dest, len(DATA), SHA)
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.dest.with_name("f.bin.part").exists())

    def test_fichier_local_corrompu_est_retelecharge(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(b"abime")
        with mock.patch.object(fm, "_opener", _opener(DATA, [])):
            self.assertEqual(fm.fetch(URL, self.dest, len(DATA), SHA), "téléchargé")
        self.assertEqual(self.dest.read_bytes(), DATA)

    def test_hotes_et_schemas_refuses(self):
        for u in ("http://huggingface.co/a", "https://evil.example/a", "https://huggingface.co.evil.net/a",
                  "ftp://github.com/a", "file:///etc/passwd"):
            self.assertFalse(fm.host_ok(u), u)
            with self.assertRaises(ValueError):
                fm.fetch(u, self.dest, 1, SHA)
        self.assertTrue(fm.host_ok("https://cas-bridge.xethub.hf.co/x?sig=1"))

    def test_redirection_hors_liste_blanche_refusee(self):
        h = fm._Redirect()
        with self.assertRaises(OSError):
            h.redirect_request(mock.Mock(), None, 302, "", {}, "http://huggingface.co/a")

    def test_manifeste_commite_est_coherent(self):
        files = json.loads((fm.ROOT / "models" / "MANIFEST.json").read_text(encoding="utf-8"))["files"]
        self.assertTrue(files)
        for e in files:
            self.assertTrue(fm.host_ok(e["url"]), e["url"])
            self.assertRegex(e["sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("/main/", e["url"])
            self.assertNotIn("..", e["path"])
            self.assertTrue(e["licence"])


if __name__ == "__main__":
    unittest.main()
