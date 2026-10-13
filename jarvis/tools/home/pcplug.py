"""Prise du PC (Tapo P110 via Home Assistant) : arrêt propre du PC, puis coupure de la multiprise.

Le Core tourne sur le PC et s'arrête avec lui : l'attente et la coupure sont confiées à un script HA
(`script.pc_prise_off`, créé dans l'interface HA, docs/INSTALL_SERVEUR_HA.md §10). Ce script ne coupe la prise
que si la puissance mesurée est retombée : si l'arrêt échoue, le PC n'est jamais coupé en marche.
Utile seulement si HA tourne sur le mini-PC : dans la VM du PC, le script serait arrêté avec lui (rien n'est coupé).
"""
from jarvis.core import ha
from jarvis.core.levels import effective
from jarvis.core.tools import REGISTRY, Level, tool
from jarvis.tools.pc import session

PLUG = "switch.prise_pc"
SCRIPT = "script.pc_prise_off"


@tool("pc_plug_on", "Remet sous tension la multiprise du PC et des écrans (prise Tapo) : le PC démarre seul si le BIOS est "
      "réglé sur « Power On » après coupure secteur (docs/INSTALL_SERVEUR_HA.md §10.4).", Level.N1)
def pc_plug_on() -> dict:
    if ha.state(PLUG).get("state") not in ("on", "off"):  # « unavailable » : on le dit au lieu d'un faux « c'est fait »
        raise ha.HAError("prise du PC injoignable")
    ha.call_service("switch", "turn_on", PLUG)
    return {"prise": "on"}


@tool("pc_off_plug","Éteint le PC proprement, attend, puis coupe la multiprise du PC et des écrans (prise Tapo). "
      "Jarvis est coupé jusqu'au rallumage de la prise. Pour éteindre le PC seul, utiliser `power`.", Level.N2)
def pc_off_plug() -> dict:
    # Appelé sans repasser par la garde : si le propriétaire relève `power` au-dessus de cet outil, on refuse.
    if effective(REGISTRY["power"]) > effective(REGISTRY["pc_off_plug"]):
        raise ValueError("`power` dépasse le niveau de cet outil : à exécuter séparément avec confirmation")
    if ha.state(PLUG).get("state") not in ("on", "off"):  # « unavailable » : prise hors ligne, rien n'est lancé
        raise ha.HAError("prise du PC injoignable")
    ha.call_service("script", "turn_on", SCRIPT)  # d'abord le script : il attend, l'arrêt vient ensuite
    session.power("shutdown")
    return {"power": "shutdown", "prise": "coupure planifiée"}
