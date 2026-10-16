"""Recette QA du 2026-10-13 : rappels, mémoire, Mic.run, hôtels, bon plan Japon. Les bugs connus sont des
`expectedFailure` (reproduction avant correction) : retirer le décorateur quand le code est corrigé."""
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

try:  # extra « voice » : absent du mini-PC, seuls les tests MicRun en dépendent
    import numpy as np
    from jarvis.core import mic as micmod
    from tests.test_mic import FakeSpeaker, FakeWake
except (ImportError, unittest.SkipTest):
    np = None

import jarvis.core.chat  # noqa: F401  (enregistre tous les outils)
import jarvis.tools.voyages  # noqa: F401
from jarvis.core import llm, memory, reminders, voyages
from jarvis.core.audit import Audit
from jarvis.core.permissions import Refused, execute
from jarvis.core.tools import REGISTRY, Level
from tests.test_voyages import HEAD, RESUME, hotel_project, project, row


class DbCase(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.audit = Audit(self.path)
        memory.load(self.audit)
        reminders.load(self.audit)
        self.addCleanup(os.unlink, self.path)
        self.addCleanup(self.audit.db.close)
        self.addCleanup(setattr, memory, "_audit", None)

    def run_tool(self, name, source="cli", **args):
        return execute(name, args, source=source, audit=self.audit, confirm=lambda t, a: False, strong_auth=lambda t, a: False)

    def journal(self):
        return str(self.audit.db.execute("SELECT * FROM audit").fetchall())


class Rappels(DbCase):
    def test_outils_journalises_sans_texte(self):
        for name, args in [("timer_set", {"duration": "5 minutes", "label": "TEXTE_SECRET"}), ("reminder_list", {}),
                           ("reminder_cancel", {"id": 0})]:
            self.run_tool(name, **args)
        j = self.journal()
        for name in ("timer_set", "reminder_list", "reminder_cancel"):
            self.assertIn(name, j)
        self.assertNotIn("TEXTE_SECRET", j)

    def test_entrees_invalides_journalisees(self):
        for name, args in [("timer_set", {"duration": "bientôt", "label": ""}), ("reminder_set", {"when": "à 25h", "label": ""}),
                           ("timer_set", {"duration": None, "label": ""}), ("reminder_cancel", {"id": -1}),
                           ("reminder_cancel", {"id": "abc"})]:
            with self.assertRaises(ValueError, msg=name):
                self.run_tool(name, **args)
        self.assertIn("invalide", self.journal())

    def test_briefing_non_annulable(self):
        reminders.arm_briefing((7, 30))
        with self.assertRaises(ValueError):
            self.run_tool("reminder_cancel", id=reminders.pending()[0][0])
        self.assertEqual(len(reminders.pending()), 1)

    def test_permission_refusee_niveau_releve(self):
        # le propriétaire relève timer_set à N2 : sans confirmation, refus journalisé et rien n'est créé
        with mock.patch("jarvis.core.permissions.effective", return_value=Level.N2):
            with self.assertRaises(Refused):
                self.run_tool("timer_set", duration="5 minutes", label="")
        self.assertEqual(reminders.pending(), [])
        self.assertIn("refusé", self.journal())

    def test_ecriture_refusee_apres_contenu_externe(self):
        calls = iter([{"message": {"tool_calls": [{"function": {"name": "briefing", "arguments": {}}}]}},
                      {"message": {"tool_calls": [{"function": {"name": "reminder_set",
                                                                "arguments": {"when": "dans 5 minutes", "label": "x"}}}]}},
                      {"message": {"tool_calls": [{"function": {"name": "timer_set",
                                                                "arguments": {"duration": "5 minutes", "label": "x"}}}]}},
                      {"message": {"content": "fini"}}])
        with mock.patch("jarvis.tools.assist.build_briefing", return_value="ok"):
            llm.ask("briefing puis rappel", audit=self.audit, confirm=lambda t, a: False, strong_auth=lambda t, a: False,
                    send=lambda path, body: next(calls), gaming=lambda: False)
        self.assertEqual(reminders.pending(), [])

    def test_base_non_chargee(self):
        reminders._audit = None
        self.addCleanup(setattr, reminders, "_audit", self.audit)
        with self.assertRaises(RuntimeError):
            reminders.pending()

    def test_boucle_survit_a_une_base_en_panne(self):
        stop, seen = threading.Event(), []
        real = reminders.tick

        def flaky(announce, at=None, now=None):
            seen.append(1)
            if len(seen) == 1:
                raise OSError("database is locked")
            stop.set()
            return real(announce, at, now)
        with mock.patch.object(reminders, "tick", flaky):
            reminders.run(lambda *a: None, None, stop, every=0)
        self.assertEqual(len(seen), 2)

    def test_annonce_une_seule_fois(self):
        now = 1_800_000_000.0
        reminders.add(now, "x", "reminder")
        got = []
        self.assertEqual(reminders.tick(lambda *a: got.append(a), now=now), 1)
        self.assertEqual(reminders.tick(lambda *a: got.append(a), now=now + 10), 0)
        self.assertEqual(len(got), 1)


class Memoire(DbCase):
    def test_BUG_01_oublier_par_numero_ne_supprime_que_ce_numero(self):
        # BUG-01 : memory.forget("#1") supprime aussi tout souvenir dont le texte contient « 1 »
        memory.add("premier")
        memory.add("code 1234")
        memory.add("rdv à 10h")
        self.assertEqual(memory.forget("#1"), 1)
        self.assertEqual([i for i, _ in memory.facts()], [2, 3])

    def test_oublier_vide_ou_inconnu_ne_supprime_rien(self):
        memory.add("café")
        with self.assertRaises(ValueError):
            self.run_tool("memory_forget", about="   ")
        self.assertEqual(memory.forget("zzz"), 0)
        self.assertEqual(len(memory.facts()), 1)

    def test_non_charge(self):
        memory._audit = None
        self.assertEqual(memory.prompt_block(), "")
        with self.assertRaises(RuntimeError):
            memory.facts()

    def test_texte_borne_et_une_ligne(self):
        memory.add("a\n\nb " + "x" * 500)
        ((_, text),) = memory.facts()
        self.assertEqual(len(text), memory.TEXT_MAX)
        self.assertNotIn("\n", text)

    def test_permission_refusee_niveau_releve(self):
        with mock.patch("jarvis.core.permissions.effective", return_value=Level.N2):
            with self.assertRaises(Refused):
                self.run_tool("memory_set", text="x")
        self.assertEqual(memory.facts(), [])

    def test_niveaux(self):
        self.assertEqual([REGISTRY[n].level for n in ("memory_set", "memory_list", "memory_forget")], [Level.N1, Level.N0, Level.N1])
        self.assertTrue(REGISTRY["memory_list"].private)


@unittest.skipIf(np is None, "numpy absent (extra voice)")
class MicRun(unittest.TestCase):
    def make(self, sd, speaker=None):
        tmp = Path(tempfile.mkdtemp())
        m = micmod.Mic(lambda a: None, speaker=speaker or FakeSpeaker(), flag=tmp / "off", sd=sd, wake_loader=lambda: FakeWake())
        m._load = lambda: setattr(m, "_wake", FakeWake())
        return m

    def test_modele_absent_arret_sans_boucle(self):
        m = self.make(sd=object())
        m._load = mock.Mock(side_effect=micmod.MicError("modèle de réveil non vérifié"))
        m.run()
        self.assertEqual(m.error, micmod.ERR_MSG)

    def test_ouverture_echoue_puis_reussit(self):
        calls = []

        class Stream:
            def start(self): pass
            def close(self): pass
            def read(self, n):
                m.stop()
                return np.zeros((n, 1), np.int16), False

        class SD:
            def InputStream(self, **kw):
                calls.append(1)
                if len(calls) < 3:
                    raise OSError("occupé")
                return Stream()
        m = self.make(SD())
        with mock.patch.object(micmod, "RETRY_S", 0):
            m.run()
        self.assertEqual((len(calls), m.error), (3, None))

    def test_close_qui_leve_ne_tue_pas_la_boucle(self):
        opened = []

        class Stream:
            def start(self): pass
            def close(self):
                if len(opened) == 1:
                    raise OSError("déjà fermé")

            def read(self, n):
                if len(opened) == 1:
                    raise OSError("perdu")
                m.stop()
                return np.zeros((n, 1), np.int16), False

        class SD:
            def InputStream(self, **kw):
                opened.append(1)
                return Stream()
        m = self.make(SD())
        with mock.patch.object(micmod, "RETRY_S", 0):
            m.run()
        self.assertEqual(len(opened), 2)

    def test_portaudio_non_relance_pendant_une_lecture(self):
        terminated = []

        class Stream:
            def start(self): pass
            def close(self): pass
            def read(self, n):
                m.stop()
                raise OSError("perdu")

        class SD:
            def InputStream(self, **kw): return Stream()
            def _terminate(self): terminated.append(1)
            def _initialize(self): pass
        sp = FakeSpeaker()
        sp.until = float("inf")
        m = self.make(SD(), sp)
        with mock.patch.object(micmod, "RETRY_S", 0):
            m.run()
        self.assertEqual(terminated, [])

    def test_kill_switch_ferme_le_flux(self):
        closed = []

        class Stream:
            def start(self): pass
            def close(self): closed.append(1)
            def read(self, n):
                m.disable()
                return np.zeros((n, 1), np.int16), False

        class SD:
            def InputStream(self, **kw): return Stream()
        m = self.make(SD())
        real_wait = m._stop.wait
        m._stop.wait = lambda t=None: (m._stop.set(), True)[1]
        self.addCleanup(setattr, m._stop, "wait", real_wait)
        m.run()
        self.assertTrue(closed)
        self.assertEqual(m.state, "coupé")

    def test_BUG_06_close_final_qui_leve_ne_tue_pas_run(self):
        # BUG-06 : stop() puis stream.close() qui lève (périphérique disparu) : l'exception sort de run() et tue le thread
        class Stream:
            def start(self): pass
            def close(self): raise OSError("disparu")

            def read(self, n):
                m.stop()
                return np.zeros((n, 1), np.int16), False

        class SD:
            def InputStream(self, **kw): return Stream()
        m = self.make(SD())
        m.run()

    def test_BUG_03_voyant_ecoute_retombe_quand_le_flux_est_perdu(self):
        # BUG-03 : flux perdu en pleine phrase -> run() remet _buf à None mais pas l'état : l'indicateur reste « écoute »
        class Stream:
            def start(self): pass
            def close(self): pass
            def read(self, n):
                m.stop()
                raise OSError("perdu")

        class SD:
            def InputStream(self, **kw): return Stream()
        m = self.make(SD())
        m._buf, m.state = [], "écoute"
        with mock.patch.object(micmod, "RETRY_S", 0):
            m.run()
        self.assertNotEqual(m.state, "écoute")


class Hotels(unittest.TestCase):
    def setUp(self):
        voyages._hotel_sync.update(at=0.0, ok=None, error=None)

    def test_git_indisponible_garde_la_copie_locale(self):
        root = hotel_project(RESUME)
        (root / ".git").mkdir()
        with mock.patch.object(voyages.subprocess, "run", side_effect=FileNotFoundError("git")):
            s = voyages.hotel_snapshot(root)
        self.assertTrue(s["configured"])
        self.assertEqual(s["total_recommande"], 2345.0)
        self.assertIn("synchronisation", s["sync_error"])

    def test_git_expire(self):
        root = hotel_project(RESUME)
        (root / ".git").mkdir()
        with mock.patch.object(voyages.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 1)):
            self.assertTrue(voyages.hotel_snapshot(root)["configured"])

    def test_schemas_inattendus_sans_exception(self):
        bad = ('{"etapes": 5}', '{"etapes": [1]}', "null", "",
               '{"date":"2026-10-13","total_recommande":NaN,"total_moins_cher":1,"etapes":[]}',
               json.dumps({**RESUME, "etapes": "x"}))
        for data in bad:
            self.assertFalse(voyages.hotel_snapshot(hotel_project(data))["configured"], data)

    def test_fichier_trop_gros_ignore(self):
        big = json.dumps({**RESUME, "pad": "x" * (voyages.MAX_RESUME_BYTES + 1)})
        self.assertFalse(voyages.hotel_snapshot(hotel_project(big))["configured"])

    def test_plafond_d_etapes(self):
        data = {**RESUME, "etapes": RESUME["etapes"] * 40}
        self.assertLessEqual(len(voyages.hotel_snapshot(hotel_project(data))["etapes"]), voyages.MAX_STAGES)

    def test_outils_n0_external(self):
        for name in ("hotel_itineraire", "voyage_prix"):
            self.assertEqual((REGISTRY[name].level, REGISTRY[name].external), (Level.N0, True))

    def test_hotel_itineraire_journalise(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        audit = Audit(path)
        self.addCleanup(os.unlink, path)
        self.addCleanup(audit.db.close)
        with mock.patch.object(voyages, "hotel_dir", return_value=hotel_project(RESUME)):
            out = execute("hotel_itineraire", {}, source="cli", audit=audit, confirm=lambda t, a: False, strong_auth=lambda t, a: False)
        self.assertIn("recommandé", out)
        self.assertIn("hotel_itineraire", str(audit.db.execute("SELECT * FROM audit").fetchall()))

    def test_BUG_04_devise_absente_meme_symbole_partout(self):
        # BUG-04 : sans « devise », la phrase parlée dit « € » mais renderHotels et le carré dashboard (app.js) affichent
        # « 2345 » sans symbole : le Core devrait normaliser une fois pour les deux consommateurs.
        s = voyages.hotel_snapshot(hotel_project({k: v for k, v in RESUME.items() if k != "devise"}))
        self.assertEqual(s["devise"], "EUR")


class BonPlan(unittest.TestCase):
    def deal(self, state, price, search="Japon", origin="BCN"):
        calls = []
        out = voyages.check_deal(lambda: calls.append(price), state, project(HEAD + row("2026-10-13", search, origin, price)))
        return out, calls

    def test_notify_qui_echoue_ne_marque_pas_comme_vu(self):
        state = Path(tempfile.mkdtemp()) / "a.json"

        def boom():
            raise OSError("réseau")
        with self.assertRaises(OSError):
            voyages.check_deal(boom, state, project(HEAD + row("2026-10-13", "Japon", "BCN", 600)))
        self.assertFalse(state.exists())
        self.assertIsNotNone(self.deal(state, 600)[0])

    def test_etat_absent_ou_corrompu(self):
        for text in ("", "pas du json", "{"):
            state = Path(tempfile.mkdtemp()) / "a.json"
            state.write_text(text, encoding="utf-8")
            self.assertIsNotNone(self.deal(state, 600)[0], text)

    def test_BUG_02_etat_json_non_objet_ne_bloque_pas_les_alertes(self):
        # BUG-02 : alert.json = « [] » ou « null » -> AttributeError à chaque heure (avalée par _voyages_watch) : plus
        # aucune alerte jusqu'à suppression manuelle du fichier.
        for text in ("[]", "null", '"x"'):
            state = Path(tempfile.mkdtemp()) / "a.json"
            state.write_text(text, encoding="utf-8")
            self.assertIsNotNone(self.deal(state, 600)[0], text)

    def test_meme_prix_puis_hausse_sans_nouvelle_alerte(self):
        state = Path(tempfile.mkdtemp()) / "a.json"
        self.assertEqual(self.deal(state, 600)[1], [600])
        for p in (600, 610, 640):
            self.assertEqual(self.deal(state, p)[1], [])

    def test_BUG_05_un_itineraire_alerte_une_seule_fois_meme_apres_un_autre(self):
        # BUG-05 : A (640) alerte, B (630, moins cher) alerte, puis B remonte et A redevient le meilleur à 640 :
        # le fichier d'état ne retient que le dernier itinéraire, A alerte une seconde fois à prix identique.
        state = Path(tempfile.mkdtemp()) / "a.json"
        a, b = row("2026-10-13", "Japon", "BCN", 640), row("2026-10-13", "Japon", "PAR", 630)
        calls = []
        for csv in (a, b + a, a):
            voyages.check_deal(lambda: calls.append(1), state, project(HEAD + csv))
        self.assertEqual(len(calls), 2)

    def test_watch_journalise_une_fois_et_survit_aux_pannes(self):
        import jarvis.__main__ as main
        audit = mock.Mock()
        seq = iter([None, {"price": 600}, OSError("git")])

        def check(notify):
            v = next(seq)
            if isinstance(v, BaseException):
                raise v
            return v
        slept = []

        def sleep(s):
            slept.append(s)
            if len(slept) > 8:
                raise KeyboardInterrupt
        with mock.patch.object(voyages, "check_deal", check), mock.patch("time.sleep", sleep):
            with self.assertRaises((KeyboardInterrupt, RuntimeError)):
                main._voyages_watch(audit)
        audit.log.assert_called_once()
        self.assertEqual(audit.log.call_args[0][1], "voyages_deal")
        self.assertNotIn("600", str(audit.log.call_args))


if __name__ == "__main__":
    unittest.main()
