from unittest import mock

from jarvis.core.permissions import Refused
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.pc import say as say_mod
from pcbase import PcBase


class SayTest(PcBase):
    def test_niveau(self):
        self.assertEqual(REGISTRY["say"].level, Level.N1)

    def test_nominal_lit_sans_bloquer(self):
        sp = mock.Mock(is_speaking=mock.Mock(return_value=False))
        with mock.patch.object(say_mod, "_get_speaker", return_value=sp):
            self.assertEqual(self.run_tool("say", {"text": "Rappel."}), {"say": "ok"})
        sp.say.assert_called_once_with("Rappel.", block=False)

    def test_deja_en_train_de_parler(self):
        sp = mock.Mock(is_speaking=mock.Mock(return_value=True))
        with mock.patch.object(say_mod, "_get_speaker", return_value=sp):
            self.assertEqual(self.run_tool("say", {"text": "Rappel."}), {"say": "occupé"})
        sp.say.assert_not_called()

    def test_entree_invalide(self):
        with mock.patch.object(say_mod, "_get_speaker") as get:
            for bad in ({"text": 5}, {}, {"text": "   "}, {"text": "x" * 1001}):
                with self.assertRaises(ValueError, msg=bad):
                    self.run_tool("say", bad)
        get.assert_not_called()

    def test_permission_refusee_si_niveau_releve(self):
        self.assert_refused_if_level_raised("say", {"text": "x"})
