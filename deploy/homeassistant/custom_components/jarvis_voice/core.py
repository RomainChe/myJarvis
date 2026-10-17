"""Appel de POST /api/voice du Core (sans dépendance à Home Assistant : testé par tests/test_ha_component.py)."""
import json
import re
from urllib.parse import urlsplit

CLIENT_RE = re.compile(r"[a-z0-9_-]{1,32}")


def build_request(url: str, key: str, client: str, text: str) -> tuple[str, dict[str, str], bytes]:
    """(URL, en-têtes, corps) ; l'en-tête Origin est exigé par le Core pour tout POST (anti-CSRF)."""
    url = url.rstrip("/")
    parts = urlsplit(url)
    secure = parts.scheme == "https" or (parts.scheme == "http" and parts.hostname == "127.0.0.1")
    if not secure or parts.path or parts.query or parts.fragment or parts.username or not key or not CLIENT_RE.fullmatch(client):
        raise ValueError("réglage invalide")  # http seulement sur la boucle locale : la clé ne circule jamais en clair ailleurs
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}", "Origin": url}
    return url + "/api/voice", headers, json.dumps({"text": text, "client": client}).encode()


def parse_answer(raw: bytes | str, reply_max: int) -> str | None:
    """Texte à lire (peut être vide : Core « hors ligne »), ou None si la réponse est illisible."""
    try:
        answer = json.loads(raw)["answer"]
    except (ValueError, KeyError, TypeError):
        return None
    return answer if isinstance(answer, str) and len(answer) <= reply_max else None
