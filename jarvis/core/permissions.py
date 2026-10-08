"""Garde de permissions : seul point d'entrée pour exécuter un outil.

Le LLM ou le routeur proposent un appel ; c'est ce code qui décide, jamais le prompt.
Échec fermé : la décision est journalisée avant l'exécution ; si le journal échoue, rien ne s'exécute.
"""
import re
from typing import Any, Callable

from .audit import Audit
from .levels import effective
from .tools import REGISTRY, Level, Tool, masked

ERROR_MAX = 200


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
    level = effective(tool)  # niveau du registre, relevé par le propriétaire, jamais sous le plancher
    # Copie avant validation : on valide, fait confirmer et exécute le même objet, que l'appelant ne tient plus.
    if type(args) is dict:
        args = dict(args)
    try:
        tool.check_args(args)
    except ValueError as e:
        audit.log(source, name, masked(args, tool.hidden), level, "invalide", e)
        raise
    logged = masked(args, tool.hidden)

    decision = "auto"
    if level >= Level.N2:
        try:
            ok = confirm(tool, dict(args)) is True and (level < Level.N3 or strong_auth(tool, dict(args)) is True)
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
