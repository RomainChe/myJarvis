"""Routeur d'intentions local, sans LLM.

Le catalogue (jarvis/intents.json) donne, par outil :
- "phrases" : phrases sans paramètre, reconnues de façon approchée (difflib) ;
- "patterns" : regex sur le texte, {slot} devient un paramètre ;
- "defaults" : paramètres par défaut, complétés par les slots.
Le routeur PROPOSE un appel ; la garde de permissions (permissions.execute) décide.
"""
import difflib
import json
import re
import unicodedata
from pathlib import Path

CATALOGUE = Path(__file__).parents[1] / "intents.json"
CUTOFF = 0.8  # similarité minimale pour une phrase approchée
# Mots sans contenu, retirés des deux côtés avant la comparaison approchée : « quel est l'état du PC » -> « etat pc ».
FILLERS = set("quel quelle quels quelles est sont c quoi l le la les du de des d un une mon ma mes "
              "moi me donne dis montre peux tu stp svp".split())
# Un verbe d'action absent de la phrase reconnue annule la correspondance : « tue les processus » n'est pas une lecture.
ACTION_VERBS = set("tue tuer arrete arreter stoppe stop ferme fermer supprime supprimer efface effacer "
                   "eteins eteindre coupe couper lance lancer ouvre ouvrir installe redemarre kill".split())


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


class Router:
    def __init__(self, path: Path = CATALOGUE):
        self.phrases: dict[str, str] = {}
        self.patterns: list[tuple[re.Pattern, str, dict]] = []
        for intent in json.loads(Path(path).read_text(encoding="utf-8")):
            for phrase in intent.get("phrases", []):
                self.phrases[_core(normalize(phrase))] = intent["tool"]
            for pattern in intent.get("patterns", []):
                regex = re.sub(r"\{(\w+)\}", r"(?P<\1>.+?)", fold(pattern))
                self.patterns.append((re.compile(regex, re.IGNORECASE), intent["tool"], intent.get("defaults", {})))

    def route(self, text: str) -> tuple[str, dict] | None:
        """(outil, paramètres) si l'intention est reconnue, sinon None (-> LLM)."""
        if not normalize(text):
            return None
        light = _light(text)
        for regex, tool, defaults in self.patterns:
            match = regex.fullmatch(light)
            if match:
                return tool, {**defaults, **match.groupdict()}
        core = _core(normalize(text))
        best = difflib.get_close_matches(core, self.phrases, n=1, cutoff=CUTOFF)
        if not best or (set(core.split()) & ACTION_VERBS) - set(best[0].split()):
            return None
        return self.phrases[best[0]], {}
