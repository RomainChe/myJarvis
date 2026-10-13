"""Le Core démarre sans outils PC (mini-PC Linux, docs/MIGRATION_CORE_MINIPC.md lot 1).

Simulé dans un processus à part : `JARVIS_PC_TOOLS=0` et tout import de `jarvis.tools.pc` bloqué.
Le vrai essai sous Linux reste à faire sur le mini-PC.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = """
import sys
class BlockPc:  # tout import de jarvis.tools.pc échoue, comme sous Linux (ctypes.WinDLL absent)
    def find_spec(self, name, path=None, target=None):
        if name == "jarvis.tools.pc" or name.startswith("jarvis.tools.pc."):
            raise ImportError("outils PC absents : " + name)
sys.meta_path.insert(0, BlockPc())
import jarvis.core.chat, jarvis.server, jarvis.__main__
from jarvis.core.tools import REGISTRY
from jarvis.core.router import Router
from jarvis.core import games
assert not any(n in REGISTRY for n in ("power", "system_status", "lock_session", "open_app")), sorted(REGISTRY)
assert "tv_on" in REGISTRY and "pc_plug_on" in REGISTRY and "reminder_set" in REGISTRY
assert games.process_names() == set()
print("OK")
"""


class CorePortableTest(unittest.TestCase):
    def run_core(self, **env) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, capture_output=True, text=True,
                              timeout=60, env={**os.environ, **env})

    def test_import_sans_outils_pc(self):
        done = self.run_core(JARVIS_PC_TOOLS="0")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("OK", done.stdout)

    def test_arret_du_pc_refuse_sans_outils_pc(self):
        code = "from jarvis.tools.home import pcplug\npcplug.pc_off_plug()\n"
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60,
                              env={**os.environ, "JARVIS_PC_TOOLS": "0"})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("agent PC requis", done.stderr)


if __name__ == "__main__":
    unittest.main()
