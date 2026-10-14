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
REFRESH_S = 24 * 3600
PDL = re.compile(r"\d{14}")


class Unavailable(Exception):
    """Source absente ou en panne. Le message ne contient jamais le jeton ni le PDL."""


def fetch(token: str, pdl: str, first: date, end: date, urlopen=urllib.request.urlopen) -> dict[str, float]:
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
    if prev and 0 <= (now - prev).total_seconds() < REFRESH_S:
        return "à jour"
    try:
        token, pdl = secret("med_token"), secret("med_pdl")
    except Exception:  # noqa: BLE001 (coffre absent)
        token = pdl = None
    if not token or not pdl:
        return "non configuré"
    try:
        days = fetch_fn(token, pdl, now.date() - timedelta(days=DAYS), now.date())
    except Unavailable:
        return "indisponible"
    if not days:
        return "indisponible"  # réponse vide : rien n'est écrit, pas de zéro inventé
    conso.store_home(days, now, db)
    return "ok"
