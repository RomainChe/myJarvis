"""Garde de permissions : seul point d'entrée pour exécuter un outil.

Le LLM ou le routeur proposent un appel ; c'est ce code qui décide, jamais le prompt.
Échec fermé : la décision est journalisée avant l'exécution ; si le journal échoue, rien ne s'exécute.
"""
from typing import Any, Callable

from .audit import Audit
from .tools import REGISTRY, Level, Tool

# ponytail: masquage par nom de paramètre ; un outil à secret doit nommer son paramètre ainsi.
SECRET_PARAMS = {"password", "token", "secret", "pin", "api_key"}
ERROR_MAX = 200


class Refused(Exception):
    """Le propriétaire a refusé l'action, ou l'authentification forte a échoué."""


def _masked(args) -> Any:
    if not isinstance(args, dict):
        return args
    return {k: "***" if k in SECRET_PARAMS else v for k, v in args.items()}


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
        audit.log(source, str(name), _masked(args), None, "inconnu", None)
        raise ValueError(f"outil inconnu : {name}")
    try:
        tool.check_args(args)
    except ValueError as e:
        audit.log(source, name, _masked(args), tool.level, "invalide", e)
        raise
    # Copie : l'appelant ou le canal de confirmation ne peut plus modifier ce qui sera exécuté.
    # ponytail: copie superficielle, suffisante tant que les paramètres sont des scalaires.
    args = dict(args)
    logged = _masked(args)

    decision = "auto"
    if tool.level >= Level.N2:
        try:
            ok = confirm(tool, dict(args)) is True and (tool.level < Level.N3 or strong_auth(tool, dict(args)) is True)
        except Exception as e:
            audit.log(source, name, logged, tool.level, "refusé", f"confirmation impossible : {type(e).__name__}")
            raise
        decision = "confirmé" if ok else "refusé"
    if decision == "refusé":
        audit.log(source, name, logged, tool.level, decision, None)
        raise Refused(f"{name} refusé")

    audit.log(source, name, logged, tool.level, decision, "en cours")
    try:
        result = tool.run(**args)
    except Exception as e:
        audit.log(source, name, logged, tool.level, decision, f"erreur : {type(e).__name__}: {str(e)[:ERROR_MAX]}")
        raise
    shown = f"<{type(result).__name__}, {len(str(result))} car.>" if tool.private else result
    audit.log(source, name, logged, tool.level, decision, shown)
    return result
