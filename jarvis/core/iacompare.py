"""Comparatif des IA (section de l'onglet Veille IA) : notes sur 100 par domaine des modèles cloud suivis, N0, lecture seule.

Sources publiques relues une fois par jour par le Core, chacune citée dans l'onglet :
- Epoch AI : ZIP de CSV (CC BY 4.0), tests détaillés (SWE-bench Verified, Terminal-Bench, GPQA Diamond, ECI…).
- LMArena : classements par votes humains (CC BY 4.0), lus en JSON par l'API publique de Hugging Face.
- Artificial Analysis : note globale, prix et vitesse, avec la clé gratuite du propriétaire (`aa_api_key`, en-tête
  `x-api-key`, jamais suivie sur une redirection). Sans clé, le comparatif marche avec les deux autres sources.

Tout ce qui vient de ces sources est une DONNÉE : seuls des nombres bornés et des noms de modèles reconnus par
`jarvis/ia_models.json` en sortent ; rien n'est montré au LLM, rien ne déclenche d'action. Une source en panne
garde ses dernières valeurs. Un instantané des notes par jour (`~/.jarvis/iacompare.db`) prépare la courbe (v2).
"""
import csv
import io
import json
import math
import re
import sqlite3
import statistics
import urllib.parse
import urllib.request
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from jarvis.core import secrets

DB = Path.home() / ".jarvis" / "iacompare.db"
CATALOG = Path(__file__).resolve().parents[1] / "ia_models.json"
TIMEOUT_S = 30
ZIP_MAX, MEMBER_MAX, JSON_MAX = 60_000_000, 8_000_000, 4_000_000
REFRESH_HOUR, MAX_TRIES_PER_DAY = 6, 3  # Artificial Analysis gratuit : 100 requêtes par jour, on en fait au plus ~30

EPOCH_URL = "https://epoch.ai/data/benchmark_data.zip"
ARENA_URL = "https://datasets-server.huggingface.co/filter"
ARENA_DATASET = "lmarena-ai/leaderboard-dataset"
AA_URL = "https://artificialanalysis.ai/api/v2/language/models/free"

SOURCES = {
    "epoch": {"name": "Epoch AI", "url": "https://epoch.ai/benchmarks", "licence": "CC BY 4.0"},
    "arena": {"name": "LMArena", "url": "https://lmarena.ai/leaderboard", "licence": "CC BY 4.0"},
    "aa": {"name": "Artificial Analysis", "url": "https://artificialanalysis.ai", "licence": "usage personnel, source citée"},
}
DOMAINS = [{"id": "code", "label": "Code"}, {"id": "general", "label": "Général"}]

# Tests retenus. kind « pct » = pourcentage (0–1 multiplié par 100) ; « rel » = échelle libre (Elo, ECI) ramenée sur 100 :
# médiane de toute la population de la source = 50, meilleur = 100.
EPOCH_TESTS = [
    {"id": "swe_verified", "label": "SWE-bench Verified", "domain": "code", "kind": "pct",
     "file": re.compile(r"^swe[_-]?bench[_-]?verified(_external)?\.csv$", re.I),
     "cols": ("mean_score", "Best score (across scorers)", "Score")},
    {"id": "terminal_bench", "label": "Terminal-Bench", "domain": "code", "kind": "pct",
     "file": re.compile(r"^terminal[_-]?bench.*\.csv$", re.I), "cols": ("Accuracy mean", "mean_score", "Score")},
    {"id": "gpqa", "label": "GPQA Diamond", "domain": "general", "kind": "pct",
     "file": re.compile(r"^gpqa[_-]?diamond.*\.csv$", re.I), "cols": ("mean_score", "Best score (across scorers)", "Score")},
    {"id": "eci", "label": "Epoch Capabilities Index", "domain": "general", "kind": "rel",
     "file": re.compile(r"^(epoch_capabilities_index|eci_scores)\.csv$", re.I), "cols": ("eci", "ECI Score", "ECI")},
]
MODEL_COLS = ("Model version", "model_version", "Model", "model", "Model name", "Name", "id")
ARENA_TESTS = [  # (config, catégorie)
    {"id": "arena_coding", "label": "LMArena, code", "domain": "code", "config": "text", "category": "coding"},
    {"id": "arena_webdev", "label": "LMArena, WebDev", "domain": "code", "config": "webdev", "category": "overall"},
    {"id": "arena_overall", "label": "LMArena, général", "domain": "general", "config": "text", "category": "overall"},
]
ARENA_PAGES = 6  # 100 lignes par page ; ~420 modèles par catégorie
AA_PAGES = 10
NEAR_TOP5 = 15  # points de note globale sous la moyenne du top 5 : au-delà, un modèle inconnu n'est pas signalé
LABS = {"anthropic", "openai", "google", "xai", "meta", "deepseek", "alibaba", "mistral", "moonshot", "zai"}

EXCLUDE = {"mini", "nano", "lite", "small", "air", "flash", "turbo", "multi", "vision", "vl", "audio", "realtime", "image"}
_SEP = re.compile(r"[^a-z0-9]+")


def norm(name: str) -> str:
    return _SEP.sub("-", str(name).lower()).strip("-")


def matches(name: str, key: str) -> bool:
    """`claude-opus-5` reconnaît « Claude Opus 5 (Max) » et « claude-opus-5-20260101 », pas « Claude Opus 5.5 » ni « … mini »."""
    n = norm(name)
    if n == key:
        return True
    if not n.startswith(key + "-"):
        return False
    nxt = n[len(key) + 1:].split("-")[0]
    return nxt not in EXCLUDE and not (nxt.isdigit() and len(nxt) <= 2)


def load_catalog(path: Path = CATALOG) -> list[dict]:
    """Modèles suivis, à plat : id, nom, famille, labo, badges, génération (current/previous), précédent."""
    out = []
    for fam in json.loads(Path(path).read_text(encoding="utf-8"))["families"]:
        for i, m in enumerate(fam["models"][:2]):
            out.append({"id": m["id"], "name": m["name"], "family": fam["family"], "lab": fam["lab"],
                        "badges": list(fam.get("badges", [])), "keys": list(m["keys"]),
                        "gen": "current" if i == 0 else "previous",
                        "prev": fam["models"][1]["id"] if i == 0 and len(fam["models"]) > 1 else None})
    return out


def match_model(name: str, catalog: list[dict]) -> str | None:
    """Clé la plus longue d'abord : « claude-opus-5-5 » avant « claude-opus-5 »."""
    best = None
    for m in catalog:
        for k in m["keys"]:
            if matches(name, k) and (best is None or len(k) > best[0]):
                best = (len(k), m["id"])
    return best[1] if best else None


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(str(v).strip().rstrip("%")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def scale(kind: str, values: dict[str, float], population: list[float]) -> dict[str, float]:
    """Ramène sur 100. pct : 0–1 ×100 si toute la population est ≤ 1. rel : médiane = 50, meilleur = 100, borné 0–100."""
    if not values or not population:
        return {}
    if kind == "pct":
        k = 100.0 if max(population) <= 1.0 else 1.0
        return {m: round(min(100.0, max(0.0, v * k)), 1) for m, v in values.items()}
    med, top = statistics.median(population), max(population)
    if top <= med:
        return {}
    return {m: round(min(100.0, max(0.0, 50 + 50 * (v - med) / (top - med))), 1) for m, v in values.items()}


def best_per_model(rows, catalog) -> tuple[dict[str, float], list[float]]:
    """rows : (nom, valeur). Meilleure valeur par modèle suivi (variantes high/max confondues) + toute la population."""
    vals, pop = {}, []
    for name, v in rows:
        if v is None:
            continue
        pop.append(v)
        if (mid := match_model(name, catalog)) is not None:
            vals[mid] = max(v, vals.get(mid, v))
    return vals, pop


# ---- Récupération ------------------------------------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Une 3xx devient une erreur : urllib recopierait `x-api-key` vers l'hôte cible."""

    def redirect_request(self, *args, **kwargs):
        return None


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """Requêtes sans secret : redirection suivie seulement vers https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_open_public = urllib.request.build_opener(_HttpsOnly).open
_open_keyed = urllib.request.build_opener(_NoRedirect).open
UA = {"User-Agent": "jarvis-iacompare/1 (usage personnel)", "Accept": "*/*"}


def _get(url: str, limit: int, headers=None, opener=None) -> bytes:
    opener = opener or (_open_keyed if headers else _open_public)
    with opener(urllib.request.Request(url, headers={**UA, **(headers or {})}), timeout=TIMEOUT_S) as r:
        body = r.read(limit + 1)
    if len(body) > limit:
        raise ValueError("réponse trop grosse")
    return body


def parse_epoch(blob: bytes, catalog) -> dict:
    """{"tests": {id: {modèle: note}}}. Lit seulement les CSV attendus, chacun borné en taille (pas de bombe ZIP)."""
    tests = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        infos = [i for i in z.infolist() if not i.is_dir()][:500]
        for t in EPOCH_TESTS:
            info = next((i for i in infos if t["file"].match(i.filename.rsplit("/", 1)[-1])), None)
            if info is None or info.file_size > MEMBER_MAX:
                continue
            with z.open(info) as f:
                text = f.read(MEMBER_MAX + 1)[:MEMBER_MAX].decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text, newline=""))
            heads = reader.fieldnames or []
            mcol = next((c for c in MODEL_COLS if c in heads), None)
            scol = next((c for c in t["cols"] if c in heads), None)
            if not mcol or not scol:
                continue
            vals, pop = best_per_model(((r.get(mcol) or "", _num(r.get(scol))) for r in reader), catalog)
            if scaled := scale(t["kind"], vals, pop):
                tests[t["id"]] = scaled
    return {"tests": tests}


def fetch_epoch(catalog, get=_get) -> dict:
    return parse_epoch(get(EPOCH_URL, ZIP_MAX), catalog)


def arena_rows(config: str, category: str, get=_get) -> list[dict]:
    rows = []
    for page in range(ARENA_PAGES):
        q = urllib.parse.urlencode({"dataset": ARENA_DATASET, "config": config, "split": "latest",
                                    "where": f"\"category\"='{category}'", "offset": page * 100, "length": 100})
        data = json.loads(get(f"{ARENA_URL}?{q}", JSON_MAX))
        got = [r.get("row") or {} for r in data.get("rows") or [] if isinstance(r, dict)]
        rows += got
        if len(got) < 100 or len(rows) >= int(data.get("num_rows_total") or 0):
            break
    return rows


def fetch_arena(catalog, get=_get) -> dict:
    tests, unmatched = {}, []
    for t in ARENA_TESTS:
        rows = arena_rows(t["config"], t["category"], get)
        vals, pop = best_per_model(((str(r.get("model_name") or ""), _num(r.get("rating"))) for r in rows), catalog)
        if scaled := scale("rel", vals, pop):
            tests[t["id"]] = scaled
        if t["id"] == "arena_overall":  # modèles des grands labos bien classés, absents du catalogue : « à associer »
            top = sorted((r for r in rows if _num(r.get("rank")) is not None), key=lambda r: _num(r["rank"]))[:25]
            for r in top:
                name = str(r.get("model_name") or "")[:60]
                if str(r.get("organization") or "").lower() in LABS and match_model(name, catalog) is None:
                    unmatched.append(name)
    return {"tests": tests, "unmatched": unmatched[:8]}


def _pick(row: dict, *path):
    for p in path:
        row = row.get(p) if isinstance(row, dict) else None
    return row


def fetch_aa(catalog, key: str, get=_get) -> dict:
    """Clé gratuite : note globale (0–100), prix (USD par million de tokens) et vitesse ; `x-api-key`, sans redirection."""
    rows = []
    for page in range(1, AA_PAGES + 1):
        data = json.loads(get(f"{AA_URL}?page={page}", JSON_MAX, headers={"x-api-key": key}))
        rows += [r for r in data.get("data") or [] if isinstance(r, dict)]
        if not (_pick(data, "pagination", "has_more") is True):
            break
    pop, vals, extra = [], {}, {}
    for r in rows:
        name = str(r.get("name") or r.get("slug") or "")
        mid = match_model(name, catalog) or match_model(str(r.get("slug") or ""), catalog)
        idx = _num(_pick(r, "evaluations", "artificial_analysis_intelligence_index"))
        if idx is not None and 0 <= idx <= 100:
            pop.append(idx)
            if mid:
                vals[mid] = max(idx, vals.get(mid, idx))
        if mid:
            perf = r.get("performance") if isinstance(r.get("performance"), dict) else r
            info = {"price_in": _num(_pick(r, "pricing", "price_1m_input_tokens")),
                    "price_out": _num(_pick(r, "pricing", "price_1m_output_tokens")),
                    "tps": _num(perf.get("median_output_tokens_per_second")),
                    "ttft": _num(perf.get("median_time_to_first_token_seconds"))}
            info = {k: round(v, 2) for k, v in info.items() if v is not None and 0 <= v < 1e5}
            if info and (mid not in extra or len(info) > len(extra[mid])):
                extra[mid] = info
    # Modèles proches du top 5 (note globale) absents du catalogue : signalés « à associer », jamais ajoutés seuls.
    top5 = sorted(pop, reverse=True)[:5]
    floor = sum(top5) / len(top5) - NEAR_TOP5 if top5 else math.inf
    unmatched = []
    for r in rows:
        name = str(r.get("name") or "")[:60]
        idx = _num(_pick(r, "evaluations", "artificial_analysis_intelligence_index"))
        if (name and idx is not None and floor <= idx <= 100 and match_model(name, catalog) is None
                and match_model(str(r.get("slug") or ""), catalog) is None):
            unmatched.append(name)
    tests = {"aa_index": scale("pct", vals, pop)} if vals else {}
    return {"tests": tests, "extra": extra, "unmatched": unmatched[:8]}


AA_TEST = {"id": "aa_index", "label": "Artificial Analysis, note globale", "domain": "general"}
TESTS = {t["id"]: {**t, "source": s} for s, ts in (("epoch", EPOCH_TESTS), ("arena", ARENA_TESTS), ("aa", [AA_TEST])) for t in ts}


# ---- Stockage et assemblage ---------------------------------------------------------------------------------------------
def _db(db: Path) -> sqlite3.Connection:
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(db)
    cx.execute("CREATE TABLE IF NOT EXISTS source (name TEXT PRIMARY KEY, fetched TEXT, data TEXT)")
    cx.execute("CREATE TABLE IF NOT EXISTS snap (day TEXT PRIMARY KEY, data TEXT)")
    cx.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    return cx


def _meta(cx, k, v=None):
    if v is None:
        row = cx.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return row[0] if row else None
    cx.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, v))


def assemble(stored: dict[str, tuple[str, dict]], catalog) -> dict:
    """Notes par domaine = moyenne des tests disponibles ; écart avec la version précédente de la même famille."""
    per = {m["id"]: {} for m in catalog}
    extra, unmatched = {}, []
    for src, (_, data) in stored.items():
        for tid, scores in (data.get("tests") or {}).items():
            if tid not in TESTS or TESTS[tid]["source"] != src:
                continue
            for mid, v in scores.items():
                if mid in per and isinstance(v, (int, float)) and 0 <= v <= 100:
                    per[mid][tid] = float(v)
        extra.update({k: v for k, v in (data.get("extra") or {}).items() if k in per})
        unmatched += [str(n)[:60] for n in data.get("unmatched") or []][:8]
    models = []
    for m in catalog:
        scores = {}
        for d in DOMAINS:
            detail = [{"test": TESTS[t]["label"], "source": SOURCES[TESTS[t]["source"]]["name"], "score": v}
                      for t, v in per[m["id"]].items() if TESTS[t]["domain"] == d["id"]]
            if detail:
                scores[d["id"]] = {"score": round(sum(x["score"] for x in detail) / len(detail), 1), "n": len(detail),
                                   "detail": sorted(detail, key=lambda x: x["test"])}
        info = dict(extra.get(m["id"], {}))
        if "price_in" in info and "price_out" in info:  # prix mixte d'usage courant : 3 tokens lus pour 1 écrit
            info["price_mix"] = round((3 * info["price_in"] + info["price_out"]) / 4, 2)
        models.append({k: m[k] for k in ("id", "name", "family", "lab", "badges", "gen", "prev")}
                      | {"scores": scores, **info})
    by_id = {m["id"]: m for m in models}
    for m in models:
        p = by_id.get(m["prev"]) if m["prev"] else None
        m["delta"] = {d: round(s["score"] - p["scores"][d]["score"], 1)
                      for d, s in m["scores"].items() if p and d in p["scores"]}
    return {"domains": DOMAINS, "models": models, "unmatched": sorted(set(unmatched))}


def snapshot(db: Path = DB, catalog_path: Path = CATALOG) -> dict:
    """Ce que lit la PWA : rien n'est récupéré ici (lecture de la base locale seulement)."""
    catalog = load_catalog(catalog_path)
    stored = {}
    if Path(db).is_file():
        with closing(_db(db)) as cx:
            for name, fetched, data in cx.execute("SELECT name, fetched, data FROM source"):
                if name in SOURCES:
                    try:
                        stored[name] = (fetched, json.loads(data))
                    except ValueError:
                        pass
    out = assemble(stored, catalog)
    out["sources"] = [{"id": s, **SOURCES[s], "fetched": stored[s][0] if s in stored else None} for s in SOURCES]
    out["updated"] = max((f for f, _ in stored.values()), default=None)
    return out


FETCHERS = {"epoch": lambda cat, key, get: fetch_epoch(cat, get), "arena": lambda cat, key, get: fetch_arena(cat, get),
            "aa": lambda cat, key, get: fetch_aa(cat, key, get)}


def refresh(db: Path = DB, now: datetime | None = None, get=_get, secret=secrets.get_secret, catalog_path: Path = CATALOG,
            force: bool = False) -> dict:
    """Relève les sources une fois par jour (à partir de REFRESH_HOUR, au plus MAX_TRIES_PER_DAY essais).
    Renvoie {source: "ok" | "indisponible" | "non configuré"} ou {} si rien n'était dû. Une source en échec garde ses valeurs."""
    now = now or datetime.now()
    today = now.date().isoformat()
    with closing(_db(db)) as cx, cx:
        done = _meta(cx, "done") == today
        tries = int(_meta(cx, f"tries:{today}") or 0)
        if not force and (done or now.hour < REFRESH_HOUR or tries >= MAX_TRIES_PER_DAY):
            return {}
        _meta(cx, f"tries:{today}", str(tries + 1))
        cx.execute("DELETE FROM meta WHERE k LIKE 'tries:%' AND k != ?", (f"tries:{today}",))
    catalog = load_catalog(catalog_path)
    try:
        key = secret("aa_api_key")
    except Exception:  # noqa: BLE001 (coffre absent : comparatif sans Artificial Analysis)
        key = None
    status = {}
    for name, fetch in FETCHERS.items():
        if name == "aa" and not key:
            status[name] = "non configuré"
            continue
        try:
            data = fetch(catalog, key, get)
            if not data.get("tests"):
                raise ValueError("aucun modèle suivi reconnu")
        except Exception:  # noqa: BLE001 (réseau, format, quota : aucun détail relayé, anciennes valeurs gardées)
            status[name] = "indisponible"
            continue
        with closing(_db(db)) as cx, cx:
            cx.execute("INSERT OR REPLACE INTO source VALUES (?,?,?)", (name, now.isoformat(timespec="minutes"), json.dumps(data)))
        status[name] = "ok"
    with closing(_db(db)) as cx, cx:
        if all(s != "indisponible" for s in status.values()):
            _meta(cx, "done", today)
    snap = snapshot(db, catalog_path)
    with closing(_db(db)) as cx, cx:
        cx.execute("INSERT OR REPLACE INTO snap VALUES (?,?)", (today, json.dumps(
            {m["id"]: {d: s["score"] for d, s in m["scores"].items()} for m in snap["models"]})))
    return status


def purge(db: Path, days: int, today=None, dry: bool = False) -> int:
    """Instantanés quotidiens plus vieux que `days` jours."""
    from datetime import timedelta
    if not Path(db).is_file():
        return 0
    cutoff = ((today or datetime.now().date()) - timedelta(days=days)).isoformat()
    with closing(_db(db)) as cx, cx:
        sql = "FROM snap WHERE day < ?"
        if dry:
            return cx.execute("SELECT COUNT(*) " + sql, (cutoff,)).fetchone()[0]
        return cx.execute("DELETE " + sql, (cutoff,)).rowcount
