"""Garde de permissions : seul point d'entrée pour exécuter un outil.

Le LLM ou le routeur proposent un appel ; c'est ce code qui décide, jamais le prompt.
Échec fermé : la décision est journalisée avant l'exécution ; si le journal échoue, rien ne s'exécute.
"""
import re
import time
from collections import deque
from typing import Any, Callable

from .audit import Audit
from .levels import effective
from .tools import REGISTRY, Level, Tool, masked

ERROR_MAX = 200
_OWNER_SOURCE = re.compile(r"pwa:\d+")
# D2 (Phase 5, étape 1) : ces N2 exigent la clé d'accès quand ils sont demandés depuis la PWA, car un token volé ne doit
# pas suffire à les confirmer. Le terminal local (source « cli ») garde la confirmation simple.
STRONG_N2 = frozenset({"run_script", "delete_file", "kill_process", "power", "clipboard_read", "screenshot", "mail_recent"})
# Le micro entend aussi la TV ou un visiteur : pas d'écriture durable à la voix (revue Sécurité 2026-10-14, constat 7).
VOICE_BLOCKED = frozenset({"memory_set", "memory_forget"})
# Minuteurs et rappels à la voix : au plus VOICE_RATE par heure, tous confondus (constat 2).
VOICE_RATE_TOOLS = frozenset({"timer_set", "reminder_set"})
VOICE_RATE = 5
_voice_hits: deque[float] = deque()


DATA_MAX = 2000
_DATA_TAG = re.compile(r"<\s*/?\s*data\b", re.IGNORECASE)


def as_data(result: Any) -> str:
    """Résultat d'outil présenté au LLM : une donnée tronquée, jamais un ordre (constat 7).

    Les balises `data` du contenu sont neutralisées : il ne peut pas fermer l'encadrement.
    """
    text = _DATA_TAG.sub("(balise)", str(result))
    if len(text) > DATA_MAX:
        text = text[:DATA_MAX] + f"… [tronqué, {len(text)} car.]"
    return f"<data>{text}</data>"


class Refused(Exception):
    """Le propriétaire a refusé l'action, ou l'authentification forte a échoué."""


def execute(
    name: str,
    args: dict,
    *,
    source: str,
    audit: Audit,
    confirm: Callable[[Tool, dict], bool],
    strong_auth: Callable[[Tool, dict], bool],
) -> Any:
    tool = REGISTRY.get(name) if isinstance(name, str) else None
    if tool is None:
        audit.log(source, str(name), masked(args), None, "inconnu", None)
        raise ValueError(f"outil inconnu : {name}")
    # Garde (a) de l'outil Claude Code : liste blanche des sources tapées par le propriétaire (ni LLM, ni voix, ni automatisme).
    if tool.owner_only and not (source == "cli" or _OWNER_SOURCE.fullmatch(source)):
        audit.log(source, name, masked(args, tool.hidden), None, "refusé", "réservé aux demandes directes du propriétaire")
        raise Refused(f"{name} refusé : à taper dans l'application ou le terminal")
    from_voice = source.split("/")[0] == "voix"
    if from_voice and name in VOICE_BLOCKED:
        audit.log(source, name, masked(args, tool.hidden), None, "refusé", "écriture de la mémoire interdite à la voix")
        raise Refused(f"{name} refusé : à demander dans l'application ou le terminal")
    if from_voice and name in VOICE_RATE_TOOLS:
        now = time.monotonic()
        while _voice_hits and now - _voice_hits[0] > 3600:
            _voice_hits.popleft()
        if len(_voice_hits) >= VOICE_RATE:
            audit.log(source, name, masked(args, tool.hidden), None, "refusé", f"plus de {VOICE_RATE} par heure à la voix")
            raise Refused(f"{name} refusé : {VOICE_RATE} par heure à la voix")
        _voice_hits.append(now)
    level = effective(tool)  # niveau du registre, relevé par le propriétaire, jamais sous le plancher
    if from_voice:  # le micro entend aussi la TV ou un visiteur : un abaissement ne vaut pas à la voix
        level = max(level, tool.level)
    # Copie avant validation : on valide, fait confirmer et exécute le même objet, que l'appelant ne tient plus.
    if type(args) is dict:
        args = dict(args)
    try:
        tool.check_args(args)
    except ValueError as e:
        audit.log(source, name, masked(args, tool.hidden), level, "invalide", e)
        raise
    logged = masked(args, tool.hidden)

    # Outil du propriétaire demandé depuis la PWA : clé d'accès exigée comme en N3, quel que soit son niveau (le terminal local, non).
    strong_needed = level >= Level.N3 or (tool.owner_only and source != "cli")
    if name in STRONG_N2 and level >= Level.N2 and source.startswith("pwa:"):
        strong_needed = True
    decision = "auto"
    if level >= Level.N2 or strong_needed:
        try:
            ok = confirm(tool, dict(args)) is True and (not strong_needed or strong_auth(tool, dict(args)) is True)
        except BaseException as e:  # Ctrl+C ou canal coupé : refus journalisé, puis l'exception remonte
            audit.log(source, name, logged, level, "refusé", f"confirmation impossible : {type(e).__name__}")
            raise
        decision = "confirmé" if ok else "refusé"
    if decision == "refusé":
        audit.log(source, name, logged, level, decision, None)
        raise Refused(f"{name} refusé")

    start = audit.log(source, name, logged, level, decision, "en cours")
    try:
        result = tool.run(**args)
    except Exception as e:
        # Le message d'un outil privé peut contenir ses données (octets du fichier, URL avec token).
        detail = "" if tool.private else f": {str(e)[:ERROR_MAX]}"
        audit.log(source, name, logged, level, decision, f"erreur : {type(e).__name__}{detail}", ref=start)
        raise
    shown = f"<{type(result).__name__}, {len(str(result))} car.>" if tool.private else result
    audit.log(source, name, logged, level, decision, shown, ref=start)
    return result
