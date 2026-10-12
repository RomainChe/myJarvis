import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core.permissions import Refused
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.pc import apps
from pcbase import PcBase, no, yes

NOTEPAD = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"


class AppsBase(PcBase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.write_apps({"Bloc-notes": str(NOTEPAD)})
        for attr, value in (("APPS_FILE", self.dir / "apps.json"), ("SCRIPTS_DIR", self.dir / "scripts")):
            patcher = mock.patch.object(apps, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        (self.dir / "scripts").mkdir()

    def write_apps(self, data):
        (self.dir / "apps.json").write_text(json.dumps(data), encoding="utf-8")


class OpenAppTest(AppsBase):
    def test_niveau(self):
        self.assertEqual(REGISTRY["open_app"].level, Level.N1)

    def test_nominal_liste_d_arguments_sans_shell(self):
        with mock.patch.object(apps.subprocess, "Popen") as popen:
            self.assertEqual(self.run_tool("open_app", {"name": "  BLOC-notes "}), {"opened": "bloc-notes"})
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [str(NOTEPAD)])  # aucun argument
        self.assertNotIn("shell", kwargs)

    def test_entree_invalide(self):
        for bad in ({}, {"name": 3}, {"name": "x", "args": "y"}):
            with self.assertRaises(ValueError):
                self.run_tool("open_app", bad)

    def test_application_hors_liste_blanche(self):
        with mock.patch.object(apps.subprocess, "Popen") as popen:
            for name in ("cmd", r"C:\Windows\System32\cmd.exe", "notepad.exe " + str(NOTEPAD), ""):
                with self.assertRaises(ValueError, msg=name):
                    self.run_tool("open_app", {"name": name})
        popen.assert_not_called()

    def test_entrees_de_config_dangereuses_ignorees(self):
        self.write_apps({"a": r"\\hote\partage\x.exe", "b": "C:x.exe", "c": r"C:\x\script.bat",
                         "d": 3, "e": r"relatif\x.exe", "bloc": str(NOTEPAD)})
        self.assertEqual(list(apps._apps()), ["bloc"])
        (self.dir / "apps.json").write_text("[1, 2]")
        self.assertEqual(apps._apps(), {})
        (self.dir / "apps.json").write_text("{pas du json")
        with self.assertRaises(ValueError):
            apps._apps()
        (self.dir / "apps.json").unlink()
        with self.assertRaises(ValueError):
            apps._apps()

    def test_permission_refusee(self):
        self.assert_refused_if_level_raised("open_app", {"name": "bloc-notes"})


class CloseAppTest(AppsBase):
    def test_nominal_ferme_les_fenetres_de_l_exe_autorise(self):
        with mock.patch.object(apps, "_windows_of", return_value=[11, 22]) as found, \
                mock.patch.object(apps, "_post_close") as close:
            self.assertEqual(self.run_tool("close_app", {"name": "bloc-notes"}), {"closed_windows": 2})
        found.assert_called_once_with(NOTEPAD)
        self.assertEqual([c.args[0] for c in close.call_args_list], [11, 22])

    def test_entree_invalide_et_hors_liste(self):
        with self.assertRaises(ValueError):
            self.run_tool("close_app", {"name": 1})
        with mock.patch.object(apps, "_post_close") as close:
            with self.assertRaises(ValueError):
                self.run_tool("close_app", {"name": "explorer"})
        close.assert_not_called()

    def test_enumeration_reelle_sans_effet(self):
        # Aucune fenêtre n'appartient à cet exécutable inexistant : rien n'est fermé.
        self.assertEqual(apps._windows_of(Path(r"C:\inexistant\x.exe")), [])

    def test_permission_refusee(self):
        self.assert_refused_if_level_raised("close_app", {"name": "bloc-notes"})


class RunScriptTest(AppsBase):
    def script(self, name="hello.bat", text="@echo bonjour\r\n"):
        path = self.dir / "scripts" / name
        path.write_text(text)
        return path

    def test_niveau_et_drapeaux(self):
        tool = REGISTRY["run_script"]
        self.assertEqual(tool.level, Level.N2)
        self.assertTrue(tool.private and tool.external)

    def test_nominal_reel_script_inoffensif(self):
        self.script()
        result = self.run_tool("run_script", {"name": "hello.bat"}, confirm=yes)
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("bonjour", result["output"])
        self.assertNotIn("bonjour", str(self.audit.last(1)[0]))  # sortie privée : jamais journalisée

    def test_commande_sans_shell_ni_argument(self):
        self.script("a.ps1", "x")
        fake = subprocess.CompletedProcess([], 3, stdout="o", stderr="e")
        with mock.patch.object(apps.subprocess, "run", return_value=fake) as run:
            result = self.run_tool("run_script", {"name": "a.ps1"}, confirm=yes)
        self.assertEqual(result, {"exit_code": 3, "output": "oe"})
        cmd, kwargs = run.call_args.args[0], run.call_args.kwargs
        self.assertEqual(cmd[-2:], ["-File", ".\\a.ps1"])
        self.assertIsInstance(cmd, list)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(Path(kwargs["cwd"]), (self.dir / "scripts").resolve())

    def test_entree_invalide(self):
        self.script()
        outside = self.dir / "dehors.bat"
        outside.write_text("@echo x")
        bad = ("hello", "hello.exe", "..\\dehors.bat", "../dehors.bat", str(outside), "sous\\x.bat", "con.bat",
               "hello.bat arg", "hello.bat & calc", "hello.bat:flux", "absent.bat", "")
        with mock.patch.object(apps.subprocess, "run") as run:
            for name in bad:
                with self.assertRaises(ValueError, msg=name):
                    self.run_tool("run_script", {"name": name}, confirm=yes)
            with self.assertRaises(ValueError):
                self.run_tool("run_script", {"name": "hello.bat", "args": "x"}, confirm=yes)
        run.assert_not_called()

    def test_lien_physique_refuse(self):
        """S3 : un lien physique vers un fichier hors du dossier échappe à resolve()."""
        outside = self.dir / "dehors.bat"
        outside.write_text("@echo x")
        try:
            os.link(outside, self.dir / "scripts" / "lien.bat")
        except OSError:
            self.skipTest("liens physiques indisponibles")
        with mock.patch.object(apps.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                self.run_tool("run_script", {"name": "lien.bat"}, confirm=yes)
        run.assert_not_called()

    def test_script_modifie_apres_confirmation_refuse(self):
        """S3 : l'empreinte affichée à la confirmation est revérifiée avant l'exécution."""
        path = self.script()
        preview = REGISTRY["run_script"].preview({"name": "hello.bat"})
        self.assertIn("SHA-256", preview)
        path.write_text("@echo piege\r\n")  # modifié entre la confirmation et l'exécution
        with mock.patch.object(apps.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                self.run_tool("run_script", {"name": "hello.bat"}, confirm=yes)
        run.assert_not_called()
        REGISTRY["run_script"].preview({"name": "hello.bat"})  # nouvelle confirmation : accepté
        self.assertIn("piege", self.run_tool("run_script", {"name": "hello.bat"}, confirm=yes)["output"])

    def test_permission_refusee(self):
        self.script()
        with mock.patch.object(apps.subprocess, "run") as run:
            with self.assertRaises(Refused):
                self.run_tool("run_script", {"name": "hello.bat"}, confirm=no)
        run.assert_not_called()
        self.assertEqual(self.audit.last(1)[0][5], "refusé")


class KillProcessTest(PcBase):
    def test_niveau(self):
        self.assertEqual(REGISTRY["kill_process"].level, Level.N2)

    def test_nominal_apres_confirmation(self):
        with mock.patch.object(apps, "_kill") as kill:
            result = self.run_tool("kill_process", {"pid": 4242, "name": "notepad.exe"}, confirm=yes)
        kill.assert_called_once_with(4242, "notepad.exe")
        self.assertEqual(result, {"killed": 4242, "name": "notepad.exe"})

    def test_sans_confirmation_rien_ne_part(self):
        with mock.patch.object(apps, "_kill") as kill:
            with self.assertRaises(Refused):
                self.run_tool("kill_process", {"pid": 4242, "name": "notepad.exe"}, confirm=no)
        kill.assert_not_called()

    def test_entree_invalide(self):
        with mock.patch.object(apps, "_kill") as kill:
            for bad in ({"pid": "12", "name": "x.exe"}, {"pid": 12}, {"pid": True, "name": "x.exe"},
                        {"pid": 0, "name": "x.exe"}, {"pid": 4, "name": "System"}, {"pid": -5, "name": "x.exe"},
                        {"pid": os.getpid(), "name": "python.exe"}, {"pid": 12, "name": "  "},
                        {"pid": 2 ** 40, "name": "x.exe"}):
                with self.assertRaises(ValueError, msg=bad):
                    self.run_tool("kill_process", bad, confirm=yes)
        kill.assert_not_called()

    def test_cible_verifiee(self):
        apps._check_target(r"C:\Program Files\App\App.exe", "app.EXE", 1)
        for image, name in ((r"C:\Program Files\App\App.exe", "autre.exe"),  # PID réattribué
                            (r"C:\Windows\System32\lsass.exe", "lsass.exe"),  # processus système
                            (r"C:\Windows\explorer.exe", "explorer.exe")):
            with self.assertRaises(ValueError, msg=image):
                apps._check_target(image, name, 1)

    def test_processus_de_jarvis_proteges(self):  # S8 minimal : Tailscale et Ollama ne se coupent pas à distance
        for exe in ("tailscaled.exe", "Tailscale.exe", "tailscale-ipn.exe", "ollama.exe", "ollama app.exe",
                    "ollama_llama_server.exe", "OLLAMA.EXE"):
            image = rf"C:\Program Files\Truc\{exe}"
            with self.assertRaises(ValueError, msg=exe):
                apps._check_target(image, exe, 1)
        apps._check_target(r"C:\Program Files\Truc\olla.exe", "olla.exe", 1)  # pas de préfixe trop large

    def test_kill_refuse_un_processus_protege_sans_le_terminer(self):
        with mock.patch.object(apps, "_k32") as k32, mock.patch.object(apps, "_long_path", side_effect=lambda p: p),                 mock.patch.object(apps, "_image_of", return_value=r"C:\Ollama\ollama.exe"):
            k32.OpenProcess.return_value = 1234
            with self.assertRaises(ValueError):
                apps._kill(4242, "ollama.exe")
        k32.TerminateProcess.assert_not_called()
        k32.CloseHandle.assert_called_once_with(1234)

    def test_chemin_court_8_3_ramene_a_la_forme_longue(self):  # S8 complet
        short = r"C:\PROGRA~1\Truc\OLLAMA~1.EXE"
        long = r"C:\Program Files\Truc\ollama app.exe"
        with mock.patch.object(apps, "_long_path", side_effect=lambda p: long if "~" in p else p):
            with self.assertRaises(ValueError):
                apps._check_target(short, "ollama app.exe", 1)
        if os.path.isdir(r"C:\Program Files"):  # expansion réelle
            self.assertEqual(apps._long_path(r"C:\PROGRA~1"), r"C:\Program Files")
        self.assertEqual(apps._long_path(r"C:\nexiste\pas.exe"), r"C:\nexiste\pas.exe")
        with self.assertRaises(ValueError):  # nom court sans forme longue lisible : échec fermé
            apps._long_path(r"C:\nexiste\TAILSC~1.EXE")

    def test_vm_home_assistant_protegee_hors_dossier_windows(self):
        for exe in ("vmwp.exe", "vmms.exe"):
            with self.assertRaises(ValueError, msg=exe):
                apps._check_target(rf"D:\Hyper\{exe}", exe, 1)

    def test_ancetre_de_jarvis_refuse_sans_rien_terminer(self):
        with mock.patch.object(apps, "ancestors", return_value={4242}), mock.patch.object(apps, "_k32") as k32:
            with self.assertRaises(ValueError):
                apps._kill(4242, "cmd.exe")
        k32.OpenProcess.assert_not_called()

    def test_ancetres_reels_contiennent_le_parent(self):
        from jarvis.tools.pc import system
        self.assertTrue(system.ancestors(os.getpid()))

    def test_apercu_montre_le_chemin_de_l_image(self):
        image = r"C:\Apps\notepad.exe"
        with mock.patch.object(apps, "_k32") as k32, mock.patch.object(apps, "_long_path", side_effect=lambda p: p),                 mock.patch.object(apps, "_image_of", return_value=image):
            k32.OpenProcess.return_value = 99
            self.assertIn(image, REGISTRY["kill_process"].preview({"pid": 7, "name": "notepad.exe"}))

    def test_pid_inexistant_leve_une_erreur_sans_rien_tuer(self):
        with self.assertRaises(OSError):
            apps._kill(0x7FFFFFF0, "x.exe")

    def test_permission_refusee(self):
        self.assert_refused_if_level_raised("kill_process", {"pid": 4242, "name": "notepad.exe"})


if __name__ == "__main__":
    unittest.main()
