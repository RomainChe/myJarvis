"""Planning lol-clipper : lecture N0 et report N2 (seul `publish_at` change, titre exact, créneau libre, futur borné)."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from jarvis.core import social
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools import social as tools


def when(days=1, hour=18) -> str:
    return (datetime.now() + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


class SocialToolsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "Montage").mkdir()
        (self.root / "Parties").mkdir()
        self.a = self.todo("Montage", "clip_a", when(1, 12), only="tiktok")
        self.todo("Parties", "partie_b", when(2, 12))
        p = mock.patch.object(social, "clips_dir", return_value=self.root)
        p.start()
        self.addCleanup(p.stop)

    def todo(self, folder, title, at, **extra) -> Path:
        f = self.root / folder / f"{title}.publish.todo"
        f.write_text(json.dumps({"video": f"X:/{title}.mp4", "only": extra.get("only"), "publish_at": at}), encoding="utf-8")
        return f

    def test_niveaux(self):
        s, r = REGISTRY["social_schedule"], REGISTRY["social_reschedule"]
        self.assertEqual((s.level, r.level, r.taint_blocked), (Level.N0, Level.N2, True))

    def test_liste(self):
        out = tools.social_schedule()["scheduled"]
        self.assertEqual([(r["title"], r["platform"]) for r in out], [("clip_a", "tiktok"), ("partie_b", "all")])

    def test_report_ne_change_que_publish_at(self):
        new = when(3, 19)
        out = tools.social_reschedule("clip_a", new)
        self.assertEqual(out["to"], new[:16])
        data = json.loads(self.a.read_text(encoding="utf-8"))
        self.assertEqual((data["publish_at"], data["video"], data["only"]), (new, "X:/clip_a.mp4", "tiktok"))
        self.assertEqual([f.name for f in self.a.parent.iterdir()], ["clip_a.publish.todo"])  # pas de .tmp

    def test_apercu_montre_ancienne_et_nouvelle_heure(self):
        new = when(3, 19)
        preview = REGISTRY["social_reschedule"].describe("clip_a", new)
        self.assertIn(when(1, 12)[:16], preview)
        self.assertIn(new[:16], preview)

    def test_dates_refusees_sans_rien_ecrire(self):
        before = self.a.read_text(encoding="utf-8")
        self.todo("Montage", "clip_c", when(2, 13))  # même dossier : créneau pris ; l'autre dossier a ses propres créneaux
        for bad in ("demain 18h", when(-1), when(40), "2026-10-09T18:00+02:00", "", when(2, 13)):  # passé, trop loin, fuseau, créneau pris
            with self.assertRaises(ValueError, msg=bad):
                tools.social_reschedule("clip_a", bad)
        self.assertEqual(self.a.read_text(encoding="utf-8"), before)

    def test_titre_inconnu_ou_ambigu(self):
        self.todo("Parties", "clip_a", when(5, 12))
        for title in ("inconnu", "clip_a", "../clip_a", ""):
            with self.assertRaises(ValueError, msg=title):
                tools.social_reschedule(title, when(3, 19))

    def test_fichier_illisible_ou_lien_ignores(self):
        (self.root / "Montage" / "casse.publish.todo").write_text("pas du json", encoding="utf-8")
        with self.assertRaises(ValueError):
            tools.social_reschedule("casse", when(3, 19))
        link = self.root / "Montage" / "lien.publish.todo"
        try:
            os.symlink(self.a, link)
        except OSError:
            self.skipTest("liens symboliques non disponibles")
        with self.assertRaises(ValueError):
            tools.social_reschedule("lien", when(3, 19))


    def test_delai_minimal_et_creneau_echu_ou_imminent(self):
        soon = (datetime.now() + timedelta(minutes=5)).isoformat()
        with self.assertRaises(ValueError):
            tools.social_reschedule("clip_a", soon)  # publication quasi immédiate
        late = self.todo("Montage", "clip_late", (datetime.now() + timedelta(minutes=1)).isoformat())
        before = late.read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            tools.social_reschedule("clip_late", when(3, 19))  # peut être en cours d'envoi par lol-clipper
        self.assertEqual(late.read_text(encoding="utf-8"), before)

    def test_video_deja_publiee_refusee(self):
        (self.root / "Montage" / "clip_a.tiktok.json").write_text("{}", encoding="utf-8")  # only=tiktok
        with self.assertRaises(ValueError):
            tools.social_reschedule("clip_a", when(3, 19))
        b = self.todo("Montage", "clip_b", when(2, 15))  # only=None : n'importe quelle plateforme déjà en ligne bloque
        (self.root / "Montage" / "clip_b.youtube.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            tools.social_reschedule("clip_b", when(3, 19))
        self.assertEqual(json.loads(b.read_text(encoding="utf-8"))["publish_at"], when(2, 15))

    def test_fichier_supprime_pendant_l_operation(self):
        real = social._read
        calls = []

        def vanishing(f):
            calls.append(f)
            if len(calls) > 1:  # relecture finale : lol-clipper vient de publier et de supprimer
                return None
            return real(f)
        with mock.patch.object(social, "_read", vanishing), self.assertRaises(ValueError):
            tools.social_reschedule("clip_a", when(3, 19))
        self.assertEqual([f.name for f in self.a.parent.iterdir()], ["clip_a.publish.todo"])  # rien recréé, pas de .tmp

    def test_titre_long_et_refus_a_la_voix(self):
        long_title = "t" * 79
        self.todo("Montage", long_title, when(4, 10))
        self.assertEqual(tools.social_schedule()["scheduled"][-1]["title"], long_title)  # désignable : 80 caractères rendus
        from jarvis.core import permissions
        from jarvis.core.audit import Audit
        before = self.a.read_text(encoding="utf-8")
        for source in ("voix", "voix/llm"):
            with self.assertRaises(permissions.Refused):
                permissions.execute("social_reschedule", {"title": "clip_a", "at": when(3, 19)}, source=source, audit=Audit(":memory:"),
                                    confirm=lambda t, a: False, strong_auth=lambda t, a: False)
        self.assertEqual(self.a.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
