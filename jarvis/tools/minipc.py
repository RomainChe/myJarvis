"""Mise à jour du mini-PC (tuile Mini-PC du dashboard)."""
from jarvis.core import minipc
from jarvis.core.tools import Level, tool


@tool("minipc_update", "Installe les mises à jour système du mini-PC (apt) puis le redémarre dans 1 minute si c'est "
                       "nécessaire ; JARVIS et Home Assistant sont coupés quelques minutes.", Level.N2, taint_blocked=True)
def minipc_update() -> dict:
    minipc.start_update()
    return {"minipc": "mise à jour lancée, redémarrage dans 1 min après si nécessaire"}
