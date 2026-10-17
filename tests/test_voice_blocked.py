"""Lot 4c : outils jamais exécutés à la voix, même en N1 (décision du propriétaire, 2026-10-17)."""
import dataclasses
import unittest
from unittest import mock

from jarvis.core.audit import Audit
from jarvis.core.host import load_pc_tools
from jarvis.core.permissions import Refused, execute
from jarvis.core.tools import REGISTRY, _registry


class VoiceBlockedTest(unittest.TestCase):
    def refused_by_voice(self, name, args):
        load_pc_tools()
        ran = []
        fake = dataclasses.replace(REGISTRY[name], run=lambda **kw: ran.append(kw))
        audit = Audit(":memory:")
        with mock.patch.dict(_registry, {name: fake}):
            for source in ("voix", "voix/llm"):
                with self.assertRaises(Refused):
                    execute(name, args, source=source, audit=audit, confirm=lambda t, a: True, strong_auth=lambda t, a: True)
            self.assertEqual(ran, [])  # rien n'a tourné
        self.assertEqual(audit.db.execute("SELECT count(*) FROM audit WHERE decision='refusé'").fetchone()[0], 2)

    def test_clipboard_write_refuse_a_la_voix(self):
        self.refused_by_voice("clipboard_write", {"text": "x"})

    def test_driverwatch_accept_refuse_a_la_voix(self):
        self.refused_by_voice("driverwatch_accept", {})


if __name__ == "__main__":
    unittest.main()
