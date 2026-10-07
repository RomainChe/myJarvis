"""Garde de permissions : seul point d'entrée pour exécuter un outil.

Le LLM ou le routeur proposent un appel ; c'est ce code qui décide, jamais le prompt.
"""
from typing import Any, Callable

from .audit import Audit
from .tools import REGISTRY, Level, Tool


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
    tool = REGISTRY.get(name)
    if tool is None:
        audit.log(source, name, args, None, "inconnu", None)
        raise ValueError(f"outil inconnu : {name}")
    try:
        tool.check_args(args)
    except ValueError as e:
        audit.log(source, name, args, tool.level, "invalide", e)
        raise

    decision = "auto"
    if tool.level >= Level.N2:
        ok = confirm(tool, args) and (tool.level < Level.N3 or strong_auth(tool, args))
        decision = "confirmé" if ok else "refusé"
    if decision == "refusé":
        audit.log(source, name, args, tool.level, decision, None)
        raise Refused(f"{name} refusé")

    try:
        result = tool.run(**args)
    except Exception as e:
        audit.log(source, name, args, tool.level, decision, f"erreur : {e}")
        raise
    audit.log(source, name, args, tool.level, decision, result)
    return result
