"""Onglets Système, Bien-être et Réseaux sur le Core du mini-PC : données du PC lues par l'agent (pc_bienetre, pc_social)."""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from jarvis import server
from jarvis.core import agentlink, llm, social
from jarvis.core.audit import Audit
from jarvis.core.permissions import Refused, execute
from test_server import ServerBase

SNAP = {"configured": True, "published": [{"platform": "youtube", "title": "clip", "at": "2026-10-16T20:00"}],
        "scheduled": [], "youtube": {"subs": 12, "views": 340, "videos": 5}}


def down(*a, **k):
    raise agentlink.AgentError("PC injoignable (TimeoutError)")


class KeptTest(unittest.TestCase):
    def setUp(self):
        self.cache = Path(tempfile.mkdtemp()) / "social-cache.json"
        self.now = lambda: datetime(2026, 10, 17, 11, 5)

    def test_releve_garde_puis_rendu_pc_eteint(self):
        self.assertEqual(social.kept(lambda: SNAP, self.cache, self.now), SNAP)
        self.assertEqual(social.kept(down, self.cache, self.now), {**SNAP, "stale": "2026-10-17T11:05"})

    def test_pc_eteint_sans_releve(self):
        self.assertEqual(social.kept(down, self.cache)["stale"], None)

    def test_copie_illisible_ou_disque_plein(self):
        self.cache.write_text("{pas du json")
        self.assertIsNone(social.kept(down, self.cache)["stale"])
        self.assertEqual(social.kept(lambda: SNAP, Path(tempfile.mkdtemp()) / "absent" / "x.json"), SNAP)

    def test_autre_erreur_non_masquee(self):
        with self.assertRaises(ValueError):
            social.kept(lambda: (_ for _ in ()).throw(ValueError("bug")), self.cache)


@mock.patch.object(server, "HAS_PC_TOOLS", False)
class MiniPcRoutesTest(ServerBase):
    def setUp(self):
        super().setUp()
        cache = mock.patch.object(social, "CACHE", Path(tempfile.mkdtemp()) / "social-cache.json")
        cache.start()
        self.addCleanup(cache.stop)
        _, self.token = self.enroll("tel")

    def test_authentification_obligatoire(self):
        for path in ("/api/bienetre", "/api/social"):
            self.assertEqual(self.call("GET", path)[0], 401, path)

    def test_bienetre_par_l_agent(self):
        with mock.patch.object(agentlink, "call", return_value={"configured": True, "counts": {"OK": 3}}) as call:
            status, body, _ = self.call("GET", "/api/bienetre", token=self.token)
        self.assertEqual((status, body["counts"]), (200, {"OK": 3}))
        self.assertEqual(call.call_args.args[:2], ("run", "pc_bienetre"))
        self.assertLessEqual(call.call_args.kwargs["timeout"], 5)  # PC éteint : l'onglet ne reste pas bloqué

    def test_bienetre_pc_eteint(self):
        with mock.patch.object(agentlink, "call", side_effect=down):
            body = self.call("GET", "/api/bienetre", token=self.token)[1]
        self.assertTrue(body["offline"] and body["configured"])
        self.assertIsNone(body["counts"])

    def test_reseaux_releve_puis_pc_eteint(self):
        with mock.patch.object(agentlink, "call", return_value=SNAP):
            self.assertEqual(self.call("GET", "/api/social", token=self.token)[1], SNAP)
        with mock.patch.object(agentlink, "call", side_effect=down):
            body = self.call("GET", "/api/social", token=self.token)[1]
        self.assertEqual(body["youtube"], SNAP["youtube"])
        self.assertIsNotNone(body["stale"])


    def test_lancement_du_bilan_journalise_par_le_core(self):
        with mock.patch.object(agentlink, "call", return_value={"configured": True, "running": True, "started": True}):
            body = self.call("GET", "/api/bienetre", token=self.token)[1]
        self.assertNotIn("started", body)
        self.assertIn(("bienetre_run", "lancé sur le PC"), [(r[2], r[6]) for r in self.audit.last(5)])


class PanelToolsTest(unittest.TestCase):
    def test_catalogue_n0_jamais_propose_au_llm(self):
        entries = {e["name"]: e for e in json.loads(agentlink.CATALOG.read_text(encoding="utf-8"))}
        agentlink.register_proxies()
        offered = {s["function"]["name"] for s in llm.schemas()}
        for name in ("pc_bienetre", "pc_social"):
            self.assertEqual((entries[name]["level"], entries[name]["owner_only"]), (0, True), name)
            self.assertNotIn(name, offered)

    def test_permission_refusee_au_llm_et_a_la_voix(self):
        agentlink.register_proxies()
        audit = Audit(":memory:")
        for name in ("pc_bienetre", "pc_social"):
            for source in ("llm", "voix"):
                with self.assertRaises(Refused), mock.patch.object(agentlink, "call") as call:
                    execute(name, {}, source=source, audit=audit, confirm=lambda *a: True, strong_auth=lambda *a: True)
                call.assert_not_called()
                row = audit.last(1)[0]
                self.assertEqual((row[2], row[5]), (name, "refusé"))

    @unittest.skipUnless(sys.platform == "win32", "outils PC Windows")
    def test_pc_social_relaie_le_snapshot_filtre(self):
        from jarvis.tools.pc import panels
        with mock.patch.object(panels.social, "snapshot", return_value={"published": [], "scheduled": [], "configured": True}), \
                mock.patch.object(panels._youtube, "snapshot", return_value=None):
            self.assertEqual(panels.pc_social(), {"published": [], "scheduled": [], "configured": True, "youtube": None})


if __name__ == "__main__":
    unittest.main()
