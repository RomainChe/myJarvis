"""Minuteurs, rappels et briefing du matin (Phase 7, pistes 2 et 4).

Le texte d'un rappel n'apparaît jamais dans un résultat d'outil : le journal est en ajout seul. Le briefing ne lit que
des sources non sensibles (météo, publications lol-clipper, veille IA, nombre de rappels) : mails et finances sont N2 et
privés, ils ne sortiraient pas à voix haute devant la TV ou un visiteur.
"""
from datetime import date, datetime

from jarvis.core import reminders, social, veille
from jarvis.core.tools import Level, tool
from jarvis.tools.home import weather

DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
TITLE_MAX = 60


def _at(due: float) -> str:
    return datetime.fromtimestamp(due).strftime("%H:%M")


@tool("timer_set", "Minuteur : prévient dans `duration` (« 20 minutes », « 1h30 », 1 minute à 24 h). `label` facultatif (« les pâtes »).",
      Level.N1, taint_blocked=True, hidden=("label",), duration=str, label=str)
def timer_set(duration: str, label: str) -> str:
    minutes = reminders.parse_duration(duration)
    due = reminders.now() + minutes * 60
    reminders.add(due, label, "timer")
    return f"Minuteur réglé pour {_at(due)} ({minutes} min)."


@tool("reminder_set", "Rappel ou réveil : `when` = « dans 20 minutes », « à 7h30 » ou « demain à 8h » (24 h au plus), `label` = ce dont il faut se souvenir.",
      Level.N1, taint_blocked=True, hidden=("label",), when=str, label=str)
def reminder_set(when: str, label: str) -> str:
    now = datetime.fromtimestamp(reminders.now())
    due = reminders.parse_when(when, now)
    reminders.add(due.timestamp(), label, "reminder")
    day = "" if due.date() == now.date() else " demain"
    return f"Rappel réglé pour{day} {due:%H:%M}."


@tool("reminder_list", "Liste les minuteurs et rappels en attente (id, heure, type ; jamais le texte).", Level.N0)
def reminder_list() -> str:
    rows = [r for r in reminders.pending() if r[3] != "briefing"]
    if not rows:
        return "Aucun minuteur ni rappel en attente."
    return "\n".join(f"#{id_} à {_at(due)} : {'minuteur' if kind == 'timer' else 'rappel'}" for id_, due, _, kind in rows)


@tool("reminder_cancel", "Annule un minuteur ou un rappel : `id` (voir reminder_list), 0 = le plus proche.", Level.N1,
      taint_blocked=True, id=int)
def reminder_cancel(id: int) -> str:
    done = reminders.cancel(id)
    if done is None:
        raise ValueError("aucun rappel à annuler")
    return f"Rappel {done} annulé."


def _weather_line() -> str:
    w = weather._weather()
    parts = [f"{w['temp_c']:.0f} °C, {w['sky'].lower()}"]
    if w["min_c"] is not None and w["max_c"] is not None:
        parts.append(f"de {w['min_c']:.0f} à {w['max_c']:.0f} °C aujourd'hui")
    if w["rain_chance"] is not None and w["rain_chance"] >= 30:
        parts.append(f"{w['rain_chance']:.0f} % de risque de pluie")
    if w["alerts"]:
        parts.append("attention : " + ", ".join(w["alerts"]))
    return "Météo : " + ", ".join(parts) + "."


def _social_line(today: date) -> str | None:
    snap = social.snapshot()
    pub = [r["title"][:TITLE_MAX] for r in snap["published"] if r["at"][:10] == today.isoformat()]
    todo = [r for r in snap["scheduled"] if r["at"][:10] == today.isoformat()]
    parts = []
    if pub:
        parts.append(f"{len(pub)} publication(s) en ligne aujourd'hui ({', '.join(pub[:3])})")
    if todo:
        parts.append(f"{len(todo)} programmée(s) aujourd'hui, la prochaine à {todo[0]['at'][11:16]}")
    return "lol-clipper : " + ", ".join(parts) + "." if parts else None


def _veille_line() -> str | None:
    issues = veille.snapshot()["issues"]
    titles = [i["lines"][0][:TITLE_MAX] for i in (issues[0]["items"] if issues else [])[:2] if i.get("lines")]
    return "Veille IA : " + " ; ".join(titles) + "." if titles else None


def _reminders_line(now: float, today: date) -> str | None:
    rows = [r for r in reminders.pending() if r[3] != "briefing" and datetime.fromtimestamp(r[1]).date() == today and r[1] > now]
    return f"{len(rows)} rappel(s) aujourd'hui, le prochain à {_at(rows[0][1])}." if rows else None


def build_briefing(now: datetime | None = None) -> str:
    """Texte du briefing. Une source en panne est omise : le reste est dit quand même."""
    now = now or datetime.fromtimestamp(reminders.now())
    lines = [f"Bonjour. Nous sommes {DAYS[now.weekday()]} {now.day} {MONTHS[now.month - 1]}."]
    for part in (_weather_line, lambda: _reminders_line(now.timestamp(), now.date()), lambda: _social_line(now.date()), _veille_line):
        try:
            if line := part():
                lines.append(line)
        except Exception:  # noqa: BLE001 (lieu non configuré, réseau, dossier absent : source ignorée)
            pass
    return " ".join(lines)


@tool("briefing", "Briefing du jour : date, météo, rappels, publications lol-clipper et titres de la veille IA. Sans mails ni finances.",
      Level.N0, external=True)
def briefing() -> str:
    return build_briefing()
