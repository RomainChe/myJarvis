import json
import unittest
from unittest import mock

from bench import run_bench as rb


def call(tool, **args):
    return {"tool": tool, "args": args}


class TestCommands(unittest.TestCase):
    def test_jeu_de_30_commandes_valide(self):
        data = rb.load()
        self.assertEqual(len(data["commands"]), 30)
        self.assertEqual(len(data["tools"]), 18)  # 16 lignes de la roadmap, dont 2 doubles
        self.assertEqual(len({c["id"] for c in data["commands"]}), 30)

    def test_format_ollama(self):
        t = rb.ollama_tools([{"name": "screen_off", "description": "d", "params": {}}])[0]
        self.assertEqual(t["function"]["parameters"], {"type": "object", "properties": {}, "required": []})


class TestScore(unittest.TestCase):
    vol = [[call("set_volume", level=30)]]

    def test_nominal(self):
        self.assertEqual(rb.score(self.vol, [call("set_volume", level=30)]), (True, True))

    def test_mauvais_parametre(self):
        self.assertEqual(rb.score(self.vol, [call("set_volume", level=3)]), (True, False))
        self.assertEqual(rb.score(self.vol, [call("set_volume", level="30")]), (True, False))
        self.assertEqual(rb.score(self.vol, [call("set_volume")]), (True, False))

    def test_bool_n_est_pas_un_entier(self):
        self.assertEqual(rb.score([[call("set_volume", level=1)]], [call("set_volume", level=True)]),
                         (True, False))

    def test_mauvais_outil_ou_aucun(self):
        self.assertEqual(rb.score(self.vol, [call("mute", muted=True)]), (False, False))
        self.assertEqual(rb.score(self.vol, []), (False, False))

    def test_texte_sans_casse_ni_accents(self):
        exp = [[call("run_script", name="sauv")]]
        self.assertEqual(rb.score(exp, [call("run_script", name="Sauvegarde.ps1")]), (True, True))
        exp = [[call("open_app", name="ecran")]]
        self.assertEqual(rb.score(exp, [call("open_app", name="Écran")]), (True, True))

    def test_alternatives(self):
        exp = [[call("mute", muted=True)], [call("set_volume", level=0)]]
        self.assertEqual(rb.score(exp, [call("set_volume", level=0)]), (True, True))

    def test_aucun_appel_attendu(self):
        self.assertEqual(rb.score([[]], []), (True, True))
        self.assertEqual(rb.score([[]], [call("delete_file", path="C:\\Windows")]), (False, False))

    def test_injection_appel_en_trop(self):
        exp = [[call("open_app", name="notepad")]]
        got = [call("open_app", name="notepad"), call("power", action="shutdown")]
        self.assertEqual(rb.score(exp, got), (False, False))

    def test_multi_etapes(self):
        exp = [[call("media_control", action="pause"), call("lock_session")]]
        self.assertEqual(rb.score(exp, [call("lock_session"), call("media_control", action="pause")]),
                         (True, True))
        self.assertEqual(rb.score(exp, [call("lock_session")]), (False, False))


class TestStream(unittest.TestCase):
    def test_appel_d_outil(self):
        lines = [
            json.dumps({"message": {"content": ""}}),
            "",
            json.dumps({"message": {"tool_calls": [{"function": {"name": "set_volume", "arguments": {"level": 30}}}]}}),
            json.dumps({"message": {"content": ""}, "done": True, "eval_count": 12}),
        ]
        text, calls, ttft, last = rb.parse_stream(lines, 0.0)
        self.assertEqual(calls, [call("set_volume", level=30)])
        self.assertIsNotNone(ttft)
        self.assertTrue(last["done"])

    def test_arguments_en_chaine_et_invalides(self):
        lines = [json.dumps({"message": {"tool_calls": [
            {"function": {"name": "mute", "arguments": '{"muted": true}'}},
            {"function": {"name": "mute", "arguments": "{pas du json"}},
        ]}})]
        _, calls, _, _ = rb.parse_stream(lines, 0.0)
        self.assertEqual(calls[0], call("mute", muted=True))
        self.assertIn("_invalide", calls[1]["args"])

    def test_texte_sans_appel(self):
        lines = [json.dumps({"message": {"content": "Fermer quoi"}}), json.dumps({"message": {"content": " ?"}})]
        text, calls, _, _ = rb.parse_stream(lines, 0.0)
        self.assertEqual((text, calls), ("Fermer quoi ?", []))

    def test_erreur_ollama(self):
        with self.assertRaises(RuntimeError):
            rb.parse_stream([json.dumps({"error": "model not found"})], 0.0)


class TestSummary(unittest.TestCase):
    def test_pourcentages_et_medianes(self):
        res = [{"tool": True, "args": True, "ttft_s": 0.2, "total_s": 0.5},
               {"tool": True, "args": False, "ttft_s": None, "total_s": 1.5},
               {"tool": False, "args": False, "ttft_s": 0.4, "total_s": 0.9},
               {"tool": True, "args": True, "ttft_s": 0.3, "total_s": 0.7}]
        s = rb.summarize(res)
        self.assertEqual((s["outil_pct"], s["params_pct"]), (75, 50))
        self.assertEqual((s["ttft_median_s"], s["total_median_s"], s["total_max_s"]), (0.3, 0.9, 1.5))


class TestArretPropre(unittest.TestCase):
    def test_ollama_absent(self):
        with mock.patch.object(rb, "_get", side_effect=rb.urllib.error.URLError("refusé")):
            with self.assertRaises(SystemExit) as e:
                rb.main(["qwen3:8b"])
        self.assertIn("injoignable", str(e.exception.code))

    def test_modele_absent_sans_telechargement(self):
        with mock.patch.object(rb, "_get", return_value={"models": [{"name": "autre:latest"}]}), \
                mock.patch.object(rb, "_chat") as chat:
            with self.assertRaises(SystemExit) as e:
                rb.main(["qwen3"])
        self.assertIn("qwen3:latest", str(e.exception.code))
        chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
