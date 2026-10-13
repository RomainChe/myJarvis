import sys
import unittest

if sys.platform != "win32":  # outils PC Windows : testés sur le PC principal seulement
    raise unittest.SkipTest("outils PC Windows")

import subprocess
import os
import tempfile
import time
from pathlib import Path
from unittest import mock

from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.pc import system
from pcbase import PcBase


class PcToolTest(PcBase):
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

    def test_gpu_sans_fenetre(self):
        with mock.patch.object(system.Path, "is_file", return_value=True), \
                mock.patch.object(system.subprocess, "run", side_effect=OSError) as run:
            system._gpu()
        self.assertEqual(run.call_args.kwargs.get("creationflags"), subprocess.CREATE_NO_WINDOW)

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

    def test_contient_ce_processus_et_rapide(self):
        start = time.perf_counter()
        procs = system.list_processes()["processes"]
        self.assertLess(time.perf_counter() - start, 0.5)  # QA-R5
        self.assertTrue(all(p["name"] and p["pid"] >= 0 for p in procs))
        self.assertGreater(procs[0]["mem_mb"], 0)

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
                       r"C:\Windows", r"..\..\..", "NUL", r"documents\com1.txt", f"{self.tmp.name}:flux", "C:",
                       r"\/hote/x", r"/\hote\x", "CONIN$", "CLOCK$", "documents/COM¹"):
            with mock.patch.object(Path, "is_dir", side_effect=AssertionError("accès disque")), \
                    mock.patch.object(Path, "resolve", side_effect=AssertionError("accès disque")):
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

    def test_dossier_tenu_ouvert_ne_peut_etre_ni_renomme_ni_remplace(self):
        """R3 : tant que la marche tient le handle, une jonction ne peut pas prendre la place du dossier."""
        base = Path(self.tmp.name)
        k32 = system._k32_search()
        handle = system._open_real_dir(k32, str(base / "sous"), None)
        self.assertIsNotNone(handle)
        try:
            with self.assertRaises(OSError):
                os.rename(base / "sous", base / "sous2")
        finally:
            k32.CloseHandle(handle)
        os.rename(base / "sous", base / "sous2")  # une fois fermé, le dossier est libre

    def test_racine_et_dossiers_refuses_par_handle(self):
        import _winapi
        base = Path(self.tmp.name)
        k32 = system._k32_search()
        (base / "dehors").mkdir()
        _winapi.CreateJunction(str(base / "dehors"), str(base / "lien"))
        self.assertIsNone(system._open_real_dir(k32, str(base / "lien"), None))  # jonction
        self.assertIsNone(system._open_real_dir(k32, str(base / "Rapport-2026.pdf"), None))  # fichier
        self.assertIsNone(system._open_real_dir(k32, str(base / "nexiste_pas"), None))
        self.assertIsNone(system._open_real_dir(k32, str(base), r"c:\windows"))  # hors de la racine autorisée

    def test_racine_substituee_par_une_jonction_refusee(self):
        import _winapi
        base = Path(self.tmp.name)
        (base / "dehors").mkdir()
        (base / "dehors" / "secret.txt").write_text("x")
        _winapi.CreateJunction(str(base / "dehors"), str(base / "racine"))
        with self.assertRaises(ValueError):  # resolve() suit la jonction : elle sort de `base`, jamais lue
            system.search_files("secret", str(base / "racine") + "\..\..\..\..\..\..\..\..")


if __name__ == "__main__":
    unittest.main()
