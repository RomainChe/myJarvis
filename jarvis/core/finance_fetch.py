"""Récupération IMAP des rapports « [Dépenses] Semaine NN » (Phase 6 point 4, étape 2) : `python -m jarvis finance fetch`.

Même compte et même coffre que le connecteur mail (`~/.jarvis/mail.json`, secret `mail_password`), lecture seule : boîte
ouverte en `readonly`, `BODY.PEEK`, rien n'est marqué lu, supprimé ni envoyé. N'est gardé que le mail qui vient de
l'adresse du compte lui-même (la tâche planifiée s'écrit à elle-même), de taille ≤ MAX_BYTES et reconnu par
`finance.parse` ; il est écrit sous `semaine-<année>-<NN>.eml` dans le dossier de `finance.py` (remplacé s'il existe).
Aucun contenu de mail n'est affiché ni journalisé : seulement le nombre de rapports écrits.
"""
import imaplib
import os
import re
import ssl
import time
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.utils import parseaddr
from pathlib import Path

from jarvis.core import finance
from jarvis.core.secrets import get_secret
from jarvis.tools import mail

DAYS, MAX_FETCH, BUDGET_S, MAX_STORED = 120, 16, 30, 60
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")  # strftime("%b") suit la locale
USER_OK = re.compile(r"[\w.+@-]{1,254}", re.ASCII)


def fetch_reports(dest: Path | None = None) -> int:
    return fetch_mails(dest or finance.finance_dir(), '"Semaine"', finance.parse,
                       lambda r: f"semaine-{r['year']}-{r['week']:02}.eml", "semaine-*.eml")


def fetch_mails(dest: Path, subject: str, parse, name, pattern: str = "*.eml") -> int:
    """Copie dans `dest` les mails du compte dont l'objet contient `subject` (déjà entre guillemets IMAP), reconnus par
    `parse(raw)` (None = ignoré), sous le nom `name(parse(raw))`. Générique : la veille IA réutilise ce chemin."""
    host, user = mail.load_config()
    password = get_secret("mail_password")
    if not password:
        raise RuntimeError("mot de passe mail absent du coffre (python -m jarvis secret set mail_password)")
    if not USER_OK.fullmatch(user):
        raise RuntimeError("adresse du compte mail invalide (~/.jarvis/mail.json)")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    oldest = now - timedelta(days=DAYS)
    since = f"{oldest.day:02}-{MONTHS[oldest.month - 1]}-{oldest.year}"
    written, deadline = 0, time.monotonic() + BUDGET_S
    imap = imaplib.IMAP4_SSL(host, ssl_context=ssl.create_default_context(), timeout=mail.TIMEOUT_S)
    try:
        imap.login(user, password)
        imap.select("INBOX", readonly=True)
        typ, data = imap.search(None, "SINCE", since, "FROM", f'"{user}"', "SUBJECT", subject)
        if typ != "OK" or data is None:
            raise RuntimeError("réponse IMAP inattendue")
        for num in reversed((data[0] or b"").split()[-MAX_FETCH:]):
            if time.monotonic() > deadline:
                break
            typ, parts = imap.fetch(num, f"(BODY.PEEK[]<0.{finance.MAX_BYTES + 1}>)")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None) if typ == "OK" else None
            if not raw or len(raw) > finance.MAX_BYTES:
                continue
            tmp = None
            try:
                msg = message_from_bytes(raw, policy=policy.default)
                sent = msg["Date"].datetime  # un Date hors fenêtre (an 9999...) pourrait masquer les vrais rapports
                report = parse(raw) if parseaddr(str(msg["From"] or ""))[1].lower() == user.lower() else None
                if report is None or not oldest <= sent.astimezone(timezone.utc) <= now + timedelta(days=1):
                    continue
                target = dest / name(report)
                stored = sorted(dest.glob(pattern), key=lambda f: f.stat().st_mtime)
                if not target.exists() and len(stored) >= MAX_STORED:
                    stored[0].unlink()  # plafond : le plus ancien cède la place, jamais de saturation silencieuse
                tmp = target.with_suffix(".tmp")
                tmp.write_bytes(raw)
                os.replace(tmp, target)
                written += 1
            except (OSError, ValueError, AttributeError):  # un mail ou un fichier en cause n'arrête pas les autres
                if tmp is not None:
                    tmp.unlink(missing_ok=True)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return written
