"""Interface commune des outils et registre global."""
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Callable


class Level(IntEnum):
    N0 = 0  # lecture : automatique
    N1 = 1  # courant et réversible : automatique
    N2 = 2  # sensible : confirmation du propriétaire
    N3 = 3  # critique : confirmation + authentification forte


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    level: Level
    params: dict[str, type]
    run: Callable[..., Any]

    def check_args(self, args: dict) -> None:
        unknown = args.keys() - self.params.keys()
        missing = self.params.keys() - args.keys()
        if unknown or missing:
            raise ValueError(f"paramètres inconnus {sorted(unknown)}, manquants {sorted(missing)}")
        for key, expected in self.params.items():
            value = args[key]
            # bool est une sous-classe d'int : True ne doit pas passer pour un entier.
            if not isinstance(value, expected) or (expected is not bool and isinstance(value, bool)):
                raise ValueError(f"{key} doit être de type {expected.__name__}")


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, level: Level, /, **params: type):
    """Décorateur : enregistre une fonction comme outil Jarvis.

    Arguments positionnels seulement : un outil peut avoir un paramètre `name` ou `level`.
    """
    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        if name in REGISTRY:
            raise ValueError(f"outil déjà enregistré : {name}")
        REGISTRY[name] = Tool(name, description, level, params, fn)
        return fn
    return register
