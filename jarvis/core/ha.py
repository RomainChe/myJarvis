"""Client REST de Home Assistant (stdlib). Le token vient du coffre Windows, jamais d'un fichier.

Les noms d'entités et les attributs renvoyés sont des DONNÉES (contenu externe) : les montrer au LLM via `as_data`.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import keyring.errors

from jarvis.core.secrets import get_secret

URL = os.environ.get("JARVIS_HA_URL") or "http://homeassistant.local:8123"
TIMEOUT = 5  # s
MAX_BYTES = 5_000_000  # /api/states d'une petite maison : quelques centaines de Ko
ENTITY = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")
SLUG = re.compile(r"[a-z0-9_]+")


class HAError(Exception):
    """Message sans token ni corps de réponse."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # urllib rejouerait l'en-tête Authorization vers la cible
        return None


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)  # ni proxy ni redirection : le token ne part que vers JARVIS_HA_URL


def _request(method: str, path: str, body: dict | None = None):
    parts = urllib.parse.urlsplit(URL)
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        raise HAError("JARVIS_HA_URL doit être http(s)://hôte, sans identifiants")
    try:
        token = get_secret("ha_token")
    except keyring.errors.KeyringError:
        raise HAError("coffre Windows indisponible") from None
    if not token:
        raise HAError("token absent : python -m jarvis secret set ha_token")
    req = urllib.request.Request(
        URL.rstrip("/") + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with _opener.open(req, timeout=TIMEOUT) as r:
            raw = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise HAError({401: "token refusé", 403: "action refusée pour l'utilisateur jarvis",
                       404: "introuvable"}.get(e.code, f"HA a répondu {e.code}")) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise HAError("Home Assistant injoignable (VM éteinte ou JARVIS_HA_URL incorrecte)") from None
    if len(raw) > MAX_BYTES:
        raise HAError("réponse trop volumineuse")
    try:
        return json.loads(raw)
    except ValueError:
        raise HAError("réponse illisible") from None


def version() -> str:
    return str(_request("GET", "/api/config").get("version", "?"))


def states() -> list[dict]:
    return _request("GET", "/api/states")


def state(entity_id: str) -> dict:
    if not ENTITY.fullmatch(entity_id):
        raise ValueError("entity_id invalide")
    return _request("GET", f"/api/states/{entity_id}")


def call_service(domain: str, service: str, entity_id: str, **data) -> list[dict]:
    """Un seul appareil par appel : jamais `all` ni une liste (une cible large demande un autre niveau)."""
    if not (SLUG.fullmatch(domain) and SLUG.fullmatch(service) and ENTITY.fullmatch(entity_id)):
        raise ValueError("domaine, service ou entity_id invalide")
    return _request("POST", f"/api/services/{domain}/{service}", {**data, "entity_id": entity_id})
