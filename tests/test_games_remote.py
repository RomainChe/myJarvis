import unittest
from unittest import mock

from jarvis.core import agentlink, games


class RemoteDetectTest(unittest.TestCase):
    def setUp(self):
        games._remote = (0.0, False)
        self.t = 100.0

    def detect(self):
        return games.detect_remote(now=lambda: self.t)

    def test_agent_says_gaming(self):
        with mock.patch.object(agentlink, "call", return_value=True) as c:
            self.assertTrue(self.detect())
            self.assertTrue(self.detect())  # cache de 5 s
            self.assertEqual(c.call_count, 1)
            self.t += 6
            self.detect()
            self.assertEqual(c.call_count, 2)

    def test_pc_off_means_no_game_and_is_not_retried_for_30s(self):
        with mock.patch.object(agentlink, "call", side_effect=agentlink.AgentError("PC injoignable")) as c:
            self.assertFalse(self.detect())
            self.t += 20
            self.assertFalse(self.detect())
            self.assertEqual(c.call_count, 1)
            self.t += 11
            self.detect()
            self.assertEqual(c.call_count, 2)

    def test_non_boolean_answer_is_not_a_game(self):
        with mock.patch.object(agentlink, "call", return_value="oui"):
            self.assertFalse(self.detect())

    def test_core_without_pc_tools_asks_the_agent(self):
        with mock.patch("jarvis.core.host.HAS_PC_TOOLS", False), \
             mock.patch.object(games, "detect_remote", return_value=True):
            self.assertTrue(games.detect())


if __name__ == "__main__":
    unittest.main()
