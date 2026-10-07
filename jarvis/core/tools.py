"""Interface commune des outils et registre global."""
import math
import re
from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType
from typing import Any, Callable

# Masquage par nom : tout nom qui ressemble à un secret doit figurer exactement ici (vérifié à l'enregistrement).
SECRET_PARAMS = {"password", "token", "secret", "pin", "api_key"}
SECRET_LIKE = re.compile(r"pass|token|secret|pin|key", re.IGNORECASE)
PARAM_TYPES = (str, int, float, bool)  # immuables : la copie superficielle des arguments suffit
STR_MAX = 1000  # un appel valide est toujours journalisé en entier


class Level(IntEnum):
    N0 = 0  # lecture : automatique
    N1 = 1  # courant et réversible : automatique
    N2 = 2  # sensible : confirmation du propriétaire
    N3 = 3  # critique : confirmation + authentification forte


def masked(args, hidden: tuple[str, ...] = ()) -> Any:
    """Arguments tels que journalisés : secrets en `***`, paramètres `hidden` réduits à leur longueur."""
    if type(args) is not dict:
        return args
    return {k: ("***" if k in SECRET_PARAMS else f"<{len(v)} car.>" if k in hidden and isinstance(v, str)
                else "***" if k in hidden else v) for k, v in args.items()}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    level: Level
    params: dict[str, type]
    run: Callable[..., Any]
    private: bool = False  # résultat jamais journalisé en clair (presse-papiers, capture, fichier)
    external: bool = False  # le résultat contient du contenu tiers (noms de fichiers, pages, emails)
    hidden: tuple[str, ...] = ()  # paramètres dont la valeur n'est jamais journalisée (texte dicté, mot de passe)
    taint_blocked: bool = False  # refusé au LLM après du contenu externe, comme N2/N3 (N1 qui écrit chez l'utilisateur)

    def check_args(self, args: dict) -> None:
        if type(args) is not dict:  # une sous-classe pourrait mentir sur keys() ou __getitem__
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
            if isinstance(value, str) and len(value) > STR_MAX:
                raise ValueError(f"{key} dépasse {STR_MAX} caractères")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{key} doit être un nombre fini")


_registry: dict[str, Tool] = {}
REGISTRY = MappingProxyType(_registry)  # lecture seule : un module ne peut pas remplacer un outil


def tool(name: str, description: str, level: Level, /, *, private: bool = False, external: bool = False,
         hidden: tuple[str, ...] = (), taint_blocked: bool = False, **params: type):
    """Décorateur : enregistre une fonction comme outil Jarvis.

    Arguments positionnels seulement : un outil peut avoir un paramètre `name` ou `level`.
    """
    for key, typ in params.items():
        if typ not in PARAM_TYPES:
            raise ValueError(f"{name}.{key} : type {typ} non autorisé (str, int, float, bool)")
        if SECRET_LIKE.search(key) and key not in SECRET_PARAMS:
            raise ValueError(f"{name}.{key} ressemble à un secret : le nommer parmi {sorted(SECRET_PARAMS)}")

    if unknown := set(hidden) - params.keys():
        raise ValueError(f"{name} : paramètres hidden inconnus {sorted(unknown)}")

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        if name in _registry:
            raise ValueError(f"outil déjà enregistré : {name}")
        _registry[name] = Tool(name, description, Level(level), params, fn, private, external, hidden, taint_blocked)
        return fn
    return register
