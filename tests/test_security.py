"""Tests de la revue de sécurité Phase 1 (docs/SECURITY_REVIEW_PHASE_1.md).

Chaque test reproduit une faille de la revue ; toutes sont corrigées.
"""
import importlib
import io
import os
import shutil
import sqlite3
import subprocess
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest import mock

import jarvis.__main__ as cli
from jarvis.core.audit import Audit
from jarvis.core.permissions import Refused, execute
from jarvis.core.tools import REGISTRY, Level, tool

ROOT = Path(__file__).resolve().parent.parent
calls = []


@tool("sec_read", "lecture", Level.N0)
def _read():
    calls.append("read")
    return "ok"


@tool("sec_delete", "suppression", Level.N2, path=str)
def _delete(path):
    calls.append(path)
    return "supprimé"


@tool("sec_lock", "serrure", Level.N3)
def _lock():
    calls.append("lock")
    return "ouvert"


@tool("sec_login", "connexion", Level.N1, user=str, password=str)
def _login(user, password):
    return "connecté"


def no(*_):
    return False


class SecurityTest(unittest.TestCase):
    def setUp(self):
        calls.clear()
        self.audit = Audit(":memory:")

    def run_tool(self, name, args=None, confirm=no, strong_auth=no, audit=None):
        return execute(name, {} if args is None else args, source="test", audit=audit or self.audit,
                       confirm=confirm, strong_auth=strong_auth)

    # --- Confirmation et garde ---

    def test_f1_confirmation_non_booleenne_refusee(self):
        # F1 : la garde teste la véracité ; un canal qui renvoie la réponse brute « non » confirme.
        with self.assertRaises(Refused):
            self.run_tool("sec_delete", {"path": "a.txt"}, confirm=lambda *_: "non")
        self.assertEqual(calls, [])

    def test_f2_args_executes_identiques_aux_args_confirmes(self):
        # F2 : la garde valide et confirme un dict, puis exécute ce dict tel qu'il est devenu.
        def confirm_then_mutate(_tool, args):
            args["path"] = "C:/Windows/System32"
            return True

        self.run_tool("sec_delete", {"path": "a.txt"}, confirm=confirm_then_mutate)
        self.assertEqual(calls, ["a.txt"])

    def test_f3_registre_non_modifiable_pour_baisser_un_niveau(self):
        # F3 : n'importe quel module peut remplacer un outil N3 par sa copie N0 (aucune trace, aucun N3).
        original = REGISTRY["sec_lock"]
        try:
            with self.assertRaises(TypeError):
                REGISTRY["sec_lock"] = replace(original, level=Level.N0)
        finally:
            if isinstance(REGISTRY, dict):
                REGISTRY["sec_lock"] = original

    def test_f4_confirmation_qui_plante_est_journalisee(self):
        # F4 : si confirm() lève (EOFError sur stdin fermé, canal coupé), aucune ligne d'audit.
        def broken_confirm(*_):
            raise EOFError

        with self.assertRaises(Exception):
            self.run_tool("sec_delete", {"path": "a.txt"}, confirm=broken_confirm)
        self.assertEqual(calls, [])
        self.assertEqual(len(self.audit.last()), 1)

    def test_f5_audit_indisponible_bloque_l_execution(self):
        # F5 : l'outil s'exécute avant l'écriture du journal ; si l'audit échoue, l'action a eu lieu sans trace.
        class BrokenAudit(Audit):
            def log(self, *a, **kw):
                raise OSError("disque plein")

        with self.assertRaises(OSError):
            self.run_tool("sec_read", audit=BrokenAudit(":memory:"))
        self.assertEqual(calls, [])

    # --- Journal d'audit ---

    def test_f6_insert_or_replace_ne_reecrit_pas_le_journal(self):
        # F6 : REPLACE supprime la ligne en conflit sans déclencher le trigger DELETE
        # (recursive_triggers désactivé par défaut) : réécriture de l'historique.
        self.audit.log("cli", "sec_lock", {}, 3, "refusé", None)
        with self.assertRaises(sqlite3.DatabaseError), self.audit.db:
            self.audit.db.execute(
                "INSERT OR REPLACE INTO audit (id, ts, source, tool, args, level, decision, result) "
                "VALUES (1, 'x', 'cli', 'sec_read', '{}', 0, 'auto', 'ok')"
            )
        self.assertEqual(self.audit.last(1)[0][2], "sec_lock")

    def test_f7_falsification_du_journal_detectee(self):
        # F7 : DROP TRIGGER puis DELETE efface une ligne ; rien ne permet de le détecter (pas de chaîne de hachage).
        for i in range(3):
            self.audit.log("cli", "sec_read", {}, 0, "auto", i)
        with self.audit.db:
            self.audit.db.executescript("DROP TRIGGER audit_no_delete; DELETE FROM audit WHERE id = 2;")
        self.assertFalse(self.audit.verify())

    def test_f8_secret_absent_du_journal(self):
        # F8 : les paramètres sont journalisés en clair ; un mot de passe finit dans la base.
        self.run_tool("sec_login", {"user": "moi", "password": "s3cr3t-valeur"})
        self.assertNotIn("s3cr3t-valeur", self.audit.last(1)[0][3])

    def test_f8_resultat_prive_resume(self):
        tool("sec_clip", "presse-papiers", Level.N1, private=True)(lambda: "mot-de-passe-colle")
        self.run_tool("sec_clip")
        self.assertEqual(self.audit.last(1)[0][6], "<str, 18 car.>")

    def test_f3_niveau_invalide_refuse(self):
        with self.assertRaises(ValueError):
            tool("sec_bad", "niveau inexistant", 7)(lambda: None)

    def test_f9_parametres_journalises_bornes(self):
        # F9 : seuls les résultats sont tronqués ; des arguments géants (appel LLM en boucle) gonflent la base.
        with self.assertRaises(ValueError):
            self.run_tool("inconnu", {"x": "a" * 1_000_000})
        self.assertLessEqual(len(self.audit.last(1)[0][3]), 2_000)

    # --- CLI ---

    def test_f10_cli_refuse_confirmation_hors_terminal(self):
        # F10 : `echo o | python -m jarvis run ...` confirme une action N2 sans humain devant l'écran.
        fake_stdin = io.StringIO("o\n")
        with mock.patch("sys.stdin", fake_stdin), redirect_stdout(io.StringIO()):
            self.assertFalse(cli.confirm(REGISTRY["sec_delete"], {"path": "a.txt"}))

    def test_f11_journal_jamais_en_memoire(self):
        # F11 : JARVIS_DB=:memory: désactive silencieusement le journal persistant.
        try:
            with mock.patch.dict(os.environ, {"JARVIS_DB": ":memory:"}), redirect_stdout(io.StringIO()):
                importlib.reload(cli)
                self.assertNotEqual(cli.main(["audit"]), 0)
        finally:
            importlib.reload(cli)

class ContreRevueTest(unittest.TestCase):
    """Constats 1 à 7 de la contre-revue (docs/SECURITY_REVIEW_PHASE_1.md)."""

    def setUp(self):
        calls.clear()
        self.audit = Audit(":memory:")

    def run_tool(self, name, args=None, confirm=no):
        return execute(name, {} if args is None else args, source="test", audit=self.audit,
                       confirm=confirm, strong_auth=no)

    def test_c1_hash_vide_detecte(self):
        for i in range(3):
            self.audit.log("cli", "sec_read", {}, 0, "auto", i)
        self.audit.db.executescript("DROP TRIGGER audit_no_update; DROP TRIGGER audit_no_delete;"
                                    "UPDATE audit SET hash = ''; DELETE FROM audit WHERE id = 2;")
        self.assertFalse(self.audit.verify())

    def test_c2_chaine_trop_longue_refusee(self):
        with self.assertRaises(ValueError):
            self.run_tool("sec_delete", {"path": "a" * 1001}, confirm=lambda *_: True)
        self.assertEqual(calls, [])

    def test_c2_troncature_par_valeur_garde_toutes_les_cles(self):
        self.audit.log("cli", "x" * 5000, {"pad": "a" * 5000, "cible": "C:/Windows"}, 0, "auto", None)
        row = self.audit.last(1)[0]
        self.assertIn("C:/Windows", row[3])
        self.assertLessEqual(len(row[2]), 100)

    def test_c3_nom_de_secret_non_standard_refuse(self):
        for name in ("Password", "user_password", "pin_code", "apiKey"):
            with self.assertRaises(ValueError, msg=name):
                tool(f"sec_{name}", "secret mal nommé", Level.N1, **{name: str})(lambda **_: None)

    def test_c3_confirmation_cli_masque_les_secrets(self):
        out = io.StringIO()
        with mock.patch("sys.stdin.isatty", return_value=True),                 mock.patch("builtins.input", lambda prompt: out.write(prompt) and "n"):
            cli.confirm(REGISTRY["sec_login"], {"user": "moi", "password": "s3cr3t"})
        self.assertNotIn("s3cr3t", out.getvalue())

    def test_c4_sous_classe_de_dict_refusee(self):
        class Trompeur(dict):
            def keys(self):
                return {"path": 1}.keys()
        with self.assertRaises(ValueError):
            self.run_tool("sec_delete", Trompeur(path="a.txt", extra="x"), confirm=lambda *_: True)
        self.assertEqual(calls, [])

    def test_c4_parametre_mutable_refuse(self):
        with self.assertRaises(ValueError):
            tool("sec_list", "liste", Level.N1, items=list)(lambda items: None)

    def test_c4_nan_refuse(self):
        tool("sec_float", "flottant", Level.N1, value=float)(lambda value: value)
        with self.assertRaises(ValueError):
            self.run_tool("sec_float", {"value": float("nan")})

    def test_c5_ctrl_c_a_la_confirmation_journalise(self):
        def ctrl_c(*_):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_tool("sec_delete", {"path": "a.txt"}, confirm=ctrl_c)
        self.assertEqual(self.audit.last(1)[0][5], "refusé")

    def test_c6_erreur_d_outil_prive_sans_message(self):
        def fuite():
            raise ValueError("contenu-prive-du-fichier")
        tool("sec_fuite", "privé", Level.N1, private=True)(fuite)
        with self.assertRaises(ValueError):
            self.run_tool("sec_fuite")
        self.assertNotIn("contenu-prive", self.audit.last(1)[0][6])

    def test_c7_resultat_lie_a_la_ligne_en_cours(self):
        self.run_tool("sec_read")
        (res_ref,), (start_ref,) = self.audit.db.execute("SELECT ref FROM audit ORDER BY id DESC LIMIT 2")
        start_id = self.audit.db.execute("SELECT MAX(id) - 1 FROM audit").fetchone()[0]
        self.assertIsNone(start_ref)
        self.assertEqual(res_ref, start_id)


@unittest.skipUnless(shutil.which("git"), "git requis")
class GitignoreTest(unittest.TestCase):
    def ignored(self, path):
        # Ignore le fichier d'exclusion global de la machine : seul le .gitignore du dépôt compte.
        cmd = ["git", "-c", f"core.excludesFile={os.devnull}", "check-ignore", "-q", "--no-index", path]
        return subprocess.run(cmd, cwd=ROOT).returncode == 0

    def test_f12_fichiers_sensibles_ignores_par_le_depot(self):
        # F12 : journaux SQLite annexes et réglages locaux de Claude ne sont pas ignorés par le dépôt public.
        for path in ("jarvis.db-wal", "jarvis.db-journal", "jarvis.sqlite3",
                     ".claude/settings.local.json", ".claude/worktrees/x/a.py"):
            self.assertTrue(self.ignored(path), path)

    def test_fichiers_deja_ignores(self):
        for path in (".env", ".env.local", "jarvis.db", "x.sqlite"):
            self.assertTrue(self.ignored(path), path)
        self.assertFalse(self.ignored(".env.example"))


if __name__ == "__main__":
    unittest.main()
