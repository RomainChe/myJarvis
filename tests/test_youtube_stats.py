"""Stats YouTube : jeton lu sans fuite, droit manquant, historique SQLite, cache, panne sans détail."""
import json
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path

from jarvis.core import youtube_stats as y
from jarvis.core.social import with_youtube

TOKEN = {"scopes": [y.SCOPE], "client_id": "cid", "client_secret": "SECRET", "refresh_token": "RT"}


def token_file(tok=TOKEN):
    f = Path(tempfile.mkdtemp()) / "t.json"
    f.write_text(json.dumps(tok), encoding="utf-8")
    return f


def fake_api(calls):
    def post(url, form):
        calls.append((url, form))
        return {"access_token": "AT"}

    def get(url, access):
        calls.append((url, access))
        if "channels" in url:
            return {"items": [{"statistics": {"subscriberCount": "120", "viewCount": "5000", "videoCount": "9"}}]}
        return {"items": [{"id": "abcdefghijk", "statistics": {"viewCount": "42"}}]}
    return post, get


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


class FetchTest(unittest.TestCase):
    def test_nominal_et_identifiants_vers_l_url_fixe(self):
        calls = []
        post, get = fake_api(calls)
        channel, vids = y.fetch(token_file(), ["abcdefghijk", "x;y"], post, get)
        self.assertEqual((channel, vids), ({"subs": 120, "views": 5000, "videos": 9}, {"abcdefghijk": 42}))
        self.assertEqual(calls[0][0], y.TOKEN_URI)
        self.assertNotIn("x;y", calls[2][0])  # identifiant invalide jamais envoyé

    def test_uri_du_jeton_ignoree(self):
        calls = []
        post, get = fake_api(calls)
        y.fetch(token_file({**TOKEN, "token_uri": "https://evil.example/t"}), (), post, get)
        self.assertEqual(calls[0][0], y.TOKEN_URI)

    def test_droit_manquant(self):
        with self.assertRaises(y.Reconnect):
            y.fetch(token_file({**TOKEN, "scopes": ["autre"]}), (), *fake_api([]))

    def test_jeton_revoque(self):
        def revoked(url, form):
            raise urllib.error.HTTPError(url, 400, "invalid_grant", {}, None)
        with self.assertRaises(y.Reconnect):
            y.fetch(token_file(), (), revoked, None)

    def test_compteur_hors_bornes(self):
        with self.assertRaises(ValueError):
            y._count(-1)


class RecordTest(unittest.TestCase):
    def test_evolution(self):
        db = Path(tempfile.mkdtemp()) / "s.db"
        self.assertEqual(y.record(db, date(2026, 10, 1), {"subs": 100, "views": 1000, "videos": 5}), {"d7": None, "d30": None})
        out = y.record(db, date(2026, 10, 9), {"subs": 110, "views": 1500, "videos": 6})
        self.assertEqual(out, {"d7": {"subs": 10, "views": 500}, "d30": None})
        out = y.record(db, date(2026, 10, 9), {"subs": 112, "views": 1600, "videos": 6})  # même jour : remplacé
        self.assertEqual(out["d7"], {"subs": 12, "views": 600})
        old = y.record(db, date(2026, 12, 1), {"subs": 200, "views": 1, "videos": 6})  # relevés trop anciens : pas d'écart
        self.assertEqual(old, {"d7": None, "d30": None})


class ServiceTest(unittest.TestCase):
    def make(self, fetch_fn, clock=None, token=lambda: Path("x")):
        return y.YouTubeStats(token=token, fetch_fn=fetch_fn, db=Path(tempfile.mkdtemp()) / "s.db", clock=clock or Clock())

    def test_non_configure(self):
        self.assertIsNone(self.make(None, token=lambda: None).snapshot())

    def test_cache_15_min(self):
        calls, clock = [], Clock()
        s = self.make(lambda p, ids: calls.append(1) or ({"subs": 1, "views": 2, "videos": 3}, {}), clock)
        s.snapshot()
        clock.t = 600
        s.snapshot()
        self.assertEqual(len(calls), 1)
        clock.t = 901
        s.snapshot()
        self.assertEqual(len(calls), 2)

    def test_pannes_sans_detail(self):
        def boom(p, ids):
            raise OSError("jeton RT illisible")
        self.assertEqual(self.make(boom).snapshot(), {"error": "indisponible"})

        def denied(p, ids):
            raise y.Reconnect
        self.assertEqual(self.make(denied).snapshot(), {"error": "reconnexion"})

    def test_with_youtube_ajoute_les_vues(self):
        s = self.make(lambda p, ids: ({"subs": 1, "views": 2, "videos": 3}, {"abcdefghijk": 42}))
        snap = {"published": [{"platform": "youtube", "url": "https://youtu.be/abcdefghijk"}, {"platform": "tiktok", "url": None}]}
        out = with_youtube(snap, s)
        self.assertEqual(out["published"][0]["views"], 42)
        self.assertNotIn("video_views", out["youtube"])
        self.assertNotIn("views", out["published"][1])


if __name__ == "__main__":
    unittest.main()
