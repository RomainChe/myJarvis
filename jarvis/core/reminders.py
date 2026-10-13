"""Minuteurs, rappels et briefing automatique : table `reminders` dans la base du journal, annonce à l'échéance.

- Le texte d'un rappel reste dans la base jusqu'à l'annonce, puis la ligne est supprimée. Le journal (ajout seul, non
  purgeable) n'en garde jamais le texte : l'id et la longueur seulement.
- L'annonce est lue par le PC et poussée à tous les appareils SANS le texte (même décision que les confirmations).
- Le briefing automatique (`JARVIS_BRIEFING_AT=07:30`) est un rappel de type `briefing` qui se réarme chaque jour.
"""
import os
import re
import threading
import time
from datetime import datetime, timedelta

from .audit import Audit
from .router import fold

SCHEMA = ("CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, due REAL NOT NULL, "
          "label TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('timer', 'reminder', 'briefing')))")
MAX_PENDING = 50
LABEL_MAX = 200
MAX_MINUTES = 24 * 60
LATE_BRIEFING_S = 2 * 3600  # PC éteint au créneau : un briefing du matin lu à midi n'a plus de sens
TICK_S = 5

_audit: Audit | None = None
_wall = time.time  # remplacé dans les tests

_NUMBERS = (("une demi heure", "30 min"), ("un quart d heure", "15 min"), ("une heure", "1 h"), ("une minute", "1 min"))
_DURATION = re.compile(r"(?:(\d{1,2}) ?h(?:eures?)?)? ?(?:(\d{1,4}) ?(?:min(?:utes?)?|mn)?)?")
_CLOCK = re.compile(r"(demain )?(?:a |vers )?(\d{1,2}) ?(?:h|:|heures?) ?(\d{2})?")


def now() -> float:
    return _wall()


def load(audit: Audit) -> None:
    """Branche les rappels sur la base du journal (démarrage de la CLI et du serveur)."""
    global _audit
    with audit.lock:
        audit.db.execute(SCHEMA)
    _audit = audit


def _db() -> Audit:
    if _audit is None:
        raise RuntimeError("rappels non initialisés")
    return _audit


def _clean(text: str) -> str:
    return " ".join(text.split())[:LABEL_MAX]


def parse_duration(text: str) -> int:
    """« 20 minutes », « 1h30 », « une demi-heure », « de 2 heures » -> minutes (1 à 24 h). ValueError sinon."""
    s = fold(text).replace("-", " ").replace("'", " ").strip()
    for words, digits in _NUMBERS:
        s = s.replace(words, digits)
    s = re.sub(r"^(?:de|pour|sur|dans|en|d) ", "", s).strip()
    m = _DURATION.fullmatch(s)
    if not s or not m or not any(m.groups()):
        raise ValueError("durée non comprise : écrire par exemple « 20 minutes » ou « 1h30 »")
    minutes = int(m[1] or 0) * 60 + int(m[2] or 0)
    if not 1 <= minutes <= MAX_MINUTES:
        raise ValueError("durée : de 1 minute à 24 heures")
    return minutes


def parse_when(text: str, now: datetime) -> datetime:
    """« dans 20 minutes », « à 7h30 », « demain à 8h » -> instant local futur (24 h au plus). ValueError sinon."""
    s = fold(text).strip()
    if s.startswith("dans "):
        return now + timedelta(minutes=parse_duration(s[5:]))
    m = _CLOCK.fullmatch(s)
    if not m or int(m[2]) > 23 or int(m[3] or 0) > 59:
        raise ValueError("heure non comprise : écrire par exemple « à 7h30 », « demain à 8h » ou « dans 20 minutes »")
    due = now.replace(hour=int(m[2]), minute=int(m[3] or 0), second=0, microsecond=0)
    if m[1]:
        due += timedelta(days=1)
    elif due <= now:  # « à 7h » à 9 h : demain
        due += timedelta(days=1)
    return due


def add(due: float, label: str, kind: str) -> int:
    a = _db()
    with a.lock:
        if a.db.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] >= MAX_PENDING:
            raise ValueError(f"{MAX_PENDING} rappels en attente au plus")
        return a.db.execute("INSERT INTO reminders (due, label, kind) VALUES (?, ?, ?)", (due, _clean(label), kind)).lastrowid


def pending() -> list[tuple[int, float, str, str]]:
    a = _db()
    with a.lock:
        return a.db.execute("SELECT id, due, label, kind FROM reminders ORDER BY due, id").fetchall()


def cancel(id_: int) -> int | None:
    """Annule le rappel `id_` (0 = le plus proche, hors briefing). Renvoie l'id annulé, None s'il n'existe pas."""
    a = _db()
    with a.lock:
        if id_ == 0:
            row = a.db.execute("SELECT id FROM reminders WHERE kind != 'briefing' ORDER BY due, id LIMIT 1").fetchone()
            id_ = row[0] if row else 0
        done = a.db.execute("DELETE FROM reminders WHERE id = ? AND kind != 'briefing'", (id_,)).rowcount
    return id_ if done else None


def _pop_due(now: float) -> list[tuple[int, float, str, str]]:
    a = _db()
    with a.lock:
        rows = a.db.execute("SELECT id, due, label, kind FROM reminders WHERE due <= ? ORDER BY due, id", (now,)).fetchall()
        a.db.executemany("DELETE FROM reminders WHERE id = ?", [(r[0],) for r in rows])
    return rows


def briefing_time(raw: str | None = None) -> tuple[int, int] | None:
    """`JARVIS_BRIEFING_AT` (« 07:30 ») ou None. Valeur invalide : ValueError (le serveur démarre sans briefing)."""
    raw = (os.environ.get("JARVIS_BRIEFING_AT", "") if raw is None else raw or "").strip()
    if not raw:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise ValueError("JARVIS_BRIEFING_AT doit être HH:MM")
    return int(m[1]), int(m[2])


def arm_briefing(at: tuple[int, int], now: datetime | None = None) -> None:
    """Pose le prochain briefing s'il n'y en a pas déjà un en attente."""
    a = _db()
    with a.lock:
        if a.db.execute("SELECT 1 FROM reminders WHERE kind = 'briefing'").fetchone():
            return
    now = now or datetime.fromtimestamp(_wall())
    due = now.replace(hour=at[0], minute=at[1], second=0, microsecond=0)
    add((due if due > now else due + timedelta(days=1)).timestamp(), "", "briefing")


def tick(announce, at: tuple[int, int] | None = None, now: float | None = None) -> int:
    """Annonce les échéances passées ; `announce(kind, label, late_s)` renvoie ce qui a été fait (« voix + push »), journalisé.
    Renvoie le nombre d'échéances traitées."""
    now = _wall() if now is None else now
    rows = _pop_due(now)
    for id_, due, label, kind in rows:
        late = now - due
        if kind == "briefing" and at is not None:
            arm_briefing(at, datetime.fromtimestamp(now))
        if kind == "briefing" and late > LATE_BRIEFING_S:
            continue
        try:
            outcome = announce(kind, label, late) or "annoncé"
        except Exception as e:  # noqa: BLE001 (l'annonce est un confort : le rappel est déjà retiré, la panne est journalisée)
            outcome = f"annonce échouée : {type(e).__name__}"
        _db().log("rappels", f"{kind}_fire", {"id": id_, "len": len(label)}, None, "auto", outcome)
    return len(rows)


def run(announce, at: tuple[int, int] | None = None, stop: threading.Event | None = None, every: float = TICK_S) -> None:
    """Boucle du serveur : un thread, une vérification toutes les `every` secondes. Ne s'arrête que sur `stop`."""
    stop = stop or threading.Event()
    fails = 0
    armed = at is None
    while True:
        try:
            if not armed:
                arm_briefing(at)
                armed = True
            tick(announce, at)
            fails = 0
        except Exception as e:  # noqa: BLE001 (base verrouillée un instant : on réessaie au tour suivant)
            fails += 1
            if fails == 5:  # une panne persistante est tracée une fois, sans message d'exception
                try:
                    _db().log("rappels", "reminders_down", {}, None, "refusé", type(e).__name__)
                except Exception:  # noqa: BLE001
                    pass
        if stop.wait(every):
            return
