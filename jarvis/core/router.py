"""Routeur d'intentions local, sans LLM.

Le catalogue (jarvis/intents.json) donne, par outil :
- "phrases" : phrases sans paramètre, reconnues de façon approchée (difflib) ;
- "patterns" : regex sur le texte normalisé, {slot} devient un paramètre ;
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


def fold(text: str) -> str:
    """Minuscules et accents retirés : « Écran » -> « ecran »."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """fold + ponctuation retirée + mot d'appel « jarvis » retiré."""
    words = (w.strip(".") for w in re.sub(r"[^\w.\-]+", " ", fold(text)).split())
    return " ".join(w for w in words if w and w != "jarvis")


class Router:
    def __init__(self, path: Path = CATALOGUE):
        self.phrases: dict[str, str] = {}
        self.patterns: list[tuple[re.Pattern, str, dict]] = []
        for intent in json.loads(Path(path).read_text(encoding="utf-8")):
            for phrase in intent.get("phrases", []):
                self.phrases[normalize(phrase)] = intent["tool"]
            for pattern in intent.get("patterns", []):
                regex = re.sub(r"\{(\w+)\}", r"(?P<\1>.+?)", fold(pattern))
                self.patterns.append((re.compile(regex), intent["tool"], intent.get("defaults", {})))

    def route(self, text: str) -> tuple[str, dict] | None:
        """(outil, paramètres) si l'intention est reconnue, sinon None (-> LLM)."""
        text = normalize(text)
        if not text:
            return None
        for regex, tool, defaults in self.patterns:
            match = regex.fullmatch(text)
            if match:
                return tool, {**defaults, **match.groupdict()}
        best = difflib.get_close_matches(text, self.phrases, n=1, cutoff=CUTOFF)
        return (self.phrases[best[0]], {}) if best else None
