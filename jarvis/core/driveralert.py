"""Alerte push quand un pilote important (affichage/GPU, réseau, système/chipset) a une mise à jour, une seule fois par version.
Lecture seule (N0) : le relevé vient de `pc_drivers`, le push est générique (aucun nom de pilote).
"""
import json
from pathlib import Path

ALERT_STATE = Path.home() / ".jarvis" / "drivers-alert.json"
CATEGORIES = ("DISPLAY", "NET", "SYSTEM")
KEEP = 100  # clés mémorisées au plus


def check(snap: dict, notify, state: Path = ALERT_STATE) -> int:
    """Appelle `notify()` une fois s'il y a des pilotes importants jamais signalés ; renvoie leur nombre."""
    due = {f"{d['id']}@{d['latest']}" for d in snap.get("drivers", [])
           if d["newer"] and not d["ignored"] and d["status"] in ("critical", "moderate") and d["category"] in CATEGORIES}
    try:
        seen = json.loads(Path(state).read_text(encoding="utf-8")).get("seen")
    except (OSError, ValueError, AttributeError):  # fichier absent, corrompu ou JSON qui n'est pas un objet
        seen = None
    seen = [k for k in seen if isinstance(k, str)] if isinstance(seen, list) else []
    new = due - set(seen)
    if not new:
        return 0
    notify()
    Path(state).parent.mkdir(parents=True, exist_ok=True)
    Path(state).write_text(json.dumps({"seen": (seen + sorted(new))[-KEEP:]}), encoding="utf-8")
    return len(new)
