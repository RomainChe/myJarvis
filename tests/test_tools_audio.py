import ctypes
import unittest
from unittest import mock

from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.pc import audio
from pcbase import PcBase


class VolumeTest(PcBase):
    def test_niveaux(self):
        for name in ("set_volume", "mute", "media_control"):
            self.assertEqual(REGISTRY[name].level, Level.N1)

    def test_set_volume_nominal(self):
        with mock.patch.object(audio, "_set_volume") as backend:
            self.assertEqual(self.run_tool("set_volume", {"level": 35}), {"volume": 35})
            self.run_tool("set_volume", {"level": 0})
            self.run_tool("set_volume", {"level": 100})
        self.assertEqual([c.args[0] for c in backend.call_args_list], [35, 0, 100])
        self.assertEqual(self.audit.last(1)[0][5], "auto")

    def test_set_volume_entree_invalide(self):
        with mock.patch.object(audio, "_set_volume") as backend:
            for bad in ({"level": 101}, {"level": -1}, {"level": "30"}, {"level": 30.5}, {"level": True}, {}):
                with self.assertRaises(ValueError, msg=bad):
                    self.run_tool("set_volume", bad)
        backend.assert_not_called()

    def test_set_volume_permission_refusee(self):
        self.assert_refused_if_level_raised("set_volume", {"level": 30})

    def test_mute_nominal(self):
        with mock.patch.object(audio, "_set_mute") as backend:
            self.assertEqual(self.run_tool("mute", {"muted": True}), {"muted": True})
            self.run_tool("mute", {"muted": False})
        self.assertEqual([c.args[0] for c in backend.call_args_list], [True, False])

    def test_mute_entree_invalide(self):
        with mock.patch.object(audio, "_set_mute") as backend:
            for bad in ({"muted": 1}, {"muted": "oui"}, {}):
                with self.assertRaises(ValueError, msg=bad):
                    self.run_tool("mute", bad)
        backend.assert_not_called()

    def test_mute_permission_refusee(self):
        self.assert_refused_if_level_raised("mute", {"muted": True})

    def test_media_nominal(self):
        with mock.patch.object(audio, "_press") as press:
            for action in audio.MEDIA_KEYS:
                self.assertEqual(self.run_tool("media_control", {"action": action}), {"action": action})
        self.assertEqual([c.args[0] for c in press.call_args_list], list(audio.MEDIA_KEYS.values()))

    def test_media_entree_invalide(self):
        with mock.patch.object(audio, "_press") as press:
            for bad in ({"action": "volume_up"}, {"action": ""}, {"action": 3}, {"action": "next", "x": 1}):
                with self.assertRaises(ValueError, msg=bad):
                    self.run_tool("media_control", bad)
        press.assert_not_called()

    def test_media_permission_refusee(self):
        self.assert_refused_if_level_raised("media_control", {"action": "next"})

    def test_peripherique_reel_relu_sans_changement(self):
        """Core Audio réel : on relit le volume puis on le remet à l'identique (aucun effet audible)."""
        try:
            with audio._endpoint() as endpoint:
                scalar = ctypes.c_float()
                audio._call(endpoint, 9, (ctypes.c_void_p, ctypes.addressof(scalar)))
        except OSError:
            self.skipTest("aucun périphérique audio")
        self.assertTrue(0.0 <= scalar.value <= 1.0)
        audio._set_volume(round(scalar.value * 100))


if __name__ == "__main__":
    unittest.main()
