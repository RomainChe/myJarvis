import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core.permissions import Refused
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.pc import files
from pcbase import PcBase, no, yes


class FilesBase(PcBase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.config = self.root / ".jarvis"
        self.config.mkdir()
        (self.config / "jarvis.db").write_text("journal")
        (self.root / "a.txt").write_text("a")
        (self.root / "dossier").mkdir()
        for patcher in (mock.patch.object(files, "CONFIG_DIR", self.config),
                        mock.patch.object(Path, "home", return_value=self.root)):  # le temp est sous AppData
            patcher.start()
            self.addCleanup(patcher.stop)


class DeleteFileTest(FilesBase):
    def test_niveau(self):
        self.assertEqual(REGISTRY["delete_file"].level, Level.N2)

    def test_nominal_passe_par_la_corbeille(self):
        target = self.root / "a.txt"
        with mock.patch.object(files, "_recycle", side_effect=lambda p: p.unlink()) as recycle:
            result = self.run_tool("delete_file", {"path": str(target)}, confirm=yes)
        recycle.assert_called_once_with(target)
        self.assertEqual(result, {"recycled": str(target)})

    def test_echec_si_le_fichier_est_toujours_la(self):
        with mock.patch.object(files, "_recycle"):
            with self.assertRaises(OSError):
                self.run_tool("delete_file", {"path": str(self.root / "a.txt")}, confirm=yes)

    def test_entree_invalide(self):
        home = Path.home()
        bad = [{}, {"path": 3}, {"path": "a", "force": True}, {"path": str(self.root / "absent.txt")},
               {"path": r"C:\Windows\System32\notepad.exe"}, {"path": r"\hote\partage\x"}, {"path": "~"},
               {"path": str(home)}, {"path": "documents"}, {"path": "Bureau"}, {"path": r"..\..\.."},
               {"path": str(self.config)}, {"path": str(self.config / "jarvis.db")},
               {"path": str(self.root / "a.txt:flux")}, {"path": str(self.root / "*")}]
        with mock.patch.object(files, "_recycle") as recycle:
            for args in bad:
                with self.assertRaises((ValueError, TypeError), msg=args):
                    self.run_tool("delete_file", args, confirm=yes)
        recycle.assert_not_called()

    def test_sans_confirmation_rien_ne_part(self):
        with mock.patch.object(files, "_recycle") as recycle:
            with self.assertRaises(Refused):
                self.run_tool("delete_file", {"path": str(self.root / "a.txt")}, confirm=no)
        recycle.assert_not_called()
        self.assertTrue((self.root / "a.txt").exists())
        self.assertEqual(self.audit.last(1)[0][5], "refusé")

    def test_jonction_vers_l_exterieur_refusee(self):
        import _winapi
        with tempfile.TemporaryDirectory(dir=self.root.anchor) as outside:  # hors du dossier utilisateur
            if Path(outside).resolve().is_relative_to(Path.home().resolve()):
                self.skipTest("dossier temporaire sous le dossier utilisateur")
            _winapi.CreateJunction(outside, str(self.root / "lien"))
            with mock.patch.object(files, "_recycle") as recycle:
                with self.assertRaises(ValueError):
                    self.run_tool("delete_file", {"path": str(self.root / "lien")}, confirm=yes)
            recycle.assert_not_called()


SENSITIVE = ("AppData/Roaming/x", ".ssh", ".gnupg", "projet/.git", "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup",
             "Start Menu/Programs/Startup")


class SensitiveFoldersTest(FilesBase):
    """S7 : AppData, .ssh, .gnupg, .git et Startup refusés en source et en destination."""

    def setUp(self):
        super().setUp()
        for rel in SENSITIVE:
            (self.root / rel).mkdir(parents=True)
            (self.root / rel / "f.txt").write_text("f")

    def test_source_refusee(self):
        with mock.patch.object(files, "_recycle") as recycle:
            for rel in SENSITIVE:
                for target in (self.root / rel, self.root / rel / "f.txt"):
                    with self.assertRaises(ValueError, msg=str(target)):
                        self.run_tool("delete_file", {"path": str(target)}, confirm=yes)
                    with self.assertRaises(ValueError, msg=str(target)):
                        self.run_tool("move_file", {"src": str(target), "dst": str(self.root / "sortie")}, confirm=yes)
        recycle.assert_not_called()

    def test_destination_refusee(self):
        for rel in SENSITIVE:
            for dst in (self.root / rel, self.root / rel / "nouveau.txt"):
                with self.assertRaises(ValueError, msg=str(dst)):
                    self.run_tool("move_file", {"src": str(self.root / "a.txt"), "dst": str(dst)}, confirm=yes)
        self.assertEqual((self.root / "a.txt").read_text(), "a")

    def test_nom_sensible_comme_nouveau_nom(self):
        with self.assertRaises(ValueError):
            self.run_tool("move_file", {"src": str(self.root / "a.txt"), "dst": str(self.root / ".git")}, confirm=yes)

    def test_dossier_ordinaire_accepte(self):
        self.run_tool("move_file", {"src": str(self.root / "a.txt"), "dst": str(self.root / "dossier")}, confirm=yes)
        self.assertTrue((self.root / "dossier" / "a.txt").exists())


class ConfirmationTest(FilesBase):
    def test_apercu_montre_le_chemin_resolu(self):
        (self.root / "dossier" / "sous").mkdir()
        raw = str(self.root / "dossier" / "sous" / ".." / ".." / "a.txt")
        shown = REGISTRY["delete_file"].preview({"path": raw})
        self.assertIn(str(self.root / "a.txt"), shown)
        self.assertNotIn("..", shown)
        shown = REGISTRY["move_file"].preview({"src": raw, "dst": str(self.root / "dossier")})
        self.assertIn(str(self.root / "a.txt"), shown)
        self.assertIn(str(self.root / "dossier" / "a.txt"), shown)

    def test_apercu_chemin_invalide_ne_plante_pas(self):
        self.assertIn("non résolu", REGISTRY["delete_file"].preview({"path": str(self.root / "absent")}))

    def test_la_cli_affiche_l_apercu(self):
        import jarvis.__main__ as cli
        raw = str(self.root / "dossier" / ".." / "a.txt")
        with mock.patch.object(cli.sys.stdin, "isatty", return_value=True),                 mock.patch("builtins.input", return_value="n") as ask:
            self.assertFalse(cli.confirm(REGISTRY["delete_file"], {"path": raw}))
        self.assertIn(str(self.root / "a.txt"), ask.call_args.args[0])


class RecycleTest(FilesBase):
    """S6 : _recycle ne bloque jamais sur une boîte de dialogue et ne supprime jamais définitivement."""

    def recycle(self, path, drive=files.DRIVE_FIXED, shell_code=0):
        flags = []

        def shell(ref):
            flags.append(ref._obj.fFlags)
            return shell_code

        with mock.patch.object(files, "_drive_type", return_value=drive),                 mock.patch.object(files, "_shell32") as sh:
            sh.SHFileOperationW.side_effect = shell
            files._recycle(path)
        return flags

    def test_nominal_flags_sans_dialogue_ni_suppression_definitive(self):
        (flags,) = self.recycle(self.root / "a.txt")
        for needed in (files.FOF_ALLOWUNDO, files.FOF_SILENT, files.FOF_NOCONFIRMATION, files.FOF_NOERRORUI):
            self.assertTrue(flags & needed, hex(needed))
        self.assertFalse(flags & files.FOF_WANTNUKEWARNING)  # partiellement incompatible avec NOCONFIRMATION : dialogue

    def test_lecteur_non_fixe_refuse(self):
        for drive in (2, 4, 5, 0):  # amovible, réseau, CD, inconnu
            with self.assertRaises(ValueError, msg=drive):
                self.recycle(self.root / "a.txt", drive=drive)

    def test_fichier_ou_dossier_trop_gros_refuse(self):
        (self.root / "dossier" / "x.bin").write_bytes(b"x" * 100)
        with mock.patch.object(files, "RECYCLE_MAX_BYTES", 50):
            for name in ("dossier", "dossier/x.bin"):
                with self.assertRaises(ValueError, msg=name):
                    self.recycle(self.root / name)
        self.recycle(self.root / "a.txt")  # petit : accepté

    def test_echec_du_shell(self):
        with self.assertRaises(OSError):
            self.recycle(self.root / "a.txt", shell_code=0x7C)

    def test_delete_file_ne_supprime_pas_si_refus(self):
        with mock.patch.object(files, "_drive_type", return_value=2),                 mock.patch.object(files, "_shell32") as sh:
            with self.assertRaises(ValueError):
                self.run_tool("delete_file", {"path": str(self.root / "a.txt")}, confirm=yes)
        sh.SHFileOperationW.assert_not_called()


class MoveFileTest(FilesBase):
    def test_niveau(self):
        self.assertEqual(REGISTRY["move_file"].level, Level.N2)

    def test_nominal_renommer_et_deplacer_dans_un_dossier(self):
        r = self.run_tool("move_file", {"src": str(self.root / "a.txt"), "dst": str(self.root / "b.txt")}, confirm=yes)
        self.assertEqual(r, {"moved": str(self.root / "b.txt")})
        self.assertTrue((self.root / "b.txt").exists() and not (self.root / "a.txt").exists())
        self.run_tool("move_file", {"src": str(self.root / "b.txt"), "dst": str(self.root / "dossier")}, confirm=yes)
        self.assertEqual((self.root / "dossier" / "b.txt").read_text(), "a")

    def test_entree_invalide(self):
        (self.root / "deja.txt").write_text("d")
        a = str(self.root / "a.txt")
        bad = [{"src": a}, {"src": 1, "dst": "x"}, {"src": str(self.root / "absent"), "dst": "x"},
               {"src": a, "dst": str(self.root / "deja.txt")},  # jamais d'écrasement
               {"src": a, "dst": r"C:\Windows\System32\a.txt"}, {"src": a, "dst": r"\hote\partage\a.txt"},
               {"src": a, "dst": str(self.root / "nul")}, {"src": a, "dst": str(self.root / "x.txt:flux")},
               {"src": a, "dst": str(self.root / "x*.txt")},
               {"src": a, "dst": str(self.root / "a.txt.")},
               {"src": a, "dst": str(self.config / "scripts.bat")}, {"src": a, "dst": str(self.config)},
               {"src": str(self.config / "jarvis.db"), "dst": str(self.root / "copie.db")},
               {"src": str(self.root / "dossier"), "dst": str(self.root / "dossier" / "sous")},
               {"src": "documents", "dst": str(self.root / "d")}, {"src": "~", "dst": str(self.root / "h")}]
        for args in bad:
            with self.assertRaises((ValueError, TypeError), msg=args):
                self.run_tool("move_file", args, confirm=yes)
        self.assertEqual((self.root / "a.txt").read_text(), "a")
        self.assertEqual((self.config / "jarvis.db").read_text(), "journal")

    def test_sans_confirmation_rien_ne_bouge(self):
        with mock.patch.object(files.shutil, "move") as move:
            with self.assertRaises(Refused):
                self.run_tool("move_file", {"src": str(self.root / "a.txt"), "dst": str(self.root / "b.txt")},
                              confirm=no)
        move.assert_not_called()
        self.assertTrue((self.root / "a.txt").exists())

    def test_permission_refusee(self):
        self.assert_refused_without_confirmation("move_file", {"src": "a", "dst": "b"})
        self.assert_refused_without_confirmation("delete_file", {"path": "a"})


if __name__ == "__main__":
    unittest.main()
