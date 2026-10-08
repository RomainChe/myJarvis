"""Scènes : enchaînent des outils et vérifient l'état réel ensuite (jamais « c'est fait » sans confirmation).

Mode cinéma = TV allumée (la barre de son suit en HDMI-CEC) + appli demandée. Les volets et la lumière du salon
(DOMOTIQUE_PLAN §4) ne sont pas encore équipés (Shelly) : la scène les signale comme non traités.
Écart au plan (script HA `script.jarvis_*`) : l'utilisateur `jarvis` n'est pas administrateur, il ne peut pas créer de
script HA. La scène vit dans Jarvis ; à migrer vers un script HA quand les volets seront posés.
"""
import time

from jarvis.core.tools import Level, tool
from jarvis.tools.home import tv

_sleep = time.sleep  # remplacé dans les tests
WAIT_S = 15  # délai maximal pour que la TV sorte de veille ou que l'appli s'affiche
NOT_EQUIPPED = ["volets du salon", "lumière du salon", "volume préréglé"]


def _wait(ok) -> bool:
    for _ in range(WAIT_S):
        if ok(tv.tv_status()):
            return True
        _sleep(1)
    return False


@tool("scene_cinema", f"Mode cinéma : allume la TV du salon et lance l'appli demandée ({', '.join(tv.APPS)} ; "
      "chaîne vide = aucune appli). Vérifie l'état réel ensuite.", Level.N1, taint_blocked=True, app=str)
def scene_cinema(app: str) -> dict:
    name = app.casefold().strip()
    if name and name not in tv.APPS:  # refusé avant d'allumer quoi que ce soit
        raise ValueError(f"appli inconnue (attendu : {', '.join(tv.APPS)} ou vide)")
    result = {"tv": "allumée" if tv.tv_status()["state"] == "on" else None, "app": None, "non_traité": NOT_EQUIPPED}
    if result["tv"] is None:
        tv.tv_on()
        result["tv"] = "allumée" if _wait(lambda s: s["state"] == "on") else "non confirmée"
    if name and result["tv"] == "allumée":
        tv.tv_open_app(name)
        result["app"] = name if _wait(lambda s: s["app"] == name) else "non confirmée"
    return result
