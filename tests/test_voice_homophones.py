"""Lot 4c : le routeur comprend les homophones mesurés de Vosk, sans déclencher d'action sur une phrase ordinaire."""
import unittest
from unittest import mock

from jarvis.core import voice as voice_mod
from jarvis.core.router import Router, voice_fix
from jarvis.core.audit import Audit
from jarvis.core.chat import Chat


class VoiceFixTest(unittest.TestCase):
    def setUp(self):
        self.router = Router()

    def routed(self, heard):
        return self.router.route(voice_fix(heard))

    def test_homophones_mesures_donnent_la_bonne_intention(self):
        self.assertEqual(self.routed("a vu le pc"), ("pc_plug_on", {}))
        self.assertEqual(self.routed("Allure le PC"), ("pc_plug_on", {}))
        self.assertEqual(self.routed("éteint la télé")[0], "tv_off")
        self.assertEqual(self.routed("mais le volume à 30"), self.router.route("mets le volume à 30"))
        self.assertEqual(voice_fix("mais la TV sur très fin"), "mets la TV sur TF1")
        self.assertEqual(voice_fix("mets la télé sur tf un"), "mets la télé sur TF1")
        self.assertEqual(voice_fix("éteint le salon"), "éteins le salon")

    def test_texte_ordinaire_inchange(self):
        for text in ("tu as vu le pc", "mais je veux le pc", "la lumière éteint le salon", "un tissu très fin", "mets la télé sur TF1",
                     "allure lampe", "mais la maison est belle", "éteint", "a vu", "il a vu la télé", "éteins la télé",
                     "ça a vu le pc"):
            self.assertEqual(voice_fix(text), text, text)

    def test_correction_sans_effet_sur_une_phrase_hors_catalogue(self):
        self.assertIsNone(self.routed("éteint le salon"))  # pas d'intention locale : au LLM, qui voit « éteins le salon »

    def test_voice_handle_route_le_texte_corrige_et_journalise_l_original(self):
        chat = Chat(Audit(":memory:"))
        voice = voice_mod.Voice(chat)
        with mock.patch.object(voice_mod, "execute", return_value="ok") as ex:
            self.assertEqual(voice.handle("a vu le pc"), "ok")
        self.assertEqual(ex.call_args.args[0], "pc_plug_on")
        self.assertEqual(ex.call_args.kwargs["source"], "voix")


if __name__ == "__main__":
    unittest.main()
