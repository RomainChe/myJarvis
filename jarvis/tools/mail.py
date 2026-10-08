"""Connecteur mail en lecture seule (Phase 6, point 6) : `mail_recent` (N2, privé, contenu tiers).

Compte : `~/.jarvis/mail.json` (`{"host": "imap.gmail.com", "user": "..."}`), jamais dans le dépôt. Mot de passe d'application
dans le coffre (`python -m jarvis secret set mail_password`). IMAP/SSL certificat vérifié, boîte ouverte en lecture seule et
`BODY.PEEK` : rien n'est marqué lu, rien n'est envoyé ni supprimé. Expéditeur, objet et texte sont des DONNÉES hostiles
(injection) : `external` interdit N2/N3 au LLM ensuite, `private` garde le contenu hors du journal.
"""
import email
import imaplib
import json
import time
import ssl
from datetime import datetime, timedelta, timezone
from email import policy
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path

from jarvis.core.secrets import get_secret
from jarvis.core.tools import Level, tool

CONFIG = Path.home() / ".jarvis" / "mail.json"
HOURS_MAX, MAILS_MAX, SNIPPET, FIELD, FETCH_BYTES, TIMEOUT_S, BUDGET_S = 72, 8, 100, 60, 20000, 10, 30  # sortie ~1 500 car. : tient dans les 2 000 de as_data


def _clean(text: str, n: int) -> str:
    return " ".join("".join(c if c.isprintable() else " " for c in text).split())[:n]


def load_config() -> tuple[str, str]:
    try:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        host, user = raw["host"], raw["user"]
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError("compte mail non configuré (~/.jarvis/mail.json)") from None
    if not (isinstance(host, str) and isinstance(user, str) and host and user):
        raise RuntimeError("compte mail non configuré (~/.jarvis/mail.json)")
    return host, user


def _parse(raw: bytes) -> tuple[datetime, dict] | None:
    msg = email.message_from_bytes(raw, policy=policy.default)
    try:
        sent = parsedate_to_datetime(str(msg["Date"]))
        sent = sent if sent.tzinfo else sent.replace(tzinfo=timezone.utc)
    except Exception:  # Date: hostile (OverflowError...) : le mail est ignoré, la lecture continue
        return None
    try:  # corps tronqué à FETCH_BYTES : une structure MIME coupée donne un extrait vide, pas une erreur
        part = msg.get_body(("plain",))
        body = part.get_content() if part else ""
    except Exception:
        body = ""
    name, addr = parseaddr(str(msg["From"] or ""))
    return sent, {"de": _clean(name or addr, FIELD), "objet": _clean(str(msg["Subject"] or ""), FIELD),
                  "extrait": _clean(body, SNIPPET)}


@tool("mail_recent", f"Résume-moi les mails reçus ces dernières heures (hours : 1 à {HOURS_MAX}) : expéditeur, objet, extrait.",
      Level.N2, private=True, external=True, hours=int)
def mail_recent(hours: int) -> dict:
    if not 1 <= hours <= HOURS_MAX:
        raise ValueError(f"hours : 1 à {HOURS_MAX}")
    host, user = load_config()
    password = get_secret("mail_password")
    if not password:
        raise RuntimeError("mot de passe mail absent du coffre (python -m jarvis secret set mail_password)")
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    found, deadline = [], time.monotonic() + BUDGET_S
    imap = imaplib.IMAP4_SSL(host, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_S)
    try:
        imap.login(user, password)
        imap.select("INBOX", readonly=True)
        typ, data = imap.search(None, "SINCE", (since - timedelta(days=1)).strftime("%d-%b-%Y"))  # SINCE n'a que le jour
        if typ != "OK" or not data or not data[0]:
            raise RuntimeError("réponse IMAP inattendue")
        for num in reversed(data[0].split()[-3 * MAILS_MAX:]):  # les plus récents d'abord, borne dure sur le nombre lu
            if time.monotonic() > deadline:
                break
            typ, parts = imap.fetch(num, f"(BODY.PEEK[]<0.{FETCH_BYTES}>)")
            if typ != "OK":
                continue
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            parsed = _parse(raw) if raw else None
            if parsed and parsed[0] >= since:
                found.append(parsed)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    found.sort(key=lambda m: m[0], reverse=True)
    return {"total": len(found), "mails": [m for _, m in found[:MAILS_MAX]]}
