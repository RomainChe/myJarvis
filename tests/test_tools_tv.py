import unittest
from unittest import mock

from jarvis.core import ha
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.home import tv
from pcbase import PcBase


class TvTest(PcBase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(ha, "call_service")
        self.call = p.start()
        self.addCleanup(p.stop)

    def test_niveaux(self):
        self.assertEqual(REGISTRY["tv_status"].level, Level.N0)
        self.assertTrue(REGISTRY["tv_status"].external)  # le nom de l'appli vient d'un tiers
        for name in ("tv_on", "tv_off", "tv_volume", "tv_mute", "tv_key", "tv_open_app"):
            self.assertEqual(REGISTRY[name].level, Level.N1)

    def test_status(self):
        state = {"state": "on", "attributes": {"app_name": "YouTube", "volume_level": 0.256, "is_volume_muted": False}}
        with mock.patch.object(ha, "state", return_value=state) as st:
            self.assertEqual(self.run_tool("tv_status"),
                             {"state": "on", "app": "YouTube", "muted": False, "volume_percent": 26})
        st.assert_called_once_with("media_player.salon_tv")

    def test_status_sans_volume(self):
        with mock.patch.object(ha, "state", return_value={"state": "off", "attributes": {}}):
            self.assertIsNone(self.run_tool("tv_status")["volume_percent"])

    def test_on_off_mute_key_app(self):
        self.run_tool("tv_on")
        self.call.assert_called_with("media_player", "turn_on", "media_player.salon_tv")
        self.run_tool("tv_off")
        self.call.assert_called_with("media_player", "turn_off", "media_player.salon_tv")
        self.run_tool("tv_mute", {"muted": True})
        self.call.assert_called_with("media_player", "volume_mute", "media_player.salon_tv", is_volume_muted=True)
        self.run_tool("tv_key", {"button": "back"})
        self.call.assert_called_with("remote", "send_command", "remote.salon_tv", command="BACK")
        self.run_tool("tv_open_app", {"app": " YouTube "})
        self.call.assert_called_with("media_player", "play_media", "media_player.salon_tv",
                                     media_type="app", media_id="com.google.android.youtube.tv")

    def test_volume_par_pas(self):
        self.run_tool("tv_volume", {"direction": "down", "steps": 3})
        self.assertEqual(self.call.call_count, 3)
        self.call.assert_called_with("media_player", "volume_down", "media_player.salon_tv")

    def test_entrees_invalides_sans_appel_ha(self):
        bad = [("tv_volume", {"direction": "sideways", "steps": 1}), ("tv_volume", {"direction": "up", "steps": 0}),
               ("tv_volume", {"direction": "up", "steps": 11}), ("tv_key", {"button": "POWER"}),
               ("tv_open_app", {"app": "com.evil.app"}), ("tv_mute", {"muted": "oui"})]
        for name, args in bad:
            with self.assertRaises(ValueError):
                self.run_tool(name, args)
        self.call.assert_not_called()

    def test_ha_injoignable_est_journalise(self):
        self.call.side_effect = ha.HAError("Home Assistant injoignable")
        with self.assertRaises(ha.HAError):
            self.run_tool("tv_on")
        self.assertIn("erreur", self.audit.last(1)[0][6])

    def test_niveau_releve_bloque(self):
        self.assert_refused_if_level_raised("tv_off", {})
        self.call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
