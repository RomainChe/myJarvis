"""Onglet Réseaux : lecture des fichiers de lol-clipper, valeurs hostiles ignorées, route authentifiée."""
import json
import tempfile
import unittest
from pathlib import Path

from jarvis.core import social
from tests.test_server import ServerBase


def make(files: dict) -> Path:
    root = Path(tempfile.mkdtemp())
    for name, content in files.items():
        f = root / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return root


class SocialTest(unittest.TestCase):
    def test_nominal(self):
        root = make({
            "Montage/a_compilation.youtube.json": {"id": "x", "url": "https://youtu.be/x", "privacy": "public"},
            "Parties/b.tiktok.json": {"url": "https://www.tiktok.com/@u/video/1"},
            "Montage/c.publish.todo": {"video": "c.mp4", "only": "tiktok", "publish_at": "2026-10-09T18:00:00"},
            "Montage/d.publish.todo": {"video": "d.mp4", "only": None, "publish_at": "2026-10-09T12:00:00"},
        })
        s = social.snapshot(root)
        self.assertTrue(s["configured"])
        self.assertEqual({(r["platform"], r["title"]) for r in s["published"]}, {("youtube", "a_compilation"), ("tiktok", "b")})
        self.assertEqual([(r["platform"], r["at"]) for r in s["scheduled"]],
                         [("all", "2026-10-09T12:00"), ("tiktok", "2026-10-09T18:00")])

    def test_lien_hors_plateforme_et_fichier_invalide_ignores(self):
        root = make({
            "Montage/a.youtube.json": {"url": "javascript:alert(1)", "privacy": "<b>x</b>"},
            "Montage/b.youtube.json": "pas du json",
            "Montage/c.tiktok.json": '["liste"]',
            "Montage/d.publish.todo": {"publish_at": "demain"},
            "Montage/e.youtube.json": {"url": "https://evil.example/x"},
        })
        s = social.snapshot(root)
        self.assertEqual({(r["title"], r["url"], r["privacy"]) for r in s["published"]}, {("a", None, None), ("e", None, None)})
        self.assertEqual(s["scheduled"], [])

    def test_dossier_absent(self):
        self.assertEqual(social.snapshot(Path(tempfile.mkdtemp()) / "nope"), {"configured": False, "published": [], "scheduled": []})

    def test_config_locale(self):
        tmp = make({"social.json": {"clips_dir": "D:/x"}})
        self.assertEqual(social.clips_dir(tmp / "social.json"), Path("D:/x"))
        self.assertEqual(social.clips_dir(tmp / "absent.json"), social.DEFAULT_DIR)


class SocialRouteTest(ServerBase):
    def test_authentification_exigee_et_forme(self):
        self.assertEqual(self.call("GET", "/api/social")[0], 401)
        _, token = self.enroll()
        status, body, _ = self.call("GET", "/api/social", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"configured", "published", "scheduled", "youtube"})


if __name__ == "__main__":
    unittest.main()
