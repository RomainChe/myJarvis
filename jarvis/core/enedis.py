"""Total du logement : conso quotidienne du compteur Linky via la passerelle hébergée MyElectricalData (N0, lecture).

Enedis n'ouvre pas Data Connect aux particuliers ; le propriétaire a consenti une fois sur myelectricaldata.fr. Le jeton
(`med_token`) et le PDL (`med_pdl`) sont dans le coffre, jamais dans un fichier du dépôt. Un seul appel par jour, 30 jours
de totaux quotidiens (aucune courbe 30 min). La réponse est une DONNÉE : bornée, validée, jamais montrée au LLM.
"""
import json
import math
import re
import urllib.request
from datetime import date, datetime, timedelta

from jarvis.core import conso, secrets

URL = "https://myelectricaldata.fr"  # ponytail: passerelle tierce hébergée ; auto-hébergée = changer cette constante
TIMEOUT_S, MAX_BYTES, MAX_KWH_DAY, DAYS = 10, 1_000_000, 500.0, 30
REFRESH_S, RETRY_S = 24 * 3600, 6 * 3600  # après un échec : pas de nouvel appel (jeton) avant 6 h
_failed_at: datetime | None = None
PDL = re.compile(r"\d{14}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Une 3xx devient une erreur : urllib recopierait `Authorization` vers l'hôte cible (fuite du jeton)."""

    def redirect_request(self, *args, **kwargs):
        return None


_open = urllib.request.build_opener(_NoRedirect).open


class Unavailable(Exception):
    """Source absente ou en panne. Le message ne contient jamais le jeton ni le PDL."""


def fetch(token: str, pdl: str, first: date, end: date, urlopen=_open) -> dict[str, float]:
    """{jour ISO: kWh} pour first <= jour < end. Valeurs absurdes ou jours hors fenêtre ignorés."""
    if not PDL.fullmatch(pdl or ""):
        raise Unavailable("PDL invalide")
    req = urllib.request.Request(f"{URL}/daily_consumption/{pdl}/start/{first.isoformat()}/end/{end.isoformat()}/",
                                 headers={"Authorization": token, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=TIMEOUT_S) as resp:
            readings = json.loads(resp.read(MAX_BYTES))["meter_reading"]["interval_reading"]
    except Exception as e:  # noqa: BLE001 (réseau, HTTP 4xx/5xx, JSON : une seule issue, sans détail)
        raise Unavailable(f"relevé indisponible ({type(e).__name__})") from None
    out: dict[str, float] = {}
    for r in readings if isinstance(readings, list) else []:
        try:
            if isinstance(r["date"], bool) or isinstance(r["value"], bool):
                continue  # float(True) = 1 Wh : un booléen n'est pas un relevé
            day, kwh = date.fromisoformat(str(r["date"])[:10]), float(r["value"]) / 1000  # l'API donne des Wh
        except (KeyError, TypeError, ValueError):
            continue
        if first <= day < end and math.isfinite(kwh) and 0 <= kwh <= MAX_KWH_DAY:
            out[day.isoformat()] = kwh
    return out


def refresh(db=None, now: datetime | None = None, fetch_fn=fetch, secret=secrets.get_secret) -> str:
    """« à jour » | « ok » | « non configuré » | « indisponible ». Au plus un appel par REFRESH_S."""
    now = now or datetime.now()
    prev = conso.last_fetch(db)
    if prev:
        age = (now - prev).total_seconds()
        complete = (conso.last_home_day(db) or "") >= (now.date() - timedelta(days=1)).isoformat()
        # J-1 pas encore publié au dernier appel : on réessaie après RETRY_S, sinon une fois par jour
        if 0 <= age < (REFRESH_S if complete else RETRY_S):
            return "à jour"
    global _failed_at
    if _failed_at and 0 <= (now - _failed_at).total_seconds() < RETRY_S:
        return "indisponible"
    try:
        token, pdl = secret("med_token"), secret("med_pdl")
    except Exception:  # noqa: BLE001 (coffre absent)
        token = pdl = None
    if not token or not pdl:
        return "non configuré"
    try:
        days = fetch_fn(token, pdl, now.date() - timedelta(days=DAYS), now.date())
    except Unavailable:
        _failed_at = now
        return "indisponible"
    if not days:
        _failed_at = now
        return "indisponible"  # réponse vide : rien n'est écrit, pas de zéro inventé
    _failed_at = None
    conso.store_home(days, now, db)
    return "ok"
