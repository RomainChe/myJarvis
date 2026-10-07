import sqlite3
import unittest

from jarvis.core.audit import Audit
from jarvis.core.permissions import Refused, execute
from jarvis.core.tools import REGISTRY, Level, tool

calls = []


@tool("test_read", "lecture", Level.N0)
def _read():
    calls.append("read")
    return "ok"


@tool("test_volume", "volume", Level.N1, value=int)
def _volume(value):
    calls.append(value)
    return value


@tool("test_delete", "suppression", Level.N2, path=str)
def _delete(path):
    calls.append(path)
    return "supprimé"


@tool("test_lock", "serrure", Level.N3)
def _lock():
    calls.append("lock")
    return "ouvert"


@tool("test_crash", "plante", Level.N1)
def _crash():
    raise RuntimeError("boum")


def yes(*_):
    return True


def no(*_):
    return False


class GateTest(unittest.TestCase):
    def setUp(self):
        calls.clear()
        self.audit = Audit(":memory:")

    def run_tool(self, name, args=None, confirm=no, strong_auth=no):
        return execute(name, args or {}, source="test", audit=self.audit, confirm=confirm, strong_auth=strong_auth)

    def last_decision(self):
        return self.audit.last(1)[0][5]

    def test_n0_n1_automatiques_sans_confirmation(self):
        self.assertEqual(self.run_tool("test_read"), "ok")
        self.assertEqual(self.run_tool("test_volume", {"value": 30}), 30)
        self.assertEqual(calls, ["read", 30])
        self.assertEqual(self.last_decision(), "auto")

    def test_n2_confirme(self):
        self.assertEqual(self.run_tool("test_delete", {"path": "a.txt"}, confirm=yes), "supprimé")
        self.assertEqual(self.last_decision(), "confirmé")

    def test_n2_refuse_n_execute_rien(self):
        with self.assertRaises(Refused):
            self.run_tool("test_delete", {"path": "a.txt"}, confirm=no)
        self.assertEqual(calls, [])
        self.assertEqual(self.last_decision(), "refusé")

    def test_n3_exige_confirmation_et_auth_forte(self):
        with self.assertRaises(Refused):
            self.run_tool("test_lock", confirm=yes, strong_auth=no)
        with self.assertRaises(Refused):
            self.run_tool("test_lock", confirm=no, strong_auth=yes)
        self.assertEqual(calls, [])
        self.assertEqual(self.run_tool("test_lock", confirm=yes, strong_auth=yes), "ouvert")

    def test_entree_invalide_rejetee_et_journalisee(self):
        for bad in ({}, {"value": "30"}, {"value": True}, {"value": 1, "extra": 2}):
            with self.assertRaises(ValueError):
                self.run_tool("test_volume", bad)
        self.assertEqual(calls, [])
        self.assertEqual(self.last_decision(), "invalide")

    def test_outil_inconnu(self):
        with self.assertRaises(ValueError):
            self.run_tool("nexiste_pas")
        self.assertEqual(self.last_decision(), "inconnu")

    def test_erreur_d_outil_journalisee(self):
        with self.assertRaises(RuntimeError):
            self.run_tool("test_crash")
        self.assertEqual(self.audit.last(1)[0][6], "erreur : boum")

    def test_double_enregistrement_interdit(self):
        with self.assertRaises(ValueError):
            tool("test_read", "doublon", Level.N0)(lambda: None)
        self.assertEqual(REGISTRY["test_read"].description, "lecture")


class AuditTest(unittest.TestCase):
    def test_journal_en_ajout_seul(self):
        audit = Audit(":memory:")
        audit.log("test", "x", {}, 0, "auto", "ok")
        for sql in ("UPDATE audit SET decision = 'refusé'", "DELETE FROM audit"):
            with self.assertRaises(sqlite3.DatabaseError):
                with audit.db:
                    audit.db.execute(sql)
        self.assertEqual(len(audit.last()), 1)

    def test_resultat_tronque(self):
        audit = Audit(":memory:")
        audit.log("test", "x", {}, 0, "auto", "a" * 10_000)
        self.assertEqual(len(audit.last(1)[0][6]), 500)


if __name__ == "__main__":
    unittest.main()
