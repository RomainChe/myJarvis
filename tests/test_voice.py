"""Phase 4, étape 1 : socle voix (texte reconnu injecté ; ni micro, ni STT, ni LLM réel, rien d'exécuté pour de vrai)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import voice as voice_mod
from jarvis.core.audit import Audit
from jarvis.core.chat import TEXT_MAX, Chat
from jarvis.core.permissions import Refused, execute
from jarvis.core.voice import Voice

SECRET = "motsecretvocal42"
UNROUTED = f"fais quelque chose d'inhabituel {SECRET}"  # ni phrase ni motif du routeur : part au LLM


class VoiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "audit.db")
        self.audit = Audit(self.path)
        self.chat = Chat(self.audit)
        self.voice = Voice(self.chat)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.audit.db.close)  # exécuté avant cleanup (ordre inverse)

    def rows(self):
        return self.audit.db.execute("SELECT source, tool, decision FROM audit").fetchall()

    def fake_ask(self, tool_name, args, answer="d'accord"):
        """Un LLM simulé qui demande l'outil `tool_name` ; sa réponse n'a aucun effet sur les messages de refus."""
        seen = []

        def ask(text, *, audit, confirm, strong_auth, source):
            seen.append(source)
            try:
                execute(tool_name, args, source=source, audit=audit, confirm=confirm, strong_auth=strong_auth)
            except Refused:
                pass
            return answer
        return mock.patch.object(voice_mod, "ask", ask), seen

    def test_n1_routeur_sans_llm_source_voix(self):
        with mock.patch.object(voice_mod, "execute", return_value={"tv": "on"}) as execute, \
                mock.patch.object(voice_mod, "ask") as ask:
            self.assertEqual(self.voice.handle("allume la télé"), "{'tv': 'on'}")
        ask.assert_not_called()
        self.assertEqual(execute.call_args.args[0], "tv_on")
        self.assertEqual(execute.call_args.kwargs["source"], "voix")
        self.assertIs(execute.call_args.kwargs["strong_auth"]("x", {}), False)

    def test_n0_via_llm_source_voix_llm(self):
        seen = []

        def ask(text, **kw):
            seen.append(kw["source"])
            return "Tout va bien."
        with mock.patch.object(voice_mod, "ask", ask):
            self.assertEqual(self.voice.handle(UNROUTED), "Tout va bien.")
        self.assertEqual(seen, ["voix/llm"])

    def test_texte_invalide_ou_trop_long(self):
        for bad in ("", "x" * (TEXT_MAX + 1), None, 12):
            with self.assertRaises(ValueError):
                self.voice.handle(bad)
        self.assertEqual(self.rows(), [])  # rien de journalisé, rien d'exécuté
        with mock.patch.object(voice_mod, "ask", return_value="ok"):
            self.assertEqual(self.voice.handle("x" * TEXT_MAX), "ok")  # la limite exacte passe

    def test_n2_refuse_rien_execute(self):
        patch, seen = self.fake_ask("power", {"action": "shutdown"})
        with patch, mock.patch("subprocess.run") as run:
            self.assertEqual(self.voice.handle("éteins le PC"), voice_mod.N2_MSG)
        run.assert_not_called()
        self.assertEqual(seen, ["voix/llm"])
        rows = self.rows()
        self.assertIn(("voix/llm", "power", "refusé"), rows)
        self.assertFalse([r for r in rows if r[0].startswith("pwa")])

    def test_n2_par_le_routeur_refuse(self):
        with mock.patch.object(self.chat.router, "route", return_value=("power", {"action": "shutdown"})), \
                mock.patch("subprocess.run") as run:
            self.assertEqual(self.voice.handle("n'importe quoi"), voice_mod.N2_MSG)
        run.assert_not_called()
        self.assertIn(("voix", "power", "refusé"), self.rows())

    def test_power_abaisse_en_n1_reste_refuse_a_la_voix(self):
        """Condition Sécurité : le son d'une TV ou d'un visiteur ne déclenche jamais un N2 du registre abaissé en N1."""
        from jarvis.core import levels
        levels.set_level("power", 1, strong_auth=True)
        with mock.patch.object(self.chat.router, "route", return_value=("power", {"action": "shutdown"})), \
                mock.patch("subprocess.run") as run:
            self.assertEqual(self.voice.handle("n'importe quoi"), voice_mod.N2_MSG)
        patch, _ = self.fake_ask("power", {"action": "shutdown"})
        with patch, mock.patch("subprocess.run") as run2:
            self.assertEqual(self.voice.handle("éteins le PC"), voice_mod.N2_MSG)
        run.assert_not_called()
        run2.assert_not_called()

    def test_n3_refuse_meme_si_le_llm_dit_oui(self):
        patch, _ = self.fake_ask("power", {"action": "shutdown"}, answer="C'est fait, oui !")
        with patch, mock.patch.object(voice_mod, "effective", return_value=3), \
                mock.patch("jarvis.core.permissions.effective", return_value=3), mock.patch("subprocess.run") as run:
            self.assertEqual(self.voice.handle("ouvre la serrure"), voice_mod.N3_MSG)
        run.assert_not_called()

    def test_n1_puis_n2_dans_le_meme_tour(self):
        """Décision Sécurité : les N0/N1 d'un tour restent exécutés, le N2 est refusé sans effet."""
        def ask(text, *, audit, confirm, strong_auth, source):
            execute("system_status", {}, source=source, audit=audit, confirm=confirm, strong_auth=strong_auth)
            for _ in range(3):  # retentatives du LLM : toutes refusées
                with self.assertRaises(Refused):
                    execute("power", {"action": "shutdown"}, source=source, audit=audit, confirm=confirm, strong_auth=strong_auth)
            return "C'est fait."
        with mock.patch.object(voice_mod, "ask", ask), mock.patch("subprocess.run") as run:
            self.assertEqual(self.voice.handle("coupe le son et éteins le PC"), voice_mod.N2_MSG)
        self.assertFalse([c for c in run.call_args_list if "shutdown" in str(c)])  # le N0 a tourné (nvidia-smi), pas le N2
        rows = self.rows()
        self.assertIn(("voix/llm", "system_status", "auto"), rows)
        self.assertEqual(sum(r == ("voix/llm", "power", "refusé") for r in rows), 3)
        self.assertFalse([r for r in rows if r[1] == "power" and r[2] != "refusé"])

    def test_valueerror_de_l_outil_message_fixe(self):
        with mock.patch.object(voice_mod, "ask", side_effect=ValueError(f"outil {SECRET} inconnu")):
            self.assertEqual(self.voice.handle(UNROUTED), "Demande invalide.")

    def test_audit_sans_le_texte(self):
        with mock.patch.object(voice_mod, "ask", return_value="ok"):
            self.voice.handle(UNROUTED)
        row = self.audit.db.execute("SELECT source, tool, args FROM audit").fetchone()
        self.assertEqual(row[:2], ("voix", "chat"))
        self.assertIn('"len"', row[2])
        self.assertIn('"sha256"', row[2])
        self.audit.db.commit()
        self.assertEqual(Path(self.path).read_bytes().count(SECRET.encode()), 0)

    def test_erreur_generique(self):
        with mock.patch.object(voice_mod, "ask", side_effect=RuntimeError(f"détail {SECRET}")):
            answer = self.voice.handle(UNROUTED)
        self.assertEqual(answer, "Erreur interne : RuntimeError")
        self.assertNotIn(SECRET, answer)

    def test_verrou_busy_partage_avec_le_chat(self):
        self.assertTrue(self.chat.busy.acquire(blocking=False))  # un tour de chat est en cours
        with mock.patch.object(voice_mod, "ask") as ask:
            self.assertEqual(self.voice.handle(UNROUTED), voice_mod.BUSY_MSG)
        ask.assert_not_called()
        self.chat.busy.release()
        with mock.patch.object(voice_mod, "ask", return_value="ok"):
            self.assertEqual(self.voice.handle(UNROUTED), "ok")
        self.assertTrue(self.chat.busy.acquire(blocking=False))  # le verrou a été rendu
        self.chat.busy.release()

    def test_verrou_rendu_apres_erreur(self):
        with mock.patch.object(voice_mod, "ask", side_effect=KeyError("x")):
            self.voice.handle(UNROUTED)
        self.assertTrue(self.chat.busy.acquire(blocking=False))
        self.chat.busy.release()


if __name__ == "__main__":
    unittest.main()
