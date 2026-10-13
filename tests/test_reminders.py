"""Minuteurs, rappels et briefing : analyse des durées et heures, échéances, journal sans texte, routeur, niveaux."""
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import jarvis.core.chat  # noqa: F401  (enregistre tous les outils : le catalogue du routeur les vise)
from jarvis.core import reminders as r
from jarvis.core import social, veille
from jarvis.core.audit import Audit
from jarvis.core.permissions import execute
from jarvis.core.router import Router
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools import assist
from jarvis.tools.home import weather

NOW = datetime(2026, 10, 13, 9, 0, 0)


def run(name, **args):
    """Chemin réel : garde de permissions, journal, niveau effectif."""
    return execute(name, args, source="cli", audit=run.audit, confirm=lambda t, a: False, strong_auth=lambda t, a: False)


class Base(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.audit = run.audit = Audit(self.path)
        r.load(self.audit)
        self.clock = [NOW.timestamp()]
        p = mock.patch.object(r, "_wall", lambda: self.clock[0])
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.audit.db.close()
        os.unlink(self.path)


class Parsing(unittest.TestCase):
    def test_durees(self):
        for text, minutes in [("20 minutes", 20), ("1h30", 90), ("2 heures", 120), ("une demi-heure", 30), ("d'une heure", 60),
                              ("un quart d'heure", 15), ("de 10 min", 10), ("90", 90), ("1 heure 15", 75)]:
            self.assertEqual(r.parse_duration(text), minutes, text)

    def test_durees_invalides(self):
        for text in ("", "bientôt", "0 minutes", "25 heures", "20 jours", "h"):
            with self.assertRaises(ValueError, msg=text):
                r.parse_duration(text)

    def test_heures(self):
        d = lambda text: r.parse_when(text, NOW)  # noqa: E731
        self.assertEqual(d("à 18h30"), datetime(2026, 10, 13, 18, 30))
        self.assertEqual(d("à 7h"), datetime(2026, 10, 14, 7, 0))  # 7 h est passé : demain
        self.assertEqual(d("demain à 8h"), datetime(2026, 10, 14, 8, 0))
        self.assertEqual(d("demain à 10h"), datetime(2026, 10, 14, 10, 0))  # « demain » prime même si 10 h n'est pas passé
        self.assertEqual(d("dans 20 minutes"), datetime(2026, 10, 13, 9, 20))
        self.assertEqual(d("21:05"), datetime(2026, 10, 13, 21, 5))

    def test_heures_invalides(self):
        for text in ("à 25h", "à 7h75", "plus tard", ""):
            with self.assertRaises(ValueError, msg=text):
                r.parse_when(text, NOW)


class Tools(Base):
    def test_niveaux(self):
        self.assertEqual([REGISTRY[n].level for n in ("timer_set", "reminder_set", "reminder_cancel", "reminder_list", "briefing")],
                         [Level.N1, Level.N1, Level.N1, Level.N0, Level.N0])
        self.assertTrue(all(REGISTRY[n].taint_blocked for n in ("timer_set", "reminder_set", "reminder_cancel")))

    def test_minuteur_puis_annonce(self):
        self.assertIn("09:20", run("timer_set", duration="20 minutes", label="les pâtes"))
        seen = []
        self.clock[0] += 19 * 60
        self.assertEqual(r.tick(lambda *a: seen.append(a)), 0)
        self.clock[0] += 61
        self.assertEqual(r.tick(lambda *a: seen.append(a)), 1)
        self.assertEqual(seen, [("timer", "les pâtes", 1.0)])
        self.assertEqual(r.tick(lambda *a: seen.append(a)), 0)  # une seule annonce
        self.assertEqual(r.pending(), [])

    def test_journal_sans_le_texte(self):
        run("timer_set", duration="1 minute", label="secret médical")
        run("reminder_set", when="à 18h", label="appeler la banque")
        self.clock[0] += 24 * 3600
        r.tick(lambda *a: None)
        dump = repr(self.audit.last(50))
        self.assertNotIn("secret", dump)
        self.assertNotIn("banque", dump)
        self.assertIn("timer_fire", dump)

    def test_liste_et_annulation(self):
        run("timer_set", duration="30 minutes", label="B")
        run("reminder_set", when="à 8h", label="A")
        text = run("reminder_list")
        self.assertIn("minuteur", text)
        self.assertIn("rappel", text)
        self.assertNotIn("A", text.replace("rappel", "").replace("à", ""))  # jamais le texte
        first = r.pending()[0][0]
        self.assertIn(str(first), run("reminder_cancel", id=0))  # le plus proche
        self.assertEqual(len(r.pending()), 1)
        with self.assertRaises(ValueError):
            run("reminder_cancel", id=999)

    def test_liste_vide(self):
        self.assertIn("Aucun", run("reminder_list"))

    def test_plafond(self):
        for _ in range(r.MAX_PENDING):
            r.add(NOW.timestamp() + 60, "x", "timer")
        with self.assertRaisesRegex(ValueError, "au plus"):
            run("timer_set", duration="5 minutes", label="")

    def test_texte_long_borne(self):
        r.add(NOW.timestamp() + 60, "x" * 5000, "timer")
        self.assertEqual(len(r.pending()[0][2]), r.LABEL_MAX)

    def test_resultat_de_l_annonce_journalise(self):
        run("timer_set", duration="1 minute", label="")
        self.clock[0] += 120
        r.tick(lambda *a: "push seul")
        self.assertIn("push seul", repr(self.audit.last(3)))

    def test_annonce_qui_echoue_est_journalisee_et_retiree(self):
        run("timer_set", duration="1 minute", label="")
        self.clock[0] += 120

        def boom(*a):
            raise OSError("pas de carte son")
        self.assertEqual(r.tick(boom), 1)
        self.assertIn("annonce échouée : OSError", repr(self.audit.last(5)))
        self.assertEqual(r.pending(), [])


class Briefing(Base):
    def test_rearmement_quotidien(self):
        r.arm_briefing((7, 30), NOW)  # 9 h > 7 h 30 : demain
        r.arm_briefing((7, 30), NOW)  # déjà armé : rien de plus
        (row,) = r.pending()
        self.assertEqual(datetime.fromtimestamp(row[1]), datetime(2026, 10, 14, 7, 30))
        seen = []
        self.clock[0] = datetime(2026, 10, 14, 7, 30, 5).timestamp()
        r.tick(lambda *a: seen.append(a[0]), (7, 30))
        self.assertEqual(seen, ["briefing"])
        (row,) = r.pending()
        self.assertEqual(datetime.fromtimestamp(row[1]), datetime(2026, 10, 15, 7, 30))

    def test_briefing_manque_non_lu(self):
        r.arm_briefing((7, 30), NOW)
        self.clock[0] = datetime(2026, 10, 14, 11, 0).timestamp()  # PC allumé 3 h 30 après
        seen = []
        r.tick(lambda *a: seen.append(a), (7, 30))
        self.assertEqual(seen, [])
        self.assertEqual(len(r.pending()), 1)  # réarmé pour le lendemain

    def test_heure_invalide(self):
        for raw in ("7h30", "25:00", "07:61"):
            with self.assertRaises(ValueError):
                r.briefing_time(raw)
        self.assertEqual(r.briefing_time("07:30"), (7, 30))
        self.assertIsNone(r.briefing_time(""))

    def test_briefing_complet_et_source_en_panne(self):
        w = {"temp_c": 14.2, "sky": "Pluie", "min_c": 9.0, "max_c": 15.0, "rain_chance": 60.0, "alerts": ["vent fort"]}
        snap = {"published": [{"title": "Best-of", "at": "2026-10-13T08:00"}], "scheduled": [{"at": "2026-10-13T19:00", "title": "x", "platform": "all"}]}
        issues = {"issues": [{"items": [{"lines": ["GPT nouveau"]}, {"lines": ["Autre titre"]}, {"lines": ["Trop"]}]}]}
        run("reminder_set", when="à 18h", label="privé")
        with mock.patch.object(weather, "_weather", return_value=w), mock.patch.object(social, "snapshot", return_value=snap), \
                mock.patch.object(veille, "snapshot", return_value=issues):
            text = assist.build_briefing(NOW)
        for part in ("mardi 13 octobre", "14 °C, pluie", "9 à 15", "60 % de risque", "vent fort", "1 rappel(s)", "Best-of",
                     "19:00", "GPT nouveau ; Autre titre"):
            self.assertIn(part, text)
        self.assertNotIn("Trop", text)
        self.assertNotIn("privé", text)  # le texte des rappels n'est jamais lu dans le briefing
        with mock.patch.object(weather, "_weather", side_effect=ValueError("lieu non configuré")), \
                mock.patch.object(social, "snapshot", side_effect=OSError), mock.patch.object(veille, "snapshot", return_value={"issues": []}):
            self.assertEqual(assist.build_briefing(NOW), "Bonjour. Nous sommes mardi 13 octobre. 1 rappel(s) aujourd'hui, le prochain à 18:00.")


class Routage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = Router()

    def test_phrases(self):
        cases = {
            "mets un minuteur de 20 minutes": ("timer_set", {"duration": "20 minutes", "label": ""}),
            "Jarvis, minuteur 1h30": ("timer_set", {"duration": "1h30", "label": ""}),
            "lance un minuteur de 10 minutes pour les pâtes": ("timer_set", {"duration": "10 minutes", "label": "les pâtes"}),
            "rappelle-moi de sortir le linge dans 20 minutes": ("timer_set", {"duration": "20 minutes", "label": "sortir le linge"}),
            "réveille-moi à 7h": ("reminder_set", {"when": "à 7h", "label": "Réveil"}),
            "réveille-moi demain à 6h30": ("reminder_set", {"when": "demain à 6h30", "label": "Réveil"}),
            "rappelle-moi à 18h30 d'appeler Paul": ("reminder_set", {"when": "à 18h30", "label": "appeler Paul"}),
            "rappelle-moi dans 2 heures de prendre le médicament": ("reminder_set", {"when": "dans 2 heures", "label": "prendre le médicament"}),
            "rappelle-moi d'appeler Paul à 18h": ("reminder_set", {"when": "18h", "label": "appeler Paul"}),
            "annule le minuteur": ("reminder_cancel", {"id": 0}),
            "annule le rappel 3": ("reminder_cancel", {"id": 3}),
            "mes rappels": ("reminder_list", {}),
            "briefing du matin": ("briefing", {}),
        }
        for text, expected in cases.items():
            self.assertEqual(self.router.route(text), expected, text)

    def test_les_catalogues_restent_valides(self):
        for text in ("quel temps fait-il", "éteins la télé", "mets le volume à 30"):
            self.assertIsNotNone(self.router.route(text), text)


if __name__ == "__main__":
    unittest.main()
