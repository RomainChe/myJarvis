"""Onglet Pilotes : /api/drivers (lu sur le PC par l'agent) et bouton « Go » (/api/drivers/update, N2 confirmé)."""
import dataclasses
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from jarvis import server
from jarvis.core import agentlink
from jarvis.core.tools import REGISTRY, Level, _registry
from test_chat import ChatBase

SNAP = {"configured": True, "at": "2026-10-20T09:00", "checking": False,
        "drivers": [{"id": "oem51.inf", "name": "RTX", "status": "moderate", "newer": True, "ignored": False, "days": 203}]}


def down(*a, **k):
    raise agentlink.AgentError("PC injoignable (TimeoutError)")


@mock.patch.object(server, "HAS_PC_TOOLS", False)
class DriversTabTest(ChatBase):
    def setUp(self):
        super().setUp()
        agentlink.register_proxies()

    def test_authentification_obligatoire(self):
        self.assertEqual(self.call("GET", "/api/drivers")[0], 401)
        self.assertEqual(self.call("POST", "/api/drivers/update", {})[0], 401)

    def test_lu_par_l_agent_et_journalise(self):
        with mock.patch.object(agentlink, "call", return_value={**SNAP, "started": True}) as call:
            status, body, _ = self.call("GET", "/api/drivers", token=self.token)
        self.assertEqual((status, body), (200, SNAP))
        self.assertEqual(call.call_args.args[:2], ("run", "pc_drivers"))
        self.assertLessEqual(call.call_args.kwargs["timeout"], 5)
        rows = [(r[2], r[6]) for r in self.audit.last(5)]
        self.assertIn(("drivers_read", "état des pilotes lu"), rows)
        self.assertIn(("drivers_check", "vérification DriverWatch lancée sur le PC"), rows)

    def test_pc_eteint(self):
        with mock.patch.object(agentlink, "call", side_effect=down):
            body = self.call("GET", "/api/drivers", token=self.token)[1]
        self.assertTrue(body["offline"])
        self.assertEqual(body["drivers"], [])

    def test_go_demande_confirmation_puis_lance(self):
        self.assertEqual(REGISTRY["driverwatch_update_all"].level, Level.N2)
        for approve in (False, True):
            run = mock.Mock(return_value={"driverwatch": "mise à jour lancée"})
            with mock.patch.dict(_registry, {"driverwatch_update_all": dataclasses.replace(REGISTRY["driverwatch_update_all"], run=run)}):
                status, body, _ = self.call("POST", "/api/drivers/update", {}, token=self.token)
                self.assertEqual(status, 202)
                p = self.pending(body["job"])
                self.decide(p["id"], approve)
                done = self.done(body["job"])
            self.assertEqual(run.call_count, int(approve))
            self.assertIn("lancée" if approve else "refusée", done["answer"])

    def test_bouton_d_une_ligne_demande_confirmation_puis_lance(self):
        self.assertEqual(REGISTRY["driverwatch_update_one"].level, Level.N2)
        self.assertEqual(self.call("POST", "/api/drivers/update-one", {"id": "oem51.inf"})[0], 401)
        self.assertEqual(self.call("POST", "/api/drivers/update-one", {"id": ""}, token=self.token)[0], 422)
        self.assertEqual(self.call("POST", "/api/drivers/update-one", {"id": "x" * 41}, token=self.token)[0], 422)
        for approve in (False, True):
            run = mock.Mock(return_value={"driverwatch": "mise à jour lancée"})
            with mock.patch.dict(_registry, {"driverwatch_update_one": dataclasses.replace(REGISTRY["driverwatch_update_one"], run=run, describe=None)}):
                status, body, _ = self.call("POST", "/api/drivers/update-one", {"id": "oem51.inf"}, token=self.token)
                self.assertEqual(status, 202)
                self.decide(self.pending(body["job"])["id"], approve)
                done = self.done(body["job"])
            self.assertEqual(run.call_args_list, [mock.call(driver_id="oem51.inf")] * int(approve))
            self.assertIn("lancée" if approve else "refusée", done["answer"])

    @unittest.skipUnless(shutil.which("node"), "Node absent : classement des pilotes non testé")
    def test_classement_cote_pwa(self):
        r = subprocess.run(["node", "--test", str(Path(__file__).with_name("pilotes.test.js"))], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
