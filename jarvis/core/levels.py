"""Niveaux effectifs des outils : le niveau du registre, relevé ou abaissé par le propriétaire, jamais sous un plancher.

Les surcharges sont dans la base (table `levels`), hors du code des outils, et relues à chaque appel : un changement
fait par `python -m jarvis level set` s'applique tout de suite au serveur en marche.
- Relever (N1 -> N2) est libre. Abaisser sous le niveau effectif est une action N3 (authentification forte).
- Les planchers ne descendent jamais : ni le LLM, ni une surcharge, ni une erreur de réglage ne met `delete_file` en N0.
"""
from .audit import Audit
from .tools import REGISTRY, Level, Tool

# Outils irréversibles ou à fort impact : jamais sous N1 (décision du propriétaire, 2026-10-08 ; avant : N2).
# Abaissés en N1, ils restent refusés au LLM après du contenu externe (llm.py compare aussi le niveau du registre).
FLOORS = {name: Level.N1 for name in ("power", "delete_file", "move_file", "kill_process", "run_script")}
SCHEMA = "CREATE TABLE IF NOT EXISTS levels (tool TEXT PRIMARY KEY, level INTEGER NOT NULL CHECK (level BETWEEN 0 AND 3))"

_audit: Audit | None = None


def load(audit: Audit) -> None:
    """Branche les surcharges sur la base du journal (à appeler au démarrage de la CLI et du serveur)."""
    global _audit
    with audit.lock:
        audit.db.execute(SCHEMA)
    _audit = audit


def floor(tool: Tool) -> Level:
    return max(tool.level if tool.level >= Level.N3 else Level.N0, FLOORS.get(tool.name, Level.N0))


def effective(tool: Tool) -> Level:
    level = tool.level
    if _audit is not None:
        with _audit.lock:
            row = _audit.db.execute("SELECT level FROM levels WHERE tool = ?", (tool.name,)).fetchone()
        if row:
            level = Level(row[0])
    return max(level, floor(tool))


def set_level(name: str, level: int, *, strong_auth: bool, source: str = "levels") -> str:
    """Enregistre la surcharge et renvoie ce qui a été fait. Lève ValueError (inconnu, sous le plancher) ou PermissionError."""
    tool = REGISTRY.get(name)
    if tool is None or _audit is None or level not in (0, 1, 2, 3):
        raise ValueError("outil ou niveau inconnu")
    before = effective(tool)
    refusal = (ValueError(f"{name} ne peut pas descendre sous N{int(floor(tool))}") if level < floor(tool) else
               PermissionError("abaisser un niveau est une action N3 : authentification forte requise")
               if level < before and not strong_auth else None)
    if refusal:
        _audit.log(source, name, {"from": int(before), "to": level}, 3, "refusé", str(refusal))
        raise refusal
    with _audit.lock:
        if level == tool.level:  # retour au niveau du registre : pas de surcharge à garder
            _audit.db.execute("DELETE FROM levels WHERE tool = ?", (name,))
        else:
            _audit.db.execute("INSERT OR REPLACE INTO levels VALUES (?, ?)", (name, level))
    _audit.log(source, name, {"from": int(before), "to": level}, 3, "confirmé", "niveau modifié")
    return f"{name} : N{level}"


# Titre et description courte de chaque outil pour l'écran de réglages (la description du registre s'adresse au LLM).
LABELS = {
    "system_status": ("État du PC", "Processeur, mémoire, disque et carte graphique."),
    "list_processes": ("Processus actifs", "Les programmes qui utilisent le plus de mémoire."),
    "search_files": ("Recherche de fichiers", "Cherche des fichiers par leur nom dans le dossier utilisateur."),
    "open_app": ("Ouvrir une application", "Lance une application de la liste autorisée."),
    "close_app": ("Fermer une application", "Ferme proprement une application de la liste autorisée."),
    "run_script": ("Lancer un script", "Exécute un script du dossier scripts."),
    "kill_process": ("Forcer l'arrêt d'un processus", "Termine un programme sans lui laisser le temps d'enregistrer."),
    "set_volume": ("Volume du PC", "Règle le volume principal."),
    "mute": ("Son du PC", "Coupe ou rétablit le son."),
    "media_control": ("Lecture multimédia", "Lecture, pause, arrêt, piste suivante ou précédente."),
    "clipboard_write": ("Écrire dans le presse-papiers", "Remplace le texte copié."),
    "clipboard_read": ("Lire le presse-papiers", "Le texte copié peut contenir des mots de passe."),
    "move_file": ("Déplacer un fichier", "Déplace ou renomme dans le dossier utilisateur."),
    "delete_file": ("Supprimer un fichier", "Envoie à la corbeille, récupérable."),
    "screenshot": ("Capture d'écran", "Enregistre tous les écrans dans Images/Jarvis."),
    "screen_off": ("Éteindre les écrans", "Le PC reste allumé."),
    "lock_session": ("Verrouiller la session", "Verrouille la session Windows."),
    "power": ("Veille, redémarrage, arrêt", "Alimentation du PC, avec délai d'annulation."),
    "power_cancel": ("Annuler l'arrêt", "Annule un redémarrage ou un arrêt en attente."),
    "tv_status": ("État de la TV", "Allumée, appli en cours, volume."),
    "tv_on": ("Allumer la TV", "TV du salon."),
    "tv_off": ("Éteindre la TV", "La barre de son suit."),
    "tv_volume": ("Volume de la TV", "Monte ou baisse le son de la TV du salon."),
    "tv_mute": ("Son de la TV", "Coupe ou rétablit le son de la TV du salon."),
    "tv_key": ("Télécommande de la TV", "Touches de navigation de la télécommande."),
    "tv_open_app": ("Appli sur la TV", "Lance YouTube, Netflix ou une autre appli sur la TV."),
    "scene_cinema": ("Mode cinéma", "Allume la TV et lance l'appli demandée."),
}


def label(tool: Tool) -> dict[str, str]:
    """Titre, description et groupe (PC ou Maison) d'un outil ; un outil sans libellé garde son nom."""
    title, desc = LABELS.get(tool.name, (tool.name, tool.description.split(". ")[0]))
    return {"title": title, "description": desc, "group": "Maison" if ".home." in tool.run.__module__ else "PC"}


def table() -> list[tuple[str, int, int, int]]:
    """(outil, niveau du registre, plancher, niveau effectif), pour l'écran de réglages."""
    return [(t.name, int(t.level), int(floor(t)), int(effective(t))) for t in sorted(REGISTRY.values(), key=lambda t: t.name)]
