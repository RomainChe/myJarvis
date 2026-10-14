"""Voyages (Phase 6 point 10) : `hotel_itineraire` (N0, Phase 4 de hotel-price-tracker) lit le dernier relevé d'hôtels ;
`voyage_prix` (N0, étape 4 : voix et chat) lit le meilleur prix ; `voyage_destination` (N2,
`taint_blocked`, étape 3) change de destination dans flight-price-tracker ; `voyage_recherche` (N1, `taint_blocked`,
étape 5) lance une recherche ponctuelle (workflow `search.yml`, résultat par e-mail, config.yaml non touché).

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
import time
from datetime import date, timedelta
from pathlib import Path

from jarvis.core import voyages
from jarvis.core.tools import Level, tool

PLACE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ' -]{1,39}")  # ville, pays ou code IATA
MAX_ORIGINS, MAX_STAYS, MAX_STAY_DAYS, MAX_AHEAD_DAYS, MAX_ALERT = 10, 5, 90, 400, 20_000
CHECK = "import sys; from tracker.config import load_config; load_config(sys.argv[1])"
CHECK_TIMEOUT_S, PUSH_TIMEOUT_S, GH_TIMEOUT_S, SEARCH_EVERY_S = 60, 60, 30, 60
_last_search = [0.0]  # une recherche par minute : un client en boucle ne peut pas inonder la boîte mail
AUTHOR, AUTHOR_EMAIL = "JARVIS", "jarvis@users.noreply.github.com"


def _fmt_day(iso: str) -> str:
    try:
        return f"{date.fromisoformat(iso):%d/%m}"
    except ValueError:
        return iso


def summary(snap: dict) -> str:
    """Phrase courte et parlable : meilleur prix de la recherche la plus récente, tendance, plus bas de la période."""
    if not snap["configured"] or not snap["searches"]:
        return "Je n'ai aucun relevé de prix de vols pour l'instant."
    s = snap["searches"][0]
    b = s["best"]
    out = f"{s['name']} : {b['price']:.0f} € depuis {b['origin']}"
    if b["depart_date"] and b["return_date"]:
        out += f", du {_fmt_day(b['depart_date'])} au {_fmt_day(b['return_date'])}"
    if b["stops"] is not None:
        out += ", direct" if b["stops"] == 0 else f", {b['stops']} escale(s)"
    out += f" (relevé du {_fmt_day(s['last_run'])})."
    if s["previous"] is not None and abs(b["price"] - s["previous"]) >= 1:
        diff = b["price"] - s["previous"]
        out += f" {'Hausse' if diff > 0 else 'Baisse'} de {abs(diff):.0f} € depuis le relevé précédent."
    if s["lowest"] < b["price"]:
        out += f" Le plus bas observé : {s['lowest']:.0f} €."
    return out


@tool("voyage_prix", "Meilleur prix actuel des vols suivis par flight-price-tracker (recherche la plus récente) : prix, départ, dates, "
                     "escales, tendance.", Level.N0, external=True)
def voyage_prix() -> str:
    return summary(voyages.snapshot())


def hotel_summary(snap: dict) -> str:
    """Phrase courte et parlable : totaux du dernier relevé puis l'hôtel recommandé de chaque étape."""
    if not snap["configured"]:
        return "Je n'ai aucun relevé de prix d'hôtels pour l'instant."
    stages, cur = snap["etapes"], snap["devise"]
    cur = "€" if cur in ("", "EUR") else cur
    out = "Hébergement"
    if stages and stages[0]["chk_in"] and stages[-1]["chk_out"]:
        out += f" du {_fmt_day(stages[0]['chk_in'])} au {_fmt_day(stages[-1]['chk_out'])}"
    out += (f" : {snap['total_recommande']:.0f} {cur} recommandé, {snap['total_moins_cher']:.0f} {cur} le moins cher, "
            f"trajets compris (relevé du {_fmt_day(snap['date'])}).")
    if not snap["complet"]:
        out += " Relevé incomplet : une étape n'a pas d'offre ou de trajet."
    picks = [f"{s['ville'].capitalize()} : {s['recommande']['hotel']}, {s['recommande']['nuit']:.0f} {cur}/nuit"
             for s in stages if s["recommande"]]
    return out + (" " + " ; ".join(picks) + "." if picks else "")


@tool("hotel_itineraire", "Hébergement du voyage suivi par hotel-price-tracker (dernier relevé) : total recommandé et moins cher "
                          "(trajets compris), hôtel recommandé par ville.", Level.N0, external=True)
def hotel_itineraire() -> str:
    return hotel_summary(voyages.hotel_snapshot())


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
                              env={k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if k in os.environ}
                                  | {"PYTHONIOENCODING": "utf-8"},
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        os.unlink(path)
    if done.returncode:
        last = (done.stderr.decode("utf-8", "replace").strip().splitlines() or ["?"])[-1]
        raise ValueError(f"configuration refusée par le projet : {last.split(': ', 1)[-1].replace(str(Path.home()), '~')[:200]}")


def _commit(root: Path, base: str, text: str, message: str) -> str:
    blob = voyages._git(root, "hash-object", "-w", "--stdin", input=text.encode("utf-8")).decode().strip()
    with tempfile.TemporaryDirectory() as d:  # index à part : celui de la copie de travail n'est pas touché
        env = {"GIT_INDEX_FILE": str(Path(d) / "index")}
        voyages._git(root, "read-tree", base, env=env)
        voyages._git(root, "update-index", "--cacheinfo", f"100644,{blob},config.yaml", env=env)
        tree = voyages._git(root, "write-tree", env=env).decode().strip()
    who = {"GIT_AUTHOR_NAME": AUTHOR, "GIT_COMMITTER_NAME": AUTHOR, "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,  # jamais l'identité git du PC
           "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL}
    return voyages._git(root, "commit-tree", tree, "-p", base, "-m", message, env=who).decode().strip()


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
        if f"- name: {json.dumps(spec['name'], ensure_ascii=False)}" in (l.strip() for l in text.splitlines()):
            return f"« {spec['name']} » est déjà suivi : rien à pousser."  # push expiré mais abouti, ou même demande refaite
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


def _describe_search(destination, depart_from, depart_to, stay_days, return_date, origins, alert_below) -> str:
    s = _spec(destination, depart_from, depart_to, stay_days, return_date, origins, alert_below)
    back = f"retour le {s['back']:%d/%m/%Y}" if s["back"] else f"séjour de {', '.join(map(str, s['stays']))} j"
    return (f"Recherche ponctuelle {s['destination']} depuis {', '.join(s['origins'])}, départ du {s['from']:%d/%m/%Y} "
            f"au {s['to']:%d/%m/%Y}, {back} : résultat par e-mail, suivi en cours inchangé.")


@tool("voyage_recherche", "Recherche de vols ponctuelle par flight-price-tracker (workflow GitHub, résultat par e-mail), sans changer "
                          "le suivi en cours. Dates AAAA-MM-JJ ; `stay_days` (ex. \"10,14\") OU `return_date`, l'autre vide ; "
                          "`origins` villes de France ou Barcelone séparées par des virgules ; `alert_below` en €, 0 = aucun.",
      Level.N1, taint_blocked=True, describe=_describe_search, destination=str, depart_from=str, depart_to=str, stay_days=str,
      return_date=str, origins=str, alert_below=int)
def voyage_recherche(destination, depart_from, depart_to, stay_days, return_date, origins, alert_below) -> str:
    s = _spec(destination, depart_from, depart_to, stay_days, return_date, origins, alert_below)
    root = voyages.tracker_dir()
    if not (root / ".git").is_dir():
        raise ValueError("clone git de flight-price-tracker introuvable : aucune recherche lancée")
    if time.monotonic() - _last_search[0] < SEARCH_EVERY_S:
        raise ValueError("une recherche vient d'être lancée : réessaie dans une minute")
    _last_search[0] = time.monotonic()
    fields = {"destination": s["destination"], "origins": ", ".join(s["origins"]), "depart_from": s["from"].isoformat(),
              "depart_to": s["to"].isoformat(), "return_date": s["back"].isoformat() if s["back"] else "",
              "stay_days": ", ".join(map(str, s["stays"])), "alert_below": str(s["alert"] or "")}
    args = [a for k, v in fields.items() for a in ("-f", f"{k}={v}")]  # -f clé=valeur : une valeur ne devient jamais une option
    try:  # dépôt déduit du clone (son `origin`) ; jeton de `gh auth`, jamais lu par JARVIS
        subprocess.run(["gh", "workflow", "run", "search.yml", *args], cwd=root, capture_output=True, check=True,
                       timeout=GH_TIMEOUT_S, env={**os.environ, "GH_PROMPT_DISABLED": "1"},
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        raise ValueError("GitHub injoignable ou `gh` non connecté : aucune recherche lancée") from None
    return f"Recherche {s['destination']} lancée sur GitHub : le résultat arrivera par e-mail d'ici une demi-heure environ."
