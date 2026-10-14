"""Onglet Voyages, étape 5 : `voyage_recherche` (N1, taint_blocked) lance le workflow `search.yml` par `gh workflow run`,
dans le clone du tracker, avec des champs validés passés en `-f clé=valeur` ; config.yaml jamais touché."""
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from jarvis.core import voyages
from jarvis.core.audit import Audit
from jarvis.core.permissions import Refused, execute
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools import voyages as tool

D1, D2, D3 = (str(date.today() + timedelta(days=n)) for n in (30, 40, 50))
ARGS = {"destination": "Thaïlande", "depart_from": D1, "depart_to": D2, "stay_days": "",
        "return_date": D3, "origins": "Paris, Barcelone", "alert_below": 0}


class RechercheTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / ".git").mkdir()
        p = mock.patch.object(voyages, "tracker_dir", return_value=self.root)
        p.start()
        self.addCleanup(p.stop)
        tool._last_search[0] = -tool.SEARCH_EVERY_S

    def test_nominal_lance_le_workflow_avec_les_champs(self):
        with mock.patch.object(tool.subprocess, "run") as run:
            out = tool.voyage_recherche(**ARGS)
        cmd, kw = run.call_args[0][0], run.call_args[1]
        self.assertEqual(cmd[:4], ["gh", "workflow", "run", "search.yml"])
        fields = dict(cmd[i + 1].split("=", 1) for i in range(4, len(cmd), 2))
        self.assertTrue(all(cmd[i] == "-f" for i in range(4, len(cmd), 2)))
        self.assertEqual(fields, {"destination": "Thaïlande", "origins": "Paris, Barcelone", "depart_from": D1,
                                  "depart_to": D2, "return_date": D3, "stay_days": "", "alert_below": ""})
        self.assertEqual((kw["cwd"], kw["env"]["GH_PROMPT_DISABLED"]), (self.root, "1"))
        self.assertIn("Thaïlande", out)

    def test_durees_et_seuil(self):
        with mock.patch.object(tool.subprocess, "run") as run:
            tool.voyage_recherche(**{**ARGS, "return_date": "", "stay_days": "14,10", "alert_below": 600})
        cmd = run.call_args[0][0]
        self.assertIn("stay_days=10, 14", cmd)
        self.assertIn("alert_below=600", cmd)

    def test_entree_invalide_rien_lance(self):
        for kw in ({"destination": "-x"}, {"origins": "a@b.fr"}, {"depart_from": "2000-01-01"}, {"stay_days": "10"}):
            with self.subTest(kw=kw), mock.patch.object(tool.subprocess, "run") as run, self.assertRaises(ValueError):
                tool.voyage_recherche(**{**ARGS, **kw})
            run.assert_not_called()

    def test_gh_en_echec_ou_absent(self):
        for err in (subprocess.CalledProcessError(1, "gh"), FileNotFoundError(), subprocess.TimeoutExpired("gh", 30)):
            tool._last_search[0] = -tool.SEARCH_EVERY_S
            with self.subTest(err=err), mock.patch.object(tool.subprocess, "run", side_effect=err), \
                    self.assertRaisesRegex(ValueError, "aucune recherche lancée"):
                tool.voyage_recherche(**ARGS)

    def test_sans_clone(self):
        (self.root / ".git").rmdir()
        with mock.patch.object(tool.subprocess, "run") as run, self.assertRaisesRegex(ValueError, "introuvable"):
            tool.voyage_recherche(**ARGS)
        run.assert_not_called()

    def test_une_recherche_par_minute(self):
        with mock.patch.object(tool.subprocess, "run") as run:
            tool.voyage_recherche(**ARGS)
            with self.assertRaisesRegex(ValueError, "une minute"):
                tool.voyage_recherche(**ARGS)
        self.assertEqual(run.call_count, 1)

    def test_n1_bloque_apres_contenu_externe(self):
        t = REGISTRY["voyage_recherche"]
        self.assertEqual((t.level, t.taint_blocked), (Level.N1, True))

    def test_permission_refusee_si_relevee_en_n2(self):
        audit = Audit(Path(tempfile.mkdtemp()) / "a.db")
        with mock.patch("jarvis.core.permissions.effective", return_value=Level.N2), \
                mock.patch.object(tool.subprocess, "run") as run, self.assertRaises(Refused):
            execute("voyage_recherche", ARGS, source="cli", audit=audit, confirm=lambda t, a: False, strong_auth=lambda t, a: False)
        run.assert_not_called()
        self.assertIn("voyage_recherche", str(audit.db.execute("SELECT * FROM audit").fetchall()))


if __name__ == "__main__":
    unittest.main()
