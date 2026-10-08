import unittest

import jarvis.tools.pc  # noqa: F401  (outils réels : delete_file, clipboard_read, open_app...)
from jarvis.core import levels
from jarvis.core.audit import Audit
from jarvis.core.permissions import Refused, execute
from jarvis.core.tools import REGISTRY, Level, tool


@tool("test_lv_light", "lumière", Level.N1)
def _light():
    return "ok"


class LevelsTest(unittest.TestCase):
    def setUp(self):
        self.audit = Audit(":memory:")
        levels.load(self.audit)
        self.addCleanup(setattr, levels, "_audit", None)

    def run_tool(self, confirm):
        asked = []
        return asked, lambda: execute("test_lv_light", {}, source="t", audit=self.audit,
                                       confirm=lambda t, a: asked.append(1) or confirm,
                                       strong_auth=lambda t, a: False)

    def test_sans_surcharge_le_niveau_du_registre_s_applique(self):
        self.assertEqual(levels.effective(REGISTRY["test_lv_light"]), Level.N1)

    def test_relever_est_libre_et_impose_la_confirmation(self):
        levels.set_level("test_lv_light", 2, strong_auth=False)
        asked, call = self.run_tool(False)
        with self.assertRaises(Refused):
            call()
        self.assertEqual(asked, [1])
        asked, call = self.run_tool(True)
        self.assertEqual(call(), "ok")

    def test_abaisser_exige_l_authentification_forte(self):
        levels.set_level("test_lv_light", 2, strong_auth=False)
        with self.assertRaises(PermissionError):
            levels.set_level("test_lv_light", 1, strong_auth=False)
        self.assertEqual(levels.effective(REGISTRY["test_lv_light"]), Level.N2)
        levels.set_level("test_lv_light", 1, strong_auth=True)
        self.assertEqual(levels.effective(REGISTRY["test_lv_light"]), Level.N1)
        self.assertEqual(self.audit.db.execute("SELECT COUNT(*) FROM levels").fetchone()[0], 0)  # retour au registre

    def test_les_planchers_ne_descendent_jamais(self):
        for name in ("delete_file", "move_file", "kill_process", "power", "run_script"):
            with self.assertRaises(ValueError, msg=name):
                levels.set_level(name, 1, strong_auth=True)
            self.assertGreaterEqual(levels.effective(REGISTRY[name]), Level.N2)

    def test_un_n2_hors_plancher_peut_descendre_avec_n3(self):
        with self.assertRaises(PermissionError):
            levels.set_level("clipboard_read", 1, strong_auth=False)
        levels.set_level("clipboard_read", 1, strong_auth=True)
        self.assertEqual(levels.effective(REGISTRY["clipboard_read"]), Level.N1)

    def test_entrees_invalides(self):
        for name, level in (("inconnu", 2), ("test_lv_light", 4), ("test_lv_light", -1)):
            with self.assertRaises(ValueError):
                levels.set_level(name, level, strong_auth=True)

    def test_ecriture_directe_en_base_sous_le_plancher_reste_au_plancher(self):
        self.audit.db.execute("INSERT INTO levels VALUES ('delete_file', 0)")
        self.assertEqual(levels.effective(REGISTRY["delete_file"]), Level.N2)

    def test_sans_load_le_registre_s_applique_et_chat_charge_les_surcharges(self):
        from jarvis.core.chat import Chat
        levels._audit = None
        Chat(self.audit)
        self.assertIs(levels._audit, self.audit)

    def test_un_refus_est_journalise_avec_l_ancien_niveau(self):
        with self.assertRaises(ValueError):
            levels.set_level("delete_file", 0, strong_auth=True)
        row = self.audit.last(1)[0]
        self.assertEqual((row[1], row[5]), ("levels", "refusé"))
        self.assertIn('"from": 2', row[3])

    def test_chaque_outil_reel_a_un_titre_et_un_groupe(self):
        import jarvis.tools.home  # noqa: F401
        for name in REGISTRY.keys() - {"test_lv_light"}:
            if not name.startswith("test_"):
                self.assertIn(name, levels.LABELS, "ajouter le titre de l'outil dans levels.LABELS")
        self.assertEqual(levels.label(REGISTRY["tv_on"])["group"], "Maison")
        self.assertEqual(levels.label(REGISTRY["delete_file"]), {"title": "Supprimer un fichier",
                         "description": "Envoie à la corbeille, récupérable.", "group": "PC"})
        self.assertEqual(levels.label(REGISTRY["test_lv_light"])["title"], "test_lv_light")  # repli : le nom

    def test_chaque_changement_est_journalise(self):
        levels.set_level("test_lv_light", 3, strong_auth=False)
        self.assertEqual(self.audit.last(1)[0][1:3], ("levels", "test_lv_light"))


if __name__ == "__main__":
    unittest.main()
