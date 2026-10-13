import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import keyring
from keyring.backend import KeyringBackend

from jarvis import __main__ as cli
from jarvis.core import secrets


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.d = {}

    def set_password(self, service, name, value):
        self.d[(service, name)] = value

    def get_password(self, service, name):
        return self.d.get((service, name))

    def delete_password(self, service, name):
        self.d.pop((service, name), None)


class TestSecrets(unittest.TestCase):
    def setUp(self):
        self.old = keyring.get_keyring()
        keyring.set_keyring(MemoryKeyring())

    def tearDown(self):
        keyring.set_keyring(self.old)

    def test_aller_retour_avec_espaces_retires(self):
        secrets.set_secret("ha_token", " abc \n")
        self.assertEqual(secrets.get_secret("ha_token"), "abc")

    def test_nom_inconnu_et_valeur_vide_refuses(self):
        with self.assertRaises(ValueError):
            secrets.set_secret("autre", "x")
        with self.assertRaises(ValueError):
            secrets.set_secret("ha_token", "  ")

    def test_cle_de_signature_des_mails_trop_courte_refusee(self):
        with self.assertRaises(ValueError):
            secrets.set_secret("mail_sig_key", "court")
        secrets.set_secret("mail_sig_key", "a" * 32)
        self.assertEqual(secrets.get_secret("mail_sig_key"), "a" * 32)

    def test_cli_ne_montre_jamais_la_valeur(self):
        with mock.patch("getpass.getpass", return_value="TOP-SECRET"), \
                mock.patch("builtins.print") as out:
            self.assertEqual(cli.main(["secret", "set", "ha_token"]), 0)
            self.assertEqual(cli.main(["secret", "check", "ha_token"]), 0)
        self.assertNotIn("TOP-SECRET", " ".join(str(c) for c in out.call_args_list))

    def test_cli_secret_inconnu(self):
        self.assertEqual(cli.main(["secret", "check", "nimporte"]), 2)

    def test_identifiant_systemd_prime_sur_le_coffre(self):
        secrets.set_secret("ha_token", "coffre")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ha_token").write_text("systemd\n")
            with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": d}):
                self.assertEqual(secrets.get_secret("ha_token"), "systemd")
                self.assertEqual(secrets.get_secret("bank_key"), None)  # absent du dossier : coffre

    def test_export_ecrit_les_fichiers_sans_afficher_les_valeurs(self):
        secrets.set_secret("ha_token", "TOP-SECRET")
        with tempfile.TemporaryDirectory() as d, mock.patch("builtins.print") as out:
            self.assertEqual(cli.main(["secret", "export", d]), 0)
            self.assertEqual((Path(d) / "ha_token").read_text(), "TOP-SECRET")
            self.assertFalse((Path(d) / "bank_key").exists())
        self.assertNotIn("TOP-SECRET", " ".join(str(c) for c in out.call_args_list))

    def test_export_refuse_le_depot_et_remplace_un_fichier_existant(self):
        secrets.set_secret("ha_token", "TOP-SECRET")
        with self.assertRaises(ValueError):
            secrets.export_all(Path(secrets.__file__).resolve().parents[2] / "out")
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "ha_token"
            old.write_text("ancien")
            os.chmod(old, 0o644)
            secrets.export_all(Path(d))
            self.assertEqual(old.read_text(), "TOP-SECRET")
            if os.name == "posix":
                self.assertEqual(old.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
