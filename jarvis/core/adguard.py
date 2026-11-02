"""Client REST d'AdGuard Home (stdlib), sur le mini-PC par Tailscale. Identifiants `utilisateur:mot_de_passe` du coffre, jamais d'un fichier.

Les noms de domaine renvoyés sont des DONNÉES (contenu externe) : les montrer au LLM via `as_data`.
"""
import base64
import http.client
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import keyring.errors

from jarvis.core.secrets import get_secret

URL = os.environ.get("JARVIS_ADGUARD_URL") or ""
TIMEOUT = 5  # s
MAX_BYTES = 1_000_000  # /control/stats : quelques Ko
MAX_PAUSE_MIN = 15
DOMAIN_BAD = re.compile(r"[^A-Za-z0-9.-]")


class AdGuardError(Exception):
    """Message sans identifiants ni corps de réponse."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # urllib rejouerait l'en-tête Authorization vers la cible
        return None


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)  # ni proxy ni redirection : les identifiants ne partent que vers JARVIS_ADGUARD_URL


def _request(method: str, path: str, body: dict | None = None) -> dict:
    if not URL:
        raise AdGuardError("JARVIS_ADGUARD_URL absente")
    try:
        parts = urllib.parse.urlsplit(URL)
    except ValueError:
        raise AdGuardError("JARVIS_ADGUARD_URL mal formée") from None
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        raise AdGuardError("JARVIS_ADGUARD_URL doit être http(s)://hôte, sans identifiants")
    try:
        auth = get_secret("adguard_auth")
    except keyring.errors.KeyringError:
        raise AdGuardError("coffre indisponible") from None
    if not auth or ":" not in auth:
        raise AdGuardError("identifiants absents : python -m jarvis secret set adguard_auth (utilisateur:mot_de_passe)")
    try:
        req = urllib.request.Request(
            URL.rstrip("/") + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": "Basic " + base64.b64encode(auth.encode()).decode(), "Content-Type": "application/json"})
        with _opener.open(req, timeout=TIMEOUT) as r:
            raw = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise AdGuardError({401: "identifiants refusés", 403: "action refusée"}.get(e.code, f"AdGuard a répondu {e.code}")) from None
    except ValueError:  # en-tête ou URL refusés par http.client : son message contiendrait les identifiants
        raise AdGuardError("requête invalide (identifiants ou URL mal formés)") from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise AdGuardError("AdGuard Home injoignable (mini-PC éteint ou JARVIS_ADGUARD_URL incorrecte)") from None
    if len(raw) > MAX_BYTES:
        raise AdGuardError("réponse trop volumineuse")
    if not raw.strip():  # POST /control/protection répond 200 sans corps
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise AdGuardError("réponse illisible") from None
    if not isinstance(data, dict):
        raise AdGuardError("réponse inattendue")
    return data


def stats() -> dict:
    """Requêtes DNS, requêtes bloquées et les 3 domaines les plus bloqués (24 h glissantes, intervalle réglé dans AdGuard)."""
    d = _request("GET", "/control/stats")
    try:
        total, blocked = int(d["num_dns_queries"]), int(d["num_blocked_filtering"])
        top = [(DOMAIN_BAD.sub("?", k)[:80], int(v)) for item in d.get("top_blocked_domains", [])[:3] for k, v in item.items()]  # nom choisi par un tiers
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AdGuardError("réponse inattendue") from None
    return {"total": total, "blocked": blocked, "top": top}


def pause(minutes: int) -> None:
    """Coupe le blocage ; AdGuard le réactive seul à la fin (`duration` en ms), même si le Core s'arrête."""
    if type(minutes) is not int or not 1 <= minutes <= MAX_PAUSE_MIN:
        raise ValueError(f"durée invalide : 1 à {MAX_PAUSE_MIN} minutes")
    _request("POST", "/control/protection", {"enabled": False, "duration": minutes * 60_000})
