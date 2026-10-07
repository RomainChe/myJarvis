"""Robustesse du cœur : cas limites, journal SQLite en panne, concurrence, latence de la garde.

Les tests marqués expectedFailure reproduisent un bug ouvert (voir docs/QA_REPORT_PHASE_1.md).
Quand le bug est corrigé, le test passe et unittest le signale : retirer alors le décorateur.
"""
import os
import sqlite3
import statistics
import tempfile
import threading
import time
import unittest

from jarvis.core.audit import Audit
from jarvis.core.permissions import Refused, execute
from jarvis.core.tools import Level, tool

calls = []


@tool("qa_read", "lecture factice", Level.N0)
def _read():
    calls.append("read")
    return "ok"


@tool("qa_volume", "volume factice", Level.N1, value=int)
def _volume(value):
    calls.append(value)
    return value


@tool("qa_delete", "suppression factice (aucun fichier touché)", Level.N2, path=str)
def _delete(path):
    calls.append(path)
    return "supprimé"


@tool("qa_lock", "serrure factice", Level.N3)
def _lock():
    calls.append("lock")
    return "ouvert"


def no(*_):
    return False


def run(audit, name, args=None, confirm=no, strong_auth=no):
    return execute(name, {} if args is None else args, source="qa", audit=audit,
                   confirm=confirm, strong_auth=strong_auth)


def fill_disk(audit):
    """Simule un disque plein : la base ne peut plus grossir d'une seule page."""
    pages = audit.db.execute("PRAGMA page_count").fetchone()[0]
    audit.db.execute(f"PRAGMA max_page_count = {pages + 2}")
    # Petites lignes : on comble aussi l'espace libre des pages, toute écriture suivante échoue.
    for _ in range(1000):
        try:
            audit.log("qa", "remplissage", {}, 0, "auto", None)
        except sqlite3.OperationalError:
            return
    raise AssertionError("le disque plein simulé n'a jamais été atteint")


class TempDbCase(unittest.TestCase):
    def setUp(self):
        calls.clear()
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = os.path.join(self.tmp.name, "jarvis.db")
        self.conns = []
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: [c.close() for c in self.conns])

    def open_audit(self):
        audit = Audit(self.path)
        self.conns.append(audit.db)
        return audit

    def count(self, audit):
        return audit.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]


class EntreesLimitesTest(unittest.TestCase):
    def setUp(self):
        calls.clear()
        self.audit = Audit(":memory:")

    @unittest.expectedFailure
    def test_args_non_dict_rejetes_proprement(self):
        # BUG-03 : une liste d'arguments (sortie LLM mal formée) lève AttributeError, sans journal.
        with self.assertRaises(ValueError):
            run(self.audit, "qa_volume", ["30"])
        self.assertEqual(self.audit.last(1)[0][5], "invalide")

    @unittest.expectedFailure
    def test_nom_d_outil_none_rejete_et_journalise(self):
        # BUG-04 : None viole la contrainte NOT NULL du journal, IntegrityError au lieu de ValueError.
        with self.assertRaises(ValueError):
            run(self.audit, None)
        self.assertEqual(self.audit.last(1)[0][5], "inconnu")

    @unittest.expectedFailure
    def test_confirmation_exige_un_vrai_oui(self):
        # BUG-02 : la garde teste la vérité de la réponse ; "non" ou un objet quelconque vaut oui.
        with self.assertRaises(Refused):
            run(self.audit, "qa_delete", {"path": "a.txt"}, confirm=lambda *_: "non")
        with self.assertRaises(Refused):
            run(self.audit, "qa_lock", confirm=lambda *_: True, strong_auth=lambda *_: object())
        self.assertEqual(calls, [])

    @unittest.expectedFailure
    def test_confirmation_qui_plante_est_journalisee(self):
        # BUG-05 : si la confirmation lève (app déconnectée), rien n'est exécuté mais rien n'est journalisé.
        def boom(*_):
            raise ConnectionError("app injoignable")
        with self.assertRaises(Exception):
            run(self.audit, "qa_delete", {"path": "a.txt"}, confirm=boom)
        self.assertEqual(calls, [])
        self.assertEqual(self.audit.last(1)[0][5], "refusé")

    def test_confirmation_qui_plante_n_execute_rien(self):
        def boom(*_):
            raise ConnectionError("app injoignable")
        with self.assertRaises(ConnectionError):
            run(self.audit, "qa_delete", {"path": "a.txt"}, confirm=boom)
        self.assertEqual(calls, [])

    def test_n0_n1_n_appellent_jamais_la_confirmation(self):
        def interdit(*_):
            raise AssertionError("confirmation demandée pour N0/N1")
        run(self.audit, "qa_read", confirm=interdit, strong_auth=interdit)
        run(self.audit, "qa_volume", {"value": 5}, confirm=interdit, strong_auth=interdit)
        self.assertEqual(calls, ["read", 5])

    def test_auth_forte_non_demandee_si_confirmation_refusee(self):
        asked = []
        with self.assertRaises(Refused):
            run(self.audit, "qa_lock", confirm=no, strong_auth=lambda *_: asked.append(1) or True)
        self.assertEqual(asked, [])

    def test_valeurs_limites_d_entier_acceptees(self):
        for v in (0, -1, 2**63):
            self.assertEqual(run(self.audit, "qa_volume", {"value": v}), v)

    def test_float_refuse_pour_un_entier(self):
        with self.assertRaises(ValueError):
            run(self.audit, "qa_volume", {"value": 30.0})

    def test_arguments_non_serialisables_journalises(self):
        # default=str dans json.dumps : un objet exotique ne doit pas casser le journal.
        with self.assertRaises(ValueError):
            run(self.audit, "qa_volume", {"value": object()})
        self.assertIn("object", self.audit.last(1)[0][3])

    def test_unicode_et_injection_sql_stockes_tels_quels(self):
        evil = "'); DROP TABLE audit; -- é🚀"
        run(self.audit, "qa_delete", {"path": evil}, confirm=lambda *_: True)
        self.assertIn(evil, self.audit.last(1)[0][3])
        self.assertEqual(calls, [evil])


class JournalEnPanneTest(TempDbCase):
    @unittest.expectedFailure
    def test_disque_plein_aucune_action_sans_journal(self):
        # BUG-01 : l'outil s'exécute AVANT l'écriture du journal ; disque plein = action faite, non tracée.
        audit = self.open_audit()
        fill_disk(audit)
        with self.assertRaises(sqlite3.OperationalError):
            run(audit, "qa_volume", {"value": 1})
        self.assertEqual(calls, [])

    @unittest.expectedFailure
    def test_base_verrouillee_aucune_action_sans_journal(self):
        # BUG-01 (même cause) : base verrouillée par un autre processus.
        audit = self.open_audit()
        audit.db.execute("PRAGMA busy_timeout = 100")
        locker = sqlite3.connect(self.path)
        self.conns.append(locker)
        locker.execute("BEGIN EXCLUSIVE")
        with self.assertRaises(sqlite3.OperationalError):
            run(audit, "qa_volume", {"value": 1})
        self.assertEqual(calls, [])

    def test_disque_plein_erreur_explicite_et_base_coherente(self):
        audit = self.open_audit()
        fill_disk(audit)
        before = self.count(audit)
        with self.assertRaises(sqlite3.OperationalError) as ctx:
            audit.log("qa", "x", {"pad": "x" * 4000}, 0, "auto", None)
        self.assertIn("full", str(ctx.exception))
        self.assertEqual(self.count(audit), before)  # transaction annulée
        self.assertEqual(audit.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_base_verrouillee_puis_liberee(self):
        audit = self.open_audit()
        audit.db.execute("PRAGMA busy_timeout = 100")
        locker = sqlite3.connect(self.path)
        self.conns.append(locker)
        locker.execute("BEGIN EXCLUSIVE")
        with self.assertRaises(sqlite3.OperationalError):
            audit.log("qa", "x", {}, 0, "auto", "ok")
        locker.rollback()
        audit.log("qa", "x", {}, 0, "auto", "ok")
        self.assertEqual(self.count(audit), 1)

    def test_base_corrompue_refusee_a_l_ouverture(self):
        with open(self.path, "wb") as f:
            f.write(b"ceci n'est pas une base SQLite" * 100)
        with self.assertRaises(sqlite3.DatabaseError):
            self.open_audit()

    def test_triggers_supprimes_sont_recrees_a_l_ouverture(self):
        audit = self.open_audit()
        audit.log("qa", "x", {}, 0, "auto", "ok")
        audit.db.executescript("DROP TRIGGER audit_no_delete; DROP TRIGGER audit_no_update;")
        audit2 = self.open_audit()
        with self.assertRaises(sqlite3.DatabaseError):
            with audit2.db:
                audit2.db.execute("DELETE FROM audit")
        self.assertEqual(self.count(audit2), 1)

    def test_persistance_apres_reouverture(self):
        self.open_audit().log("qa", "x", {"k": 1}, 1, "auto", "ok")
        self.assertEqual(self.open_audit().last(1)[0][2], "x")

    def test_last_ordre_et_limite(self):
        audit = self.open_audit()
        for i in range(5):
            audit.log("qa", f"t{i}", {}, 0, "auto", None)
        self.assertEqual([r[2] for r in audit.last(3)], ["t4", "t3", "t2"])
        self.assertEqual(audit.last(0), [])


class ConcurrenceTest(TempDbCase):
    def test_ecritures_concurrentes_une_connexion_par_thread(self):
        # Cas CLI + futur serveur : plusieurs connexions sur le même fichier.
        n_threads, n_logs = 8, 25
        errors = []
        self.open_audit()  # crée le schéma

        def target():
            audit = Audit(self.path)
            try:
                for i in range(n_logs):
                    audit.log("qa", "concurrent", {"i": i}, 0, "auto", None)
            except Exception as e:
                errors.append(e)
            finally:
                audit.db.close()

        threads = [threading.Thread(target=target) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(self.count(self.open_audit()), n_threads * n_logs)

    @unittest.expectedFailure
    def test_journal_partage_entre_threads(self):
        # BUG-06 : sqlite3.connect(check_same_thread=True) ; un Audit créé au démarrage
        # devient inutilisable depuis un thread de travail (FastAPI exécute le sync en pool).
        audit = self.open_audit()
        errors = []

        def target():
            try:
                audit.log("qa", "thread", {}, 0, "auto", None)
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=target)
        t.start()
        t.join()
        self.assertEqual(errors, [])


class LatenceTest(TempDbCase):
    def test_surcout_de_la_garde_sous_100_ms(self):
        # Budget Phase 1 : action locale < 500 ms. La garde + l'écriture disque n'en prennent qu'une fraction.
        audit = self.open_audit()
        samples = []
        for _ in range(20):
            t0 = time.perf_counter()
            run(audit, "qa_read")
            samples.append(time.perf_counter() - t0)
        self.assertLess(statistics.median(samples), 0.100, f"médiane {statistics.median(samples):.3f} s")


if __name__ == "__main__":
    unittest.main()
