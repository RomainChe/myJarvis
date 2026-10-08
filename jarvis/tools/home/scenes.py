"""Scènes : enchaînent des outils et vérifient l'état réel ensuite (jamais « c'est fait » sans confirmation).

Mode cinéma = TV allumée (la barre de son suit en HDMI-CEC) + appli demandée. Les volets et la lumière du salon
(DOMOTIQUE_PLAN §4) ne sont pas encore équipés (Shelly) : la scène les signale comme non traités.
Écart au plan (script HA `script.jarvis_*`) : l'utilisateur `jarvis` n'est pas administrateur, il ne peut pas créer de
script HA. La scène vit dans Jarvis ; à migrer vers un script HA quand les volets seront posés.
"""
import time

from jarvis.core import ha
from jarvis.core.tools import REGISTRY, Level, tool
from jarvis.tools.home import tv

_sleep, _now = time.sleep, time.monotonic  # remplacés dans les tests
WAIT_S = 15  # échéance (temps réel) par étape : la scène bloque l'appelant ~1 min au pire (HA lent : +5 s par lecture)
NOT_EQUIPPED = ["volets du salon", "lumière du salon", "volume préréglé"]


def _wait(ok, result: dict) -> bool:
    deadline = _now() + WAIT_S
    while True:
        try:
            if ok(tv.tv_status()):
                return True
        except ha.HAError as e:  # HA tombe après l'action : « non confirmée », cause gardée dans le résultat
            result["erreur"] = str(e)  # message fixe de ha.py, sans secret (un 403 ne passe pas pour une TV lente)
        if _now() >= deadline:
            return False
        _sleep(1)


@tool("scene_cinema", f"Mode cinéma : allume la TV du salon et lance l'appli demandée ({', '.join(tv.APPS)} ; "
      "chaîne vide = aucune appli). Vérifie l'état réel ensuite.", Level.N1, taint_blocked=True, app=str)
def scene_cinema(app: str) -> dict:
    name = tv.app_key(app)
    if name and name not in tv.APPS:  # refusé avant d'allumer quoi que ce soit
        raise ValueError(f"appli inconnue (attendu : {', '.join(tv.APPS)} ou vide)")
    # Les sous-outils sont appelés sans repasser par la garde : si le propriétaire en relève un au-dessus de N1,
    # toute la scène est refusée avant la première action (revue Sécurité, constat 1).
    needed = ["tv_on"] + (["tv_open_app"] if name else [])
    if over := [t for t in needed if REGISTRY[t].level > Level.N1]:
        raise ValueError(f"scène refusée : {', '.join(over)} dépasse N1, à exécuter séparément avec confirmation")
    result = {"tv": "allumée" if tv.tv_status()["state"] == "on" else None, "app": None, "non_traité": list(NOT_EQUIPPED)}
    if result["tv"] is None:
        tv.tv_on()
        result["tv"] = "allumée" if _wait(lambda s: s["state"] == "on", result) else "non confirmée"
    if name and result["tv"] == "allumée":
        try:
            tv.tv_open_app(name)
            result["app"] = name if _wait(lambda s: s["app"] == name, result) else "non confirmée"
        except ha.HAError as e:  # la TV est déjà allumée : on le dit au lieu de tout effacer par une exception
            result["app"], result["erreur"] = "non confirmée", str(e)
    return result
