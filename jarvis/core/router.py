"""Routeur d'intentions local, sans LLM.

Le catalogue (jarvis/intents.json) donne, par outil :
- "phrases" : phrases sans paramètre, reconnues de façon approchée (difflib) ;
- "patterns" : regex sur le texte, {slot} devient un paramètre ;
- "defaults" : paramètres par défaut, complétés par les slots ;
- "choices" : valeurs permises par slot (comparées sans casse ni accents) ; hors liste -> None (LLM).
Le routeur PROPOSE un appel ; la garde de permissions (permissions.execute) décide.
"""
import difflib
import json
import re
import unicodedata
from pathlib import Path

from .tools import REGISTRY

CATALOGUE = Path(__file__).parents[1] / "intents.json"
CUTOFF = 0.8  # similarité minimale pour une phrase approchée
TEXT_MAX = 500  # au-delà, pas de routage : les regex à plusieurs .+? coûtent cher sur un long texte
SLOT_MAX = 100
INTENT_KEYS = {"tool", "phrases", "patterns", "defaults", "choices"}
# Mots sans contenu, retirés des deux côtés avant la comparaison approchée : « quel est l'état du PC » -> « etat pc ».
FILLERS = set("quel quelle quels quelles est sont c quoi l le la les du de des d un une mon ma mes "
              "moi me donne dis montre peux tu stp svp".split())
# Un verbe d'action absent de la phrase reconnue annule la correspondance : « tue les processus » n'est pas une lecture.
ACTION_VERBS = set("tue tuer arrete arreter stoppe stop ferme fermer supprime supprimer efface effacer "
                   "eteins eteindre coupe couper lance lancer ouvre ouvrir installe redemarre kill quitte quitter "
                   "vide vider termine terminer detruis detruire nettoie nettoyer".split())


def fold(text: str) -> str:
    """Minuscules et accents retirés : « Écran » -> « ecran »."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """fold + ponctuation retirée + mot d'appel « jarvis » retiré."""
    words = (w.strip(".") for w in re.sub(r"[^\w.\-]+", " ", fold(text)).split())
    return " ".join(w for w in words if w and w != "jarvis")


def _core(text: str) -> str:
    return " ".join(w for w in text.split() if w not in FILLERS)


def _light(text: str) -> str:
    """Texte presque brut pour les slots : seuls le mot d'appel en tête et la ponctuation finale sont retirés."""
    text = re.sub(r"^\s*jarvis\b[\s,!.:]*", "", text.strip(), flags=re.IGNORECASE)
    return " ".join(text.rstrip(" ?!.").split())


def _check(intent: dict) -> None:
    """Le catalogue ne vise qu'un outil enregistré et ses paramètres ; il ne porte pas de niveau."""
    if unknown := intent.keys() - INTENT_KEYS:
        raise ValueError(f"clé inconnue dans le catalogue : {sorted(unknown)}")
    tool = REGISTRY.get(intent.get("tool"))
    if tool is None:
        raise ValueError(f"outil inconnu dans le catalogue : {intent.get('tool')}")
    slots = {s for p in intent.get("patterns", []) for s in re.findall(r"\{(\w+)\}", p)}
    if extra := (slots | intent.get("defaults", {}).keys() | intent.get("choices", {}).keys()) - tool.params.keys():
        raise ValueError(f"{tool.name} n'a pas de paramètre {sorted(extra)}")


class Router:
    def __init__(self, path: Path = CATALOGUE):
        self.phrases: dict[str, str] = {}
        self.patterns: list[tuple[re.Pattern, str, dict, dict]] = []
        for intent in json.loads(Path(path).read_text(encoding="utf-8")):
            _check(intent)
            for phrase in intent.get("phrases", []):
                self.phrases[_core(normalize(phrase))] = intent["tool"]
            for pattern in intent.get("patterns", []):
                # casefold seul : le motif garde ses accents (« [eé] »), comme le texte des slots.
                regex = re.sub(r"\{(\w+)\}", r"(?P<\1>.+?)", pattern.casefold())
                choices = {k: {fold(v) for v in vs} for k, vs in intent.get("choices", {}).items()}
                self.patterns.append((re.compile(regex, re.IGNORECASE), intent["tool"], intent.get("defaults", {}),
                                      choices))

    def route(self, text: str) -> tuple[str, dict] | None:
        """(outil, paramètres) si l'intention est reconnue, sinon None (-> LLM)."""
        if len(text) > TEXT_MAX or not normalize(text):
            return None
        light = _light(text)
        for regex, tool, defaults, choices in self.patterns:
            match = regex.fullmatch(light)
            if match:
                slots = {k: v.strip(" ,;:") for k, v in match.groupdict().items()}
                limit = TEXT_MAX if REGISTRY[tool].owner_only else SLOT_MAX  # une demande de code tient en une longue phrase
                if any(not v or len(v) > limit for v in slots.values()):
                    return None
                if any(fold(slots[k]) not in allowed for k, allowed in choices.items() if k in slots):
                    return None  # valeur hors liste blanche : au LLM, pas au motif suivant
                params = REGISTRY[tool].params
                for k in slots:  # un slot est du texte : un paramètre entier n'accepte que des chiffres (la borne est celle de l'outil)
                    if params[k] is int:
                        if not slots[k].isascii() or not slots[k].isdigit():
                            return None
                        slots[k] = int(slots[k])
                return tool, {**defaults, **slots}
        core = _core(normalize(text))
        best = difflib.get_close_matches(core, self.phrases, n=1, cutoff=CUTOFF)
        if not best or (set(core.split()) & ACTION_VERBS) - set(best[0].split()):
            return None
        return self.phrases[best[0]], {}
