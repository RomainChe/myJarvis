"""Comparatif des IA (Veille IA) : reconnaissance des noms, notes sur 100, sources lues hors ligne, relevé quotidien,
route authentifiée et journalisée."""
import io
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from contextlib import closing
from datetime import datetime, date
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from jarvis.core import iacompare as ia
from jarvis.core import secrets
from tests.test_server import ServerBase

CAT = ia.load_catalog()


def epoch_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


EPOCH = epoch_zip({
    "swe_bench_verified.csv": "Model version,mean_score,Release date\n"
                              "claude-opus-5-5-20261001,0.81,2026-10-01\nclaude-opus-5-20260601,0.74,2026-06-01\n"
                              "claude-opus-5-5-20261001,0.79,2026-10-01\ngpt-6-astra,0.70,2026-08-01\nautre-modele,0.2,2026-01-01\n",
    "epoch_capabilities_index/eci_scores.csv": "Model version,eci\nclaude-opus-5-5,160\ngpt-6-astra,150\nx,120\ny,130\nz,140\n",
    "gpqa_diamond.csv": "Model,Score\nclaude-opus-5-5,pas un nombre\n",
    "benchmark_metadata.csv": "benchmark,score_column\nswe,mean_score\n",
})


def arena_get(rows_by_cat: dict):
    def get(url, limit, headers=None, opener=None):
        q = parse_qs(urlsplit(url).query)
        cat = (q["config"][0], q["where"][0].split("'")[1])
        rows = rows_by_cat.get(cat, [])
        off = int(q["offset"][0])
        page = rows[off:off + 100]
        return json.dumps({"rows": [{"row_idx": i, "row": r} for i, r in enumerate(page)], "num_rows_total": len(rows)}).encode()
    return get


def arow(name, rating, rank=1, org="anthropic"):
    return {"model_name": name, "organization": org, "rating": rating, "rank": rank}


ARENA = {
    ("text", "coding"): [arow("Claude Opus 5.5 (High)", 1500, 1), arow("Claude Opus 5 (Max)", 1480, 2), arow("Petit", 1300, 3),
                         arow("Moyen", 1400, 4)],
    ("text", "overall"): [arow("Claude Opus 5.5 (High)", 1516, 1), arow("Nouveau Modèle X", 1510, 2, "openai"),
                          arow("Hors labo", 1505, 3, "inconnu"), arow("Claude Opus 5", 1400, 4), arow("Bas", 1300, 5, "inconnu")],
}


class MatchTest(unittest.TestCase):
    def test_variantes_et_dates_acceptees(self):
        self.assertTrue(ia.matches("Claude Opus 5 (Max)", "claude-opus-5"))
        self.assertTrue(ia.matches("claude-opus-4-5-20251101", "claude-opus-4-5"))
        self.assertTrue(ia.matches("GPT-6 Astra (Max)", "gpt-6-astra"))
        self.assertTrue(ia.matches("Qwen3.7-Max-Preview", "qwen3-7-max"))

    def test_autre_version_ou_declinaison_refusee(self):
        self.assertFalse(ia.matches("Claude Opus 5.5 (High)", "claude-opus-5"))
        self.assertFalse(ia.matches("Gemini 3.5 Flash-Lite", "gemini-3-5-flash"))
        self.assertFalse(ia.matches("GLM-5.3-Flash", "glm-5-3"))
        self.assertFalse(ia.matches("GLM-5V-Turbo", "glm-5"))
        self.assertFalse(ia.matches("", "glm-5"))

    def test_cle_la_plus_longue_gagne(self):
        self.assertEqual(ia.match_model("Claude Opus 5.5 (High)", CAT), "claude-opus-5-5")
        self.assertEqual(ia.match_model("Claude Opus 5 (High)", CAT), "claude-opus-5")
        self.assertIsNone(ia.match_model("Modèle inconnu", CAT))

    def test_catalogue_coherent(self):
        ids = [m["id"] for m in CAT]
        self.assertEqual(len(ids), len(set(ids)))
        for m in CAT:
            for k in m["keys"]:
                self.assertEqual(k, ia.norm(k), k)
            if m["prev"]:  # une famille à un seul modèle (GPT Astra) n'a pas de version précédente
                self.assertIn(m["prev"], ids)
            for b in m["badges"]:
                self.assertIn(b, ("claude_code", "copilot"))


class ScaleTest(unittest.TestCase):
    def test_pourcentage(self):
        self.assertEqual(ia.scale("pct", {"a": 0.5}, [0.1, 0.5, 1.0]), {"a": 50.0})
        self.assertEqual(ia.scale("pct", {"a": 64.0}, [10, 64, 90]), {"a": 64.0})
        self.assertEqual(ia.scale("pct", {"a": 140.0}, [10, 140]), {"a": 100.0})

    def test_relatif_mediane_50_meilleur_100(self):
        out = ia.scale("rel", {"top": 1500, "med": 1400, "bas": 1000}, [1000, 1300, 1400, 1450, 1500])
        self.assertEqual(out, {"top": 100.0, "med": 50.0, "bas": 0.0})

    def test_population_plate_ou_vide(self):
        self.assertEqual(ia.scale("rel", {"a": 1}, [1, 1]), {})
        self.assertEqual(ia.scale("pct", {}, []), {})


class SourcesTest(unittest.TestCase):
    def test_epoch_meilleure_valeur_et_csv_imbrique(self):
        out = ia.parse_epoch(EPOCH, CAT)["tests"]
        self.assertEqual(out["swe_verified"], {"claude-opus-5-5": 81.0, "claude-opus-5": 74.0, "gpt-6-astra": 70.0})
        self.assertEqual(out["eci"]["claude-opus-5-5"], 100.0)  # nom de dossier ignoré, échelle libre ramenée sur 100
        self.assertNotIn("gpqa", out)  # valeur illisible : test absent, pas de zéro inventé

    def test_epoch_zip_invalide(self):
        with self.assertRaises(zipfile.BadZipFile):
            ia.parse_epoch(b"pas un zip", CAT)

    def test_epoch_membre_trop_gros_ignore(self):
        with mock.patch.object(ia, "MEMBER_MAX", 10):
            self.assertEqual(ia.parse_epoch(EPOCH, CAT)["tests"], {})

    def test_arena(self):
        out = ia.fetch_arena(CAT, arena_get(ARENA))
        self.assertEqual(out["tests"]["arena_coding"]["claude-opus-5-5"], 100.0)
        self.assertNotIn("arena_webdev", out["tests"])
        self.assertEqual(out["unmatched"], ["Nouveau Modèle X"])  # grand labo seulement

    def test_arena_pagination(self):
        rows = [arow(f"m{i}", 1000 + i, i) for i in range(250)] + [arow("Claude Opus 5.5", 2000, 0)]
        calls = []
        get = arena_get({("text", "coding"): rows})

        def counting(url, limit, headers=None, opener=None):
            calls.append(url)
            return get(url, limit)
        self.assertEqual(len(ia.arena_rows("text", "coding", counting)), 251)
        self.assertEqual(len(calls), 3)

    def test_aa_cle_en_entete_et_valeurs_bornees(self):
        seen = []

        def get(url, limit, headers=None, opener=None):
            seen.append((url, headers))
            page = int(parse_qs(urlsplit(url).query)["page"][0])
            data = [{"name": "Claude Opus 5.5", "slug": "claude-opus-5-5",
                     "evaluations": {"artificial_analysis_intelligence_index": 72.5},
                     "pricing": {"price_1m_input_tokens": 5, "price_1m_output_tokens": 25},
                     "median_output_tokens_per_second": 80.123, "median_time_to_first_token_seconds": "x"},
                    {"name": "Autre", "evaluations": {"artificial_analysis_intelligence_index": 500}}] if page == 1 else \
                   [{"name": "GPT-6 Astra", "evaluations": {"artificial_analysis_intelligence_index": 70}}]
            return json.dumps({"data": data, "pagination": {"has_more": page == 1}}).encode()
        out = ia.fetch_aa(CAT, "CLE", get)
        self.assertEqual(out["tests"]["aa_index"], {"claude-opus-5-5": 72.5, "gpt-6-astra": 70.0})
        self.assertEqual(out["extra"]["claude-opus-5-5"], {"price_in": 5.0, "price_out": 25.0, "tps": 80.12})
        self.assertEqual(out["unmatched"], [])  # « Autre » : note hors bornes
        self.assertEqual([h for _, h in seen], [{"x-api-key": "CLE"}] * 2)

    def test_aa_indices_code_et_maths_par_domaine(self):
        rows = [{"name": "Claude Opus 5.5", "evaluations": {"artificial_analysis_intelligence_index": 70,
                                                           "artificial_analysis_coding_index": 64, "artificial_analysis_math_index": 90}},
                {"name": "Autre", "evaluations": {"artificial_analysis_intelligence_index": 50, "artificial_analysis_coding_index": 30}}]
        out = ia.fetch_aa(CAT, "k", lambda *a, **k: json.dumps({"data": rows}).encode())
        self.assertEqual(out["tests"]["aa_coding"], {"claude-opus-5-5": 64.0})
        self.assertEqual(out["tests"]["aa_math"], {"claude-opus-5-5": 90.0})
        self.assertEqual({t["domain"] for t in ia.AA_TESTS} - {d["id"] for d in ia.DOMAINS}, set())

    def test_arena_categorie_en_echec_ne_bloque_pas_les_autres(self):
        def get(url, limit, headers=None, opener=None):
            if "creative_writing" in url:
                raise OSError("réseau")
            return json.dumps({"rows": [{"row": {"model_name": "claude-opus-5-5", "rating": 1500, "rank": 1}},
                                        {"row": {"model_name": "x", "rating": 1000, "rank": 2}}], "num_rows_total": 2}).encode()
        out = ia.fetch_arena(CAT, get)
        self.assertIn("arena_overall", out["tests"])
        self.assertNotIn("arena_creative", out["tests"])

    def test_tests_epoch_dans_des_domaines_connus(self):
        for t in ia.TESTS.values():
            self.assertIn(t["domain"], {d["id"] for d in ia.DOMAINS})

    def test_aa_nouveau_modele_proche_du_top5_signale(self):
        rows = [{"name": f"Fort {i}", "evaluations": {"artificial_analysis_intelligence_index": 70 + i}} for i in range(5)]
        rows += [{"name": "Proche", "evaluations": {"artificial_analysis_intelligence_index": 60}},
                 {"name": "Loin", "evaluations": {"artificial_analysis_intelligence_index": 40}},
                 {"name": "Claude Haiku 5.5", "evaluations": {"artificial_analysis_intelligence_index": 65},
                  "pricing": {"price_1m_input_tokens": 1, "price_1m_output_tokens": 5}}]
        out = ia.fetch_aa(CAT, "k", lambda *a, **k: json.dumps({"data": rows}).encode())
        self.assertEqual(out["unmatched"], [f"Fort {i}" for i in range(5)] + ["Proche"])
        self.assertEqual(out["tests"]["aa_index"], {"claude-haiku-5-5": 65.0})

    def test_cle_jamais_suivie_sur_redirection(self):
        self.assertIsNone(ia._NoRedirect().redirect_request(None, None, 302, "", {}, "https://ailleurs.example/"))
        self.assertIsNone(ia._HttpsOnly().redirect_request(None, None, 302, "", {}, "http://ailleurs.example/"))

    def test_reponse_trop_grosse(self):
        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        with self.assertRaises(ValueError):
            ia._get("https://x.example/", 3, opener=lambda req, timeout: R(b"12345"))


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "ia.db"
        self.calls = []
        arena = arena_get(ARENA)

        def get(url, limit, headers=None, opener=None):
            self.calls.append(url)
            if url == ia.EPOCH_URL:
                if self.epoch_down:
                    raise OSError("réseau")
                return EPOCH
            if url.startswith(ia.AA_URL):
                return json.dumps({"data": [{"name": "Claude Opus 5", "evaluations": {"artificial_analysis_intelligence_index": 60},
                                             "pricing": {"price_1m_input_tokens": 4, "price_1m_output_tokens": 20}}]}).encode()
            return arena(url, limit)
        self.get, self.epoch_down = get, False

    def run_at(self, hour, key=None, day=2, **kw):
        return ia.refresh(self.db, datetime(2026, 11, day, hour), self.get, lambda name: key, **kw)

    def test_une_fois_par_jour_a_partir_de_6h(self):
        self.assertEqual(self.run_at(5), {})
        self.assertEqual(self.run_at(6, key="k"), {"epoch": "ok", "arena": "ok", "aa": "ok"})
        self.assertEqual(self.run_at(9, key="k"), {})
        self.assertNotEqual(self.run_at(6, key="k", day=3), {})

    def test_sans_cle_aa_non_configure_sans_appel(self):
        self.assertEqual(self.run_at(7)["aa"], "non configuré")
        self.assertFalse(any(u.startswith(ia.AA_URL) for u in self.calls))

    def test_source_en_panne_garde_ses_valeurs_et_reessaie_3_fois(self):
        self.run_at(6)
        self.epoch_down = True
        snap_before = ia.snapshot(self.db)
        self.assertEqual(self.run_at(6, day=3)["epoch"], "indisponible")
        self.assertEqual(ia.snapshot(self.db)["models"], snap_before["models"])
        self.assertNotEqual(self.run_at(7, day=3), {})
        self.assertNotEqual(self.run_at(8, day=3), {})
        self.assertEqual(self.run_at(9, day=3), {})  # 3 essais par jour au plus (quota de la clé)

    def test_snapshot_assemble_notes_ecart_et_sources(self):
        self.run_at(6, key="k")
        s = ia.snapshot(self.db)
        m = {x["id"]: x for x in s["models"]}
        opus = m["claude-opus-5-5"]
        self.assertEqual(opus["gen"], "current")
        self.assertEqual(opus["prev"], "claude-opus-5")
        self.assertIn("claude_code", opus["badges"])
        code = opus["scores"]["code"]
        self.assertEqual(code["n"], 2)
        self.assertEqual(code["score"], round((81.0 + 100.0) / 2, 1))
        self.assertEqual({d["source"] for d in code["detail"]}, {"Epoch AI", "LMArena"})
        self.assertEqual(opus["delta"]["code"], round(code["score"] - m["claude-opus-5"]["scores"]["code"]["score"], 1))
        self.assertEqual(m["claude-opus-5"]["delta"], {})
        self.assertEqual(m["claude-opus-5"]["price_mix"], 8.0)
        self.assertEqual(m["kimi-k3"]["scores"], {})
        self.assertEqual([x["id"] for x in s["sources"]], ["epoch", "arena", "aa"])
        self.assertEqual(s["updated"], "2026-11-02T06:00")
        self.assertEqual(s["unmatched"], ["Nouveau Modèle X"])

    def test_snapshot_sans_base(self):
        s = ia.snapshot(Path(tempfile.mkdtemp()) / "absent.db")
        self.assertIsNone(s["updated"])
        self.assertTrue(all(not m["scores"] for m in s["models"]))

    def test_donnees_stockees_hostiles_ignorees(self):
        with closing(ia._db(self.db)) as cx, cx:
            cx.execute("INSERT INTO source VALUES ('epoch','2026-11-02T06:00',?)",
                       (json.dumps({"tests": {"swe_verified": {"claude-opus-5-5": 1e9, "inconnu": 50},
                                              "aa_index": {"claude-opus-5-5": 99}}}),))
            cx.execute("INSERT INTO source VALUES ('pirate','x','{}')")
        s = ia.snapshot(self.db)
        self.assertTrue(all(not m["scores"] for m in s["models"]))  # hors bornes, test d'une autre source, source inconnue

    def test_purge_instantanes(self):
        self.run_at(6)
        self.assertEqual(ia.purge(self.db, 365, date(2027, 12, 1), dry=True), 1)
        self.assertEqual(ia.purge(self.db, 365, date(2027, 12, 1)), 1)
        self.assertEqual(ia.purge(self.db, 365, date(2027, 12, 1)), 0)


@unittest.skipUnless(shutil.which("node"), "node absent")
class PwaLogicTest(unittest.TestCase):
    def test_logique_de_l_ecran(self):
        r = subprocess.run(["node", "--test", str(Path(__file__).with_name("comparatif.test.js"))], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class SecretTest(unittest.TestCase):
    def test_nom_de_cle_accepte(self):
        self.assertIn("aa_api_key", secrets.NAMES)


class RouteTest(ServerBase):
    def test_authentifiee_et_journalisee(self):
        self.assertEqual(self.call("GET", "/api/ia-compare")[0], 401)
        _, token = self.enroll()
        with mock.patch("jarvis.server.iacompare_snapshot", return_value={"models": []}):
            status, body, _ = self.call("GET", "/api/ia-compare", token=token)
        self.assertEqual((status, body), (200, {"models": []}))
        self.assertIn("iacompare_read", str(self.call("GET", "/api/audit?limit=20", token=token)[1]))

    def test_base_illisible(self):
        _, token = self.enroll()
        with mock.patch("jarvis.server.iacompare_snapshot", side_effect=OSError("disque")):
            self.assertEqual(self.call("GET", "/api/ia-compare", token=token)[0], 503)

    def test_cle_de_portee_limitee_refusee(self):
        token = self.devices.add_scoped("tv-salon", "tv")[1]
        self.assertEqual(self.call("GET", "/api/ia-compare", token=token)[0], 403)


if __name__ == "__main__":
    unittest.main()
