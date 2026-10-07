"""Interface commune des outils et registre global."""
from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType
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
    private: bool = False  # résultat jamais journalisé en clair (presse-papiers, capture, fichier)

    def check_args(self, args: dict) -> None:
        if not isinstance(args, dict):
            raise ValueError("les arguments doivent être un dictionnaire")
        unknown = args.keys() - self.params.keys()
        missing = self.params.keys() - args.keys()
        if unknown or missing:
            raise ValueError(f"paramètres inconnus {sorted(unknown)}, manquants {sorted(missing)}")
        for key, expected in self.params.items():
            value = args[key]
            # bool est une sous-classe d'int : True ne doit pas passer pour un entier.
            if not isinstance(value, expected) or (expected is not bool and isinstance(value, bool)):
                raise ValueError(f"{key} doit être de type {expected.__name__}")


_registry: dict[str, Tool] = {}
REGISTRY = MappingProxyType(_registry)  # lecture seule : un module ne peut pas remplacer un outil


def tool(name: str, description: str, level: Level, *, private: bool = False, **params: type):
    """Décorateur : enregistre une fonction comme outil Jarvis."""
    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        if name in _registry:
            raise ValueError(f"outil déjà enregistré : {name}")
        _registry[name] = Tool(name, description, Level(level), params, fn, private)
        return fn
    return register
