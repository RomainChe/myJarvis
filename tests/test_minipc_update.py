"""Bouton « Mettre à jour et redémarrer » de la tuile Mini-PC : N2 confirmé, unité systemd fixe, échecs sans détail."""
import dataclasses
import subprocess
import unittest
from unittest import mock

from jarvis.core import levels, minipc
from jarvis.core.tools import REGISTRY, Level, _registry
from test_chat import ChatBase


class StartUpdate(unittest.TestCase):
    def test_lance_l_unite_fixe_sans_attendre(self):
        minipc._cache["apt"] = (0, {"count": 8})
        with mock.patch.object(minipc.sys, "platform", "linux"), mock.patch.object(minipc.os.path, "exists", return_value=True), \
                mock.patch.object(minipc.subprocess, "run") as run:
            minipc.start_update()
        self.assertEqual(run.call_args.args[0], [minipc.SYSTEMCTL, "start", "--no-block", "jarvis-maintenance.service"])
        self.assertNotIn("apt", minipc._cache)

    def test_refus_polkit_message_fixe(self):
        err = subprocess.CalledProcessError(1, "systemctl", stderr=b"secret")
        with mock.patch.object(minipc.sys, "platform", "linux"), mock.patch.object(minipc.os.path, "exists", return_value=True), \
                mock.patch.object(minipc.subprocess, "run", side_effect=err):
            with self.assertRaises(RuntimeError) as cm:
                minipc.start_update()
        self.assertNotIn("secret", str(cm.exception))

    def test_hors_mini_pc(self):
        with mock.patch.object(minipc.sys, "platform", "win32"), mock.patch.object(minipc.subprocess, "run") as run:
            with self.assertRaises(RuntimeError):
                minipc.start_update()
        run.assert_not_called()


class Bouton(ChatBase):
    def test_niveau_et_plancher(self):
        self.assertEqual(REGISTRY["minipc_update"].level, Level.N2)
        self.assertTrue(REGISTRY["minipc_update"].taint_blocked)
        self.assertEqual(levels.FLOORS["minipc_update"], Level.N2)
        self.assertIn("minipc_update", levels.LABELS)

    def test_authentification_obligatoire(self):
        self.assertEqual(self.call("POST", "/api/minipc/update", {})[0], 401)

    def test_confirmation_puis_lancement(self):
        for approve in (False, True):
            run = mock.Mock(return_value={"minipc": "mise à jour lancée"})
            with mock.patch.dict(_registry, {"minipc_update": dataclasses.replace(REGISTRY["minipc_update"], run=run)}):
                status, body, _ = self.call("POST", "/api/minipc/update", {}, token=self.token)
                self.assertEqual(status, 202)
                self.decide(self.pending(body["job"])["id"], approve)
                self.done(body["job"])
            self.assertEqual(run.call_count, int(approve))


if __name__ == "__main__":
    unittest.main()
