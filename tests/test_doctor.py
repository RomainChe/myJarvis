import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import doctor
from jarvis.core.audit import Audit


class WatchTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "watchdog.json"
        self.audit = Audit(str(Path(tmp.name) / "jarvis.db"))
        self.addCleanup(self.audit.db.close)
        self.restart, self.notify, self.t = mock.Mock(), mock.Mock(), [1_000_000.0]

    def watch(self, up):
        return doctor.watch(self.audit, up=up, restart=self.restart, notify=self.notify, state=self.state,
                            now=lambda: self.t[0], sleep=lambda s: None)

    def test_chaine_rompue_alerte_une_fois_par_heure(self):
        notify_health = mock.Mock()
        self.audit.log("cli", "x", {}, 1, "auto", 1)
        self.audit.db.execute("DROP TRIGGER audit_no_update")
        self.audit.db.execute("UPDATE audit SET args = '{\"a\": 1}' WHERE id = 1")  # chaîne rompue

        def run():
            return doctor.watch(self.audit, up=lambda: True, restart=self.restart, notify=self.notify,
                                state=self.state, now=lambda: self.t[0], sleep=lambda s: None,
                                notify_health=notify_health)
        run()
        run()  # moins d'une heure plus tard : pas de nouveau contrôle
        notify_health.assert_called_once()
        self.assertEqual(self.audit.last(1)[0][2], "audit_health")
        self.t[0] += 2 * 3600
        run()
        self.assertEqual(notify_health.call_count, 2)

    def test_chaine_saine_ne_notifie_pas(self):
        notify_health = mock.Mock()
        doctor.watch(self.audit, up=lambda: True, notify=self.notify, state=self.state, now=lambda: self.t[0],
                     notify_health=notify_health)
        notify_health.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "schtasks : Windows seulement")
    def test_schtasks_par_chemin_absolu(self):
        with mock.patch.object(doctor.subprocess, "run") as run:
            doctor.restart_task()
        for call in run.call_args_list:
            self.assertTrue(Path(call.args[0][0]).is_absolute())
            self.assertEqual(Path(call.args[0][0]).name, "schtasks.exe")

    def test_systemd_hors_windows(self):
        with mock.patch.object(doctor.sys, "platform", "linux"), mock.patch.object(doctor.subprocess, "run") as run:
            doctor.restart_task()
        run.assert_called_once_with(["/usr/bin/systemctl", "--user", "restart", doctor.UNIT], check=False)

    def test_core_vivant_ne_fait_rien(self):
        self.assertEqual(self.watch(lambda: True), "ok")
        self.restart.assert_not_called()

    def test_un_raté_isolé_ne_relance_pas(self):
        answers = iter([False, True])
        self.assertEqual(self.watch(lambda: next(answers)), "ok")
        self.restart.assert_not_called()

    def test_core_muet_relance_journalise_et_notifie(self):
        self.assertEqual(self.watch(lambda: False), "relancé")
        self.restart.assert_called_once()
        self.notify.assert_called_once()
        self.assertEqual(self.audit.last(1)[0][2], "core_restart")

    def test_pas_de_relance_pendant_le_delai_de_grace(self):
        self.watch(lambda: False)
        self.t[0] += 30
        self.assertEqual(self.watch(lambda: False), "attente")
        self.assertEqual(self.restart.call_count, 1)

    def test_une_seule_alerte_par_30_min(self):
        self.watch(lambda: False)
        self.t[0] += 120
        self.watch(lambda: False)
        self.assertEqual(self.restart.call_count, 2)
        self.assertEqual(self.notify.call_count, 1)
        self.t[0] += doctor.COOLDOWN_S
        self.watch(lambda: False)
        self.assertEqual(self.notify.call_count, 2)

    def test_push_en_panne_ne_bloque_pas_la_relance(self):
        self.notify.side_effect = RuntimeError("réseau")
        self.assertEqual(self.watch(lambda: False), "relancé")
        self.restart.assert_called_once()

    def test_etat_illisible_ignore(self):
        self.state.write_text("{pas du json")
        self.assertEqual(self.watch(lambda: False), "relancé")


class ReportTest(unittest.TestCase):
    def test_un_controle_qui_plante_est_un_ko_et_n_arrete_pas_le_bilan(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            audit = Audit(str(Path(d) / "j.db"))
            self.addCleanup(audit.db.close)
            with mock.patch.object(doctor, "http_up", return_value=True), \
                    mock.patch("jarvis.core.ha.version", side_effect=OSError("x")):
                out = dict(doctor.report(audit, 8765, Path(d) / "b", Path(d) / "m"))
        self.assertIsNone(out["core"])
        self.assertIn("impossible", out["home assistant"])
        self.assertIn("aucune sauvegarde", out["sauvegarde"])
        self.assertIsNone(out["modèles"])


if __name__ == "__main__":
    unittest.main()
