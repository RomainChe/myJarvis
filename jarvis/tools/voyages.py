"""Changer de destination dans flight-price-tracker (Phase 6 point 10, étape 3) : `voyage_destination` (N2, `taint_blocked`).

Changer de destination = nouvelle recherche en tête de `searches` dans `config.yaml`, les recherches actives commentées
(leur historique reste dans `data/prices.csv`, indexé par `name`) ; jamais un renommage. Le fichier est construit à partir de
`origin/main` (après `git fetch`) et commité par la plomberie git (`hash-object`, index temporaire, `commit-tree`) puis
poussé sur `main` sans `--force` : la copie de travail et la branche locale du propriétaire ne sont jamais touchées. Avant
le commit, le `load_config` du projet (son `.venv`) valide le fichier : départs France + Barcelone, destination connue.
Champs bornés par des motifs stricts (ni `@`, ni `:`, ni chiffres hors dates) : aucun secret ni e-mail ne peut entrer dans
le dépôt public. Push refusé (le workflow a commité entre-temps) = une seconde tentative sur le nouveau `origin/main`.
"""
import json
import os
import re
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

from jarvis.core import voyages
from jarvis.core.tools import Level, tool

PLACE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ' -]{1,39}")  # ville, pays ou code IATA
MAX_ORIGINS, MAX_STAYS, MAX_STAY_DAYS, MAX_AHEAD_DAYS, MAX_ALERT = 10, 5, 90, 400, 20_000
CHECK = "import sys; from tracker.config import load_config; load_config(sys.argv[1])"
CHECK_TIMEOUT_S, PUSH_TIMEOUT_S = 60, 60


def _place(value: str, label: str) -> str:
    value = " ".join(value.split())
    if not PLACE.fullmatch(value):
        raise ValueError(f"{label} invalide : lettres, espaces, tirets et apostrophes seulement (40 caractères au plus)")
    return value


def _day(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"{label} : date attendue au format AAAA-MM-JJ") from None


def _spec(destination, depart_from, depart_to, stay_days, return_date, origins, alert_below, today=None) -> dict:
    """Paramètres validés ; l'appartenance des villes à la zone autorisée est vérifiée par le projet lui-même."""
    today = today or date.today()
    places = [_place(o, "ville de départ") for o in origins.split(",") if o.strip()]
    if not 0 < len(places) <= MAX_ORIGINS:
        raise ValueError(f"de 1 à {MAX_ORIGINS} villes de départ, séparées par des virgules")
    start, end = _day(depart_from, "début de la période"), _day(depart_to, "fin de la période")
    if not today < start <= end <= today + timedelta(days=MAX_AHEAD_DAYS):
        raise ValueError(f"période : début au plus tôt demain, fin après le début et dans les {MAX_AHEAD_DAYS} jours")
    spec = {"destination": _place(destination, "destination"), "origins": places, "from": start, "to": end,
            "alert": alert_below, "back": None, "stays": []}
    if bool(stay_days.strip()) == bool(return_date.strip()):
        raise ValueError("indique soit des durées de séjour, soit une date de retour fixe")
    if return_date.strip():
        spec["back"] = _day(return_date, "date de retour")
        if spec["back"] <= end:
            raise ValueError("la date de retour doit suivre la fin de la période de départ")
    else:
        try:
            spec["stays"] = sorted({int(d) for d in stay_days.split(",") if d.strip()})
        except ValueError:
            raise ValueError("durées de séjour : nombres de jours séparés par des virgules") from None
        if not 0 < len(spec["stays"]) <= MAX_STAYS or not all(0 < d <= MAX_STAY_DAYS for d in spec["stays"]):
            raise ValueError(f"de 1 à {MAX_STAYS} durées de séjour, entre 1 et {MAX_STAY_DAYS} jours")
    if not 0 <= alert_below <= MAX_ALERT:
        raise ValueError(f"seuil d'alerte entre 0 (aucun) et {MAX_ALERT} €")
    spec["name"] = f"{spec['destination']} {start.isoformat()}"
    return spec


def _block(spec: dict, nl: str) -> str:
    q = lambda v: json.dumps(v, ensure_ascii=False)  # noqa: E731  (chaîne JSON = scalaire YAML entre guillemets)
    lines = [f"  - name: {q(spec['name'])}",
             f"    origins: [{', '.join(q(o) for o in spec['origins'])}]",
             f"    destination: {q(spec['destination'])}",
             f"    depart_from: {spec['from'].isoformat()}",
             f"    depart_to: {spec['to'].isoformat()}",
             f"    return_date: {spec['back'].isoformat()}" if spec["back"] else f"    stay_days: [{', '.join(map(str, spec['stays']))}]"]
    if spec["alert"]:
        lines.append(f"    alert_below: {spec['alert']}")
    return nl.join(lines) + nl


def edit(text: str, spec: dict) -> str:
    """Nouvelle recherche juste sous `searches:`, chaque ligne active de la section commentée (commentaires gardés)."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    try:
        at = next(i for i, line in enumerate(lines) if line.rstrip() == "searches:")
    except StopIteration:
        raise ValueError("config.yaml du projet : section `searches:` introuvable") from None
    out, inside = lines[:at + 1] + [_block(spec, nl)], True
    for line in lines[at + 1:]:
        body = line.strip()
        if inside and body and not line[0].isspace() and not body.startswith("#"):
            inside = False  # clé suivante du premier niveau : fin de la section
        if inside and body and not body.startswith("#"):
            indent = len(line) - len(line.lstrip(" "))
            line = line[:min(indent, 2)] + "# " + line[min(indent, 2):]
        out.append(line)
    return "".join(out)


def _validate(root: Path, text: str) -> None:
    """`load_config` du projet sur le fichier candidat ; son message d'erreur est rendu (tronqué), rien n'est commité."""
    python = root / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise ValueError("environnement .venv de flight-price-tracker introuvable : rien n'a été modifié")
    fd, path = tempfile.mkstemp(suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as h:
            h.write(text)
        done = subprocess.run([str(python), "-c", CHECK, path], cwd=root, capture_output=True, timeout=CHECK_TIMEOUT_S,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        os.unlink(path)
    if done.returncode:
        last = (done.stderr.decode("utf-8", "replace").strip().splitlines() or ["?"])[-1]
        raise ValueError(f"configuration refusée par le projet : {last.split(': ', 1)[-1][:200]}")


def _commit(root: Path, base: str, text: str, message: str) -> str:
    blob = voyages._git(root, "hash-object", "-w", "--stdin", input=text.encode("utf-8")).decode().strip()
    with tempfile.TemporaryDirectory() as d:  # index à part : celui de la copie de travail n'est pas touché
        env = {"GIT_INDEX_FILE": str(Path(d) / "index")}
        voyages._git(root, "read-tree", base, env=env)
        voyages._git(root, "update-index", "--cacheinfo", f"100644,{blob},config.yaml", env=env)
        tree = voyages._git(root, "write-tree", env=env).decode().strip()
    return voyages._git(root, "commit-tree", tree, "-p", base, "-m", message).decode().strip()


def _describe(destination, depart_from, depart_to, stay_days, return_date, origins, alert_below) -> str:
    s = _spec(destination, depart_from, depart_to, stay_days, return_date, origins, alert_below)
    when = f"départ du {s['from']:%d/%m/%Y} au {s['to']:%d/%m/%Y}" if s["from"] != s["to"] else f"départ le {s['from']:%d/%m/%Y}"
    back = f"retour le {s['back']:%d/%m/%Y}" if s["back"] else f"séjour de {', '.join(map(str, s['stays']))} j"
    alert = f", alerte sous {s['alert']} €" if s["alert"] else ""
    return (f"Suivre « {s['name']} » depuis {', '.join(s['origins'])} : {when}, {back}{alert}. "
            f"Les recherches en cours seront mises en pause, commit et push sur le dépôt public flight-price-tracker.")


@tool("voyage_destination", "Change la destination suivie par flight-price-tracker : nouvelle recherche (les actuelles en pause), "
                            "commit et push de config.yaml. Dates AAAA-MM-JJ ; `stay_days` (ex. \"10,14\") OU `return_date`, "
                            "l'autre vide ; `origins` villes de France ou Barcelone séparées par des virgules ; `alert_below` en €, 0 = aucun.",
      Level.N2, taint_blocked=True, describe=_describe, destination=str, depart_from=str, depart_to=str, stay_days=str,
      return_date=str, origins=str, alert_below=int)
def voyage_destination(destination, depart_from, depart_to, stay_days, return_date, origins, alert_below) -> str:
    spec = _spec(destination, depart_from, depart_to, stay_days, return_date, origins, alert_below)
    root = voyages.tracker_dir()
    if not (root / ".git").is_dir():
        raise ValueError("clone git de flight-price-tracker introuvable : rien n'a été modifié")
    for attempt in range(2):
        try:
            voyages._git(root, "fetch", "--quiet", "--no-tags", "origin", "main")
            base = voyages._git(root, "rev-parse", "origin/main").decode().strip()
            text = voyages._git(root, "show", f"{base}:config.yaml").decode("utf-8")
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
            raise ValueError("GitHub injoignable ou config.yaml illisible : rien n'a été modifié") from None
        new = edit(text, spec)
        _validate(root, new)
        try:
            commit = _commit(root, base, new, f"config : suivi de {spec['name']} (les recherches en cours en pause)")
            voyages._git(root, "push", "--quiet", "origin", f"{commit}:refs/heads/main", timeout=PUSH_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            if attempt:  # deux refus : sans doute pas une simple course avec le workflow quotidien
                raise ValueError("push refusé par GitHub : rien n'a été modifié") from None
            continue
        return f"Suivi passé sur « {spec['name']} » (commit {commit[:7]} poussé). Le prochain relevé quotidien l'inclura."
    raise AssertionError("inatteignable")
