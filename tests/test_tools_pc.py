import dataclasses
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core.audit import Audit
from jarvis.core.permissions import Refused, execute
from jarvis.core.tools import REGISTRY, Level, _registry
from jarvis.tools.pc import system


def no(*_):
    return False


class PcToolTest(unittest.TestCase):
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

    def test_niveaux(self):
        for name in ("system_status", "list_processes", "search_files"):
            self.assertEqual(REGISTRY[name].level, Level.N0)


class SystemStatusTest(PcToolTest):
    def test_nominal(self):
        status = self.run_tool("system_status")
        self.assertTrue(0 <= status["cpu_percent"] <= 100)
        self.assertGreater(status["ram"]["total_gb"], 0)
        self.assertGreater(status["disk"]["total_gb"], 0)
        self.assertEqual(self.audit.last(1)[0][5], "auto")

    def test_sans_gpu(self):
        with mock.patch.object(system, "NVIDIA_SMI", Path("absent", "nvidia-smi.exe")):
            self.assertIsNone(self.run_tool("system_status")["gpu"])

    def test_gpu_sortie_illisible(self):
        with mock.patch.object(system.Path, "is_file", return_value=True), \
                mock.patch.object(system.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 5)):
            self.assertIsNone(system._gpu())

    def test_entree_invalide(self):
        with self.assertRaises(ValueError):
            self.run_tool("system_status", {"extra": 1})

    def test_permission_refusee(self):
        self.assert_refused_if_level_raised("system_status", {})


class ListProcessesTest(PcToolTest):
    def test_nominal(self):
        result = self.run_tool("list_processes")
        procs = result["processes"]
        self.assertGreater(result["total"], 0)
        self.assertLessEqual(len(procs), system.MAX_PROCESSES)
        self.assertEqual(procs, sorted(procs, key=lambda p: p["mem_mb"], reverse=True))

    def test_formats_memoire_locaux(self):
        out = '"a.exe","1","Console","1","2 048 Ko"\r\n"b.exe","2","Console","1","4,096 K"\r\n'
        fake = subprocess.CompletedProcess([], 0, stdout=out)
        with mock.patch.object(system.subprocess, "run", return_value=fake):
            result = system.list_processes()
        self.assertEqual(result["processes"], [{"name": "b.exe", "pid": 2, "mem_mb": 4.0},
                                               {"name": "a.exe", "pid": 1, "mem_mb": 2.0}])

    def test_entree_invalide(self):
        with self.assertRaises(ValueError):
            self.run_tool("list_processes", {"limit": 10})

    def test_permission_refusee(self):
        self.assert_refused_if_level_raised("list_processes", {})


class SearchFilesTest(PcToolTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "sous").mkdir()
        for name in ("Rapport-2026.pdf", "sous/rapport_final.docx", "sous/Écran.png", "autre.txt"):
            (root / name).write_text("x")

    def test_nominal_insensible_casse_et_accents(self):
        result = self.run_tool("search_files", {"name": "rapport", "folder": self.tmp.name})
        self.assertTrue(result["complete"])
        self.assertEqual(sorted(Path(p).name for p in result["results"]),
                         ["Rapport-2026.pdf", "rapport_final.docx"])
        found = self.run_tool("search_files", {"name": "ecran", "folder": self.tmp.name})["results"]
        self.assertEqual([Path(p).name for p in found], ["Écran.png"])

    def test_nombre_de_resultats_limite(self):
        for i in range(system.MAX_RESULTS + 10):
            Path(self.tmp.name, f"log{i}.txt").write_text("x")
        result = self.run_tool("search_files", {"name": "log", "folder": self.tmp.name})
        self.assertEqual(len(result["results"]), system.MAX_RESULTS)
        self.assertFalse(result["complete"])

    def test_entree_invalide(self):
        for bad in ({"name": "x"}, {"name": 3, "folder": self.tmp.name}):
            with self.assertRaises(ValueError):
                self.run_tool("search_files", bad)
        for bad in ({"name": "  ", "folder": self.tmp.name},
                    {"name": "x", "folder": str(Path(self.tmp.name, "nexiste_pas"))}):
            with self.assertRaises(ValueError):
                self.run_tool("search_files", bad)
        self.assertTrue(self.audit.last(1)[0][6].startswith("erreur"))

    def test_permission_refusee(self):
        self.assert_refused_if_level_raised("search_files", {"name": "x", "folder": self.tmp.name})

    def test_dossier_hors_racine_refuse_sans_acces_disque(self):
        # Sécurité constat 1 : UNC (fuite du hash NTLM), \\?\, ADS, nom réservé, sortie de la racine.
        for folder in (r"\\hote-attaquant\x", "//hote/x", r"\\?\C:\Windows", r"\\.\PhysicalDrive0",
                       r"C:\Windows", r"..\..\..", "NUL", r"documents\com1.txt",f"{self.tmp.name}:flux", "C:"):
            with mock.patch.object(Path, "is_dir", side_effect=AssertionError("accès disque")):
                with self.assertRaises(ValueError, msg=folder):
                    system.search_files("x", folder)

    def test_jonction_non_suivie(self):
        # Sécurité constat 2 : os.walk descend dans une jonction et sort de la racine.
        import _winapi
        base = Path(self.tmp.name)
        (base / "dehors").mkdir()
        (base / "dehors" / "secret.txt").write_text("x")
        _winapi.CreateJunction(str(base / "dehors"), str(base / "sous" / "lien"))
        found = system.search_files("secret", str(base / "sous"))["results"]
        self.assertEqual(found, [])
        self.assertEqual(Path(system.search_files("lien", str(base / "sous"))["results"][0]).name, "lien")


if __name__ == "__main__":
    unittest.main()
