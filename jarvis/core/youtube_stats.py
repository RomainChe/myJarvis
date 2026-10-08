"""Abonnés et vues YouTube de l'onglet Réseaux (Phase 6 point 3 étape 2, N0, lecture seule).

Jeton : celui de lol-clipper, lu en lecture seule (`~/.jarvis/social.json` : `{"youtube_token": "chemin"}`), jamais copié, loggué
ni montré au LLM. Il sert à obtenir un jeton d'accès, gardé en mémoire seulement (lol-clipper renouvelle son fichier lui-même).
Seuls des entiers en sortent. Droit requis : `youtube.readonly` (relancer `stats.bat` après avoir supprimé le jeton).
Historique : un relevé par jour dans `~/.jarvis/social.db` (SQLite), d'où l'évolution sur 7 et 30 jours.
"""
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

CONFIG = Path.home() / ".jarvis" / "social.json"
DB = Path.home() / ".jarvis" / "social.db"
TOKEN_URI = "https://oauth2.googleapis.com/token"  # fixe : le jeton ne peut pas rediriger nos identifiants ailleurs
API = "https://www.googleapis.com/youtube/v3/"
SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
TTL_S, FAIL_TTL_S = 900, 60
ID = re.compile(r"[A-Za-z0-9_-]{11}")
Counts = dict[str, int]


class Reconnect(Exception):
    """Droit absent ou jeton refusé : le propriétaire doit reconnecter lol-clipper (pas une simple panne)."""


def token_path(path: Path = CONFIG) -> Path | None:
    try:
        return Path(json.loads(Path(path).read_text(encoding="utf-8"))["youtube_token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _post(url: str, form: dict) -> dict:
    req = urllib.request.Request(url, urllib.parse.urlencode(form).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read(8192))


def _get(url: str, access: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {access}"}), timeout=5) as r:
        return json.loads(r.read(65536))


def _count(v) -> int:
    n = int(v)
    if not 0 <= n < 10**12:
        raise ValueError("compteur hors bornes")
    return n


def fetch(token_file: Path, video_ids=(), post=_post, get=_get) -> tuple[Counts, dict[str, int]]:
    tok = json.loads(Path(token_file).read_text(encoding="utf-8"))
    if SCOPE not in (tok.get("scopes") or []):
        raise Reconnect("droit youtube.readonly absent : reconnexion de lol-clipper à faire")
    try:
        access = post(TOKEN_URI, {"client_id": tok["client_id"], "client_secret": tok["client_secret"],
                                  "refresh_token": tok["refresh_token"], "grant_type": "refresh_token",
                                  "scope": SCOPE})["access_token"]  # jeton d'accès limité à la lecture
    except urllib.error.HTTPError as e:  # jeton révoqué (invalid_grant) : action du propriétaire
        if e.code in (400, 401):
            raise Reconnect("jeton refusé") from None
        raise
    st = get(API + "channels?part=statistics&mine=true", access)["items"][0]["statistics"]
    channel = {"subs": _count(st["subscriberCount"]), "views": _count(st["viewCount"]), "videos": _count(st["videoCount"])}
    ids = [i for i in video_ids if isinstance(i, str) and ID.fullmatch(i)][:20]
    per_video = {}
    if ids:
        for it in get(API + "videos?part=statistics&id=" + ",".join(ids), access)["items"]:
            per_video[str(it["id"])] = _count(it["statistics"]["viewCount"])
    return channel, per_video


def record(db: Path, today: date, c: Counts) -> dict:
    """Un relevé par jour (le dernier du jour gagne) ; renvoie l'évolution sur 7 et 30 jours (None sans relevé assez ancien)."""
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as cx, cx:
        cx.execute("CREATE TABLE IF NOT EXISTS yt (day TEXT PRIMARY KEY, subs INT, views INT, videos INT)")
        cx.execute("INSERT OR REPLACE INTO yt VALUES (?,?,?,?)", (today.isoformat(), c["subs"], c["views"], c["videos"]))
        out = {}
        for n in (7, 30):
            row = cx.execute("SELECT subs, views FROM yt WHERE day <= ? AND day >= ? ORDER BY day DESC LIMIT 1",
                             ((today - timedelta(days=n)).isoformat(), (today - timedelta(days=n + 2)).isoformat())).fetchone()
            out[f"d{n}"] = {"subs": c["subs"] - row[0], "views": c["views"] - row[1]} if row else None
    return out


class YouTubeStats:
    def __init__(self, *, token=token_path, fetch_fn=fetch, db=DB, clock=time.monotonic, today=date.today):
        self._token, self._fetch, self._db, self._clock, self._today = token, fetch_fn, db, clock, today
        self._hit: tuple[float, dict | None, int] | None = None

    def snapshot(self, video_ids=()) -> dict | None:
        """None si non configuré ; {"error": ...} si injoignable ; sinon compteurs, évolution et vues par vidéo."""
        path = self._token()
        if not path:
            return None
        if self._hit and self._clock() - self._hit[0] < self._hit[2]:
            return self._hit[1]
        try:
            channel, per_video = self._fetch(path, video_ids)
            value = {**channel, "delta": record(self._db, self._today(), channel), "video_views": per_video}
            keep = TTL_S
        except Reconnect:
            value, keep = {"error": "reconnexion"}, FAIL_TTL_S
        except Exception:  # réseau, JSON, jeton illisible : un message générique, aucun détail relayé
            value, keep = {"error": "indisponible"}, FAIL_TTL_S
        self._hit = (self._clock(), value, keep)
        return value
