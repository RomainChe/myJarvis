"""Socle commun des tests d'outils PC (non découvert : le nom ne commence pas par « test »)."""
import dataclasses
import unittest
from unittest import mock

from jarvis.core.audit import Audit
from jarvis.core.permissions import Refused, execute
from jarvis.core.tools import REGISTRY, Level, _registry


def no(*_):
    return False


def yes(*_):
    return True


class PcBase(unittest.TestCase):
    def setUp(self):
        self.audit = Audit(":memory:")

    def run_tool(self, name, args=None, confirm=no):
        return execute(name, args or {}, source="test", audit=self.audit, confirm=confirm, strong_auth=no)

    def assert_refused_if_level_raised(self, name, args):
        """Le propriétaire peut monter le niveau d'un outil : la garde doit alors bloquer."""
        run = mock.Mock()
        raised = dataclasses.replace(REGISTRY[name], level=Level.N2, run=run)
        with mock.patch.dict(_registry, {name: raised}):  # REGISTRY est en lecture seule
            with self.assertRaises(Refused):
                self.run_tool(name, args, confirm=no)
        run.assert_not_called()
        self.assertEqual(self.audit.last(1)[0][5], "refusé")

    def assert_refused_without_confirmation(self, name, args):
        """Outil N2 : sans confirmation, rien ne s'exécute."""
        run = mock.Mock()
        patched = dataclasses.replace(REGISTRY[name], run=run)
        with mock.patch.dict(_registry, {name: patched}):
            with self.assertRaises(Refused):
                self.run_tool(name, args, confirm=no)
        run.assert_not_called()
