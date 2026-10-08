import unittest
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

    def test_cli_ne_montre_jamais_la_valeur(self):
        with mock.patch("getpass.getpass", return_value="TOP-SECRET"), \
                mock.patch("builtins.print") as out:
            self.assertEqual(cli.main(["secret", "set", "ha_token"]), 0)
            self.assertEqual(cli.main(["secret", "check", "ha_token"]), 0)
        self.assertNotIn("TOP-SECRET", " ".join(str(c) for c in out.call_args_list))

    def test_cli_secret_inconnu(self):
        self.assertEqual(cli.main(["secret", "check", "nimporte"]), 2)


if __name__ == "__main__":
    unittest.main()
