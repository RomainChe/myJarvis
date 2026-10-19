"""Prise du PC (Tapo P110 via Home Assistant) : arrêt propre du PC par l'agent, puis coupure de la multiprise.

Le Core tourne sur le mini-PC (docs/MIGRATION_CORE_MINIPC.md, lot 6) : il survit à l'arrêt du PC et orchestre lui-même
l'attente. La prise n'est coupée que si la puissance mesurée est retombée, deux fois à 30 s d'écart : si l'arrêt échoue
ou est annulé, le PC n'est jamais coupé en marche. Sur un Core hébergé par le PC, l'outil est refusé (il s'arrêterait
avec le PC avant la coupure).
"""
import math
import os
import threading
import time

from jarvis.core import ha
from jarvis.core.audit import Audit
from jarvis.core.host import HAS_PC_TOOLS
from jarvis.core.levels import effective
from jarvis.core.tools import REGISTRY, Level, tool

PLUG = "switch.prise_pc"
SENSOR = "sensor.prise_pc_consommation_actuelle"
WAIT_S, POLL_S, SETTLE_S = 5 * 60, 5, 30
_audit: Audit | None = None
_busy = threading.Lock()  # un seul cycle d'arrêt à la fois


def load(audit: Audit) -> None:
    """Journal des coupures différées (démarrage de la CLI et du serveur)."""
    global _audit
    _audit = audit


def limit_w() -> float:
    """Seuil « PC éteint » (W) : JARVIS_PC_IDLE_W, 5 à 100, défaut 10 (mesure de veille : INSTALL_SERVEUR_HA §10.2)."""
    try:
        return min(max(float(os.environ.get("JARVIS_PC_IDLE_W") or 10), 5.0), 100.0)
    except ValueError:
        return 10.0


def watts() -> float:
    """Puissance de la prise ; illisible = infinie (le PC est supposé allumé, rien n'est coupé)."""
    try:
        w = float(ha.state(SENSOR).get("state"))
    except (ha.HAError, ValueError, TypeError):
        return math.inf
    return w if math.isfinite(w) else math.inf


def cut_when_off(sleep=time.sleep, now=time.monotonic) -> str:
    """Attend la chute de puissance (5 min au plus), laisse 30 s au disque, revérifie, coupe. Renvoie l'issue."""
    limit, deadline = limit_w(), now() + WAIT_S
    while watts() >= limit:
        if now() >= deadline:
            return "prise conservée : le PC ne s'est pas éteint (délai de 5 min)"
        sleep(POLL_S)
    sleep(SETTLE_S)
    if watts() >= limit:
        return "prise conservée : la puissance est remontée"
    ha.call_service("switch", "turn_off", PLUG)
    return "prise coupée"


def _cycle() -> None:
    try:
        with _busy:
            try:
                outcome = cut_when_off()
            except Exception as e:  # noqa: BLE001 (HA injoignable : le PC reste alimenté, le journal garde la trace)
                outcome = f"prise conservée : {type(e).__name__}"
            if _audit is not None:
                _audit.log("pcplug", "pc_off_plug", {}, 2, "auto", outcome)
    except Exception:  # noqa: BLE001 (thread de fond : jamais de trace vers une sortie absente)
        pass


@tool("pc_plug_on", "Remet sous tension la multiprise du PC et des écrans ; le PC démarre seul.", Level.N1)
def pc_plug_on() -> dict:
    if ha.state(PLUG).get("state") not in ("on", "off"):  # « unavailable » : on le dit au lieu d'un faux « c'est fait »
        raise ha.HAError("prise du PC injoignable")
    ha.call_service("switch", "turn_on", PLUG)
    return {"prise": "on"}


@tool("pc_off_plug", "Éteint le PC proprement puis coupe sa multiprise (PC et écrans). Pour éteindre le PC seul : "
                     "`power`.", Level.N2)
def pc_off_plug() -> dict:
    if HAS_PC_TOOLS:  # ce Core s'arrêterait avec le PC : la prise ne serait jamais coupée
        raise RuntimeError("arrêt avec coupure de prise indisponible : ce Core tourne sur le PC (utiliser `power`)")
    # Appelé sans repasser par la garde : si le propriétaire relève `power` au-dessus de cet outil, on refuse.
    if effective(REGISTRY["power"]) > effective(REGISTRY["pc_off_plug"]):
        raise ValueError("`power` dépasse le niveau de cet outil : à exécuter séparément avec confirmation")
    if ha.state(PLUG).get("state") not in ("on", "off"):  # « unavailable » : prise hors ligne, rien n'est lancé
        raise ha.HAError("prise du PC injoignable")
    if watts() == math.inf:  # sans mesure, on ne pourrait jamais vérifier que le PC est éteint
        raise ha.HAError("mesure de puissance de la prise illisible")
    if _busy.locked():
        raise RuntimeError("un arrêt avec coupure de prise est déjà en cours")
    REGISTRY["power"].run(action="shutdown")  # échec (PC injoignable, agent refusé) : rien n'est coupé
    threading.Thread(target=_cycle, daemon=True).start()
    return {"power": "shutdown", "prise": "coupure planifiée"}
