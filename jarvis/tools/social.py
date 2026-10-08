"""Planning des publications de lol-clipper (Phase 6 point 3, étape 4) : `social_schedule` (N0) et `social_reschedule` (N2).

Le planning, ce sont les fichiers `<vidéo>.publish.todo` de lol-clipper (voir jarvis/core/social.py). `social_reschedule` ne change
que `publish_at` d'un de ces fichiers, désigné par son titre exact ; le clipper met en ligne à la nouvelle heure. Ni création,
ni suppression, ni publication immédiate : ces actions restent à lol-clipper. Refusé à la voix (N2 : plafond N0/N1) et au LLM
après du contenu externe (`taint_blocked`).
"""
import json
import os
import tempfile
from datetime import datetime, timedelta

from jarvis.core import social
from jarvis.core.tools import Level, tool

MAX_DAYS, MAX_LIST, TITLE_MAX = 30, 10, 80
MIN_LEAD = timedelta(minutes=10)  # sinon la prochaine passe du clipper publierait aussitôt
BUSY = timedelta(minutes=2)  # un créneau échu ou imminent est peut-être en cours d'envoi par lol-clipper


def _find(title: str):
    """Le seul .publish.todo (hors lien symbolique) de ce titre ; erreur claire s'il y en a zéro ou plusieurs."""
    root = social.clips_dir()
    found = [f for folder in social.FOLDERS for f in (root / folder).glob("*.publish.todo")
             if not f.is_symlink() and social._title(f, ".publish.todo") == title.strip()[:TITLE_MAX]]
    if not found:
        raise ValueError("aucune vidéo programmée de ce titre (social_schedule liste le planning)")
    if len(found) > 1:
        raise ValueError("plusieurs vidéos programmées portent ce titre")
    return found[0]


def _stamp(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _guard(todo, data: dict, now: datetime) -> datetime:
    """Refuse un report si l'ancien créneau est illisible, échu ou imminent, ou si la vidéo est déjà en ligne."""
    old = _stamp(data.get("publish_at"))
    if old is None:
        raise ValueError("fichier de planning illisible")
    if old <= now + BUSY:
        raise ValueError("créneau échu ou imminent : lol-clipper est peut-être en train de publier")
    stem = todo.name[: -len(".publish.todo")]
    only = data.get("only")
    for platform in ("youtube", "tiktok") if only not in ("youtube", "tiktok") else (only,):
        if (todo.parent / f"{stem}.{platform}.json").exists():
            raise ValueError(f"déjà publiée sur {platform}")
    return old


def _new_time(at: str, todo, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    try:
        when = datetime.fromisoformat(at.strip())
    except ValueError:
        raise ValueError("date invalide : écrire AAAA-MM-JJTHH:MM, heure locale") from None
    if when.tzinfo is not None:
        raise ValueError("date sans fuseau : heure locale du PC")
    when = when.replace(second=0, microsecond=0)
    if not now + MIN_LEAD <= when <= now + timedelta(days=MAX_DAYS):
        raise ValueError(f"l'heure doit être à plus de {MIN_LEAD.seconds // 60} minutes et dans les {MAX_DAYS} jours")
    for other in todo.parent.glob("*.publish.todo"):
        if other != todo and (data := social._read(other)) and _stamp(data.get("publish_at")) == when:
            raise ValueError("un autre créneau est déjà pris à cette heure")
    return when


def _describe(title: str, at: str) -> str:
    todo = _find(title)
    data, now = social._read(todo) or {}, datetime.now()
    old = _guard(todo, data, now)
    return f"« {title.strip()[:TITLE_MAX]} » : {old.isoformat(timespec='minutes')} → {_new_time(at, todo, now).isoformat(timespec='minutes')}"


@tool("social_schedule", "Liste les publications programmées de lol-clipper (titre, plateforme, date), les plus proches d'abord.", Level.N0)
def social_schedule() -> dict:
    rows = social.snapshot()["scheduled"][:MAX_LIST]
    return {"scheduled": [{"title": r["title"][:TITLE_MAX], "platform": r["platform"], "at": r["at"]} for r in rows]}


@tool("social_reschedule", "Décale une publication programmée de lol-clipper : `title` exact (voir social_schedule) et nouvelle heure "
                           "locale `at` au format AAAA-MM-JJTHH:MM (futur, 30 jours au plus, créneau libre).",
      Level.N2, taint_blocked=True, describe=_describe, title=str, at=str)
def social_reschedule(title: str, at: str) -> dict:
    todo = _find(title)
    data, now = social._read(todo) or {}, datetime.now()
    old, new = _guard(todo, data, now), _new_time(at, todo, now)
    fd, tmp = tempfile.mkstemp(dir=todo.parent, prefix=todo.name, suffix=".tmp")  # .tmp exclusif, hors du motif *.publish.todo
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump({**data, "publish_at": new.isoformat()}, h)
        again = social._read(todo)  # lol-clipper a pu publier et supprimer le fichier pendant ce temps
        if again is None or _stamp(again.get("publish_at")) != old:
            raise ValueError("le planning a changé pendant l'opération : rien n'a été modifié")
        os.replace(tmp, todo)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {"title": title.strip()[:TITLE_MAX], "from": old.isoformat(timespec="minutes"), "to": new.isoformat(timespec="minutes")}
