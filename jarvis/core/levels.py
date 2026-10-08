"""Niveaux effectifs des outils : le niveau du registre, relevé ou abaissé par le propriétaire, jamais sous un plancher.

Les surcharges sont dans la base (table `levels`), hors du code des outils, et relues à chaque appel : un changement
fait par `python -m jarvis level set` s'applique tout de suite au serveur en marche.
- Relever (N1 -> N2) est libre. Abaisser sous le niveau effectif est une action N3 (authentification forte).
- Les planchers ne descendent jamais : ni le LLM, ni une surcharge, ni une erreur de réglage ne rend `delete_file` automatique.
"""
from .audit import Audit
from .tools import REGISTRY, Level, Tool

# Outils irréversibles ou à fort impact : jamais sous N2. Les autres N2 (presse-papiers, capture) peuvent descendre en N3.
FLOORS = {name: Level.N2 for name in ("power", "delete_file", "move_file", "kill_process", "run_script")}
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


def set_level(name: str, level: int, *, strong_auth: bool) -> str:
    """Enregistre la surcharge et renvoie ce qui a été fait. Lève ValueError (inconnu, sous le plancher) ou PermissionError."""
    tool = REGISTRY.get(name)
    if tool is None or _audit is None or level not in (0, 1, 2, 3):
        raise ValueError("outil ou niveau inconnu")
    before = effective(tool)
    refusal = (ValueError(f"{name} ne peut pas descendre sous N{int(floor(tool))}") if level < floor(tool) else
               PermissionError("abaisser un niveau est une action N3 : authentification forte requise")
               if level < before and not strong_auth else None)
    if refusal:
        _audit.log("levels", name, {"from": int(before), "to": level}, 3, "refusé", str(refusal))
        raise refusal
    with _audit.lock:
        if level == tool.level:  # retour au niveau du registre : pas de surcharge à garder
            _audit.db.execute("DELETE FROM levels WHERE tool = ?", (name,))
        else:
            _audit.db.execute("INSERT OR REPLACE INTO levels VALUES (?, ?)", (name, level))
    _audit.log("levels", name, {"from": int(before), "to": level}, 3, "confirmé", "niveau modifié")
    return f"{name} : N{level}"


def table() -> list[tuple[str, int, int, int]]:
    """(outil, niveau du registre, plancher, niveau effectif), pour l'écran de réglages."""
    return [(t.name, int(t.level), int(floor(t)), int(effective(t))) for t in sorted(REGISTRY.values(), key=lambda t: t.name)]
