"""L'agent PC attend l'adresse Tailscale au démarrage de Windows au lieu de s'arrêter à la première erreur."""
import unittest

from jarvis import agent


class BindServerTests(unittest.TestCase):
    def test_reessaie_jusqu_a_ce_que_l_adresse_existe(self):
        calls = []

        def make(addr, handler):
            calls.append(addr)
            if len(calls) < 3:
                raise OSError("adresse non attribuée")
            return "serveur"

        waits = []
        self.assertEqual(agent.bind_server("100.64.0.1", 8788, object, make=make, sleep=waits.append), "serveur")
        self.assertEqual(len(calls), 3)
        self.assertEqual(waits, [agent.BIND_RETRY_S] * 2)

    def test_abandonne_apres_le_delai(self):
        def make(addr, handler):
            raise OSError("adresse non attribuée")

        waits = []
        with self.assertRaises(OSError):
            agent.bind_server("100.64.0.1", 8788, object, make=make, sleep=waits.append)
        self.assertEqual(len(waits), agent.BIND_WAIT_S // agent.BIND_RETRY_S)


if __name__ == "__main__":
    unittest.main()
