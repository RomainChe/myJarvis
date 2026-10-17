"""D2 : les N2 « forts » exigent la clé d'accès depuis la PWA, pas depuis le terminal."""
import dataclasses
import unittest
from unittest import mock

import jarvis.__main__  # noqa: F401  (enregistre tous les outils)
from jarvis.core.audit import Audit
from jarvis.core.permissions import STRONG_N2, Refused, execute
from jarvis.core.tools import REGISTRY, Level, _registry

ARGS = {"pid": 4242, "name": "notepad.exe"}


class StrongN2(unittest.TestCase):
    def setUp(self):
        self.audit = Audit(":memory:")
        self.run = mock.Mock(return_value={"killed": 4242})
        p = mock.patch.dict(_registry, {"kill_process": dataclasses.replace(REGISTRY["kill_process"], run=self.run)})
        p.start()
        self.addCleanup(p.stop)

    def call(self, source, strong):
        return execute("kill_process", dict(ARGS), source=source, audit=self.audit,
                       confirm=lambda *_: True, strong_auth=strong)

    def test_pwa_sans_cle_refusee(self):
        with self.assertRaises(Refused):
            self.call("pwa:1", lambda *_: False)
        self.run.assert_not_called()

    def test_pwa_avec_cle_acceptee(self):
        self.assertEqual(self.call("pwa:1", lambda *_: True), {"killed": 4242})

    def test_terminal_sans_cle_accepte(self):
        self.call("cli", lambda *_: self.fail("le terminal n'a pas de clé d'accès"))
        self.run.assert_called_once()

    def test_la_liste_ne_contient_que_des_outils_existants_n2_ou_plus(self):
        for name in STRONG_N2:
            self.assertGreaterEqual(REGISTRY[name].level, Level.N1, name)


if __name__ == "__main__":
    unittest.main()
