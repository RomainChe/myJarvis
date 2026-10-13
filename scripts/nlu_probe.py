"""Sonde de compréhension : vrai LLM (Ollama), outils SIMULÉS (aucun effet sur le PC ni la maison).

Usage : python scripts/nlu_probe.py [--tools]   (--tools : liste les outils exposés au LLM)
Chaque phrase est comparée aux outils attendus (ensemble) ; le résultat sert à décider quoi améliorer.
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))
import jarvis.tools.assist, jarvis.tools.dev, jarvis.tools.home, jarvis.tools.mail, jarvis.tools.social, jarvis.tools.pc  # noqa: E401,F401
from jarvis.core import llm
from jarvis.core.router import Router
from jarvis.core.tools import REGISTRY

# (phrase, outils attendus) ; None = aucun outil (réponse parlée ou question)
CASES = [
    ("allume la TV et lance Spotify", {"scene_cinema"}),
    ("mets la télé et ouvre Netflix dessus", {"scene_cinema"}),
    ("éteins la télé et mets l'écran du PC en veille", {"tv_off", "screen_off"}),
    ("monte le son de la TV", {"tv_volume"}),
    ("coupe le son du PC", {"mute"}),
    ("je veux regarder YouTube sur la grande télé", {"scene_cinema"}),
    ("il fait quoi dehors ?", {"weather_now"}),
    ("est-ce qu'il va pleuvoir, y a un orage ?", {"weather_now"}),
    ("il y a du vent aujourd'hui ?", {"weather_now"}),
    ("c'est quoi l'état du PC", None),
    ("ouvre Spotify sur mon ordi", {"open_app"}),
    ("mets le mode cinéma avec Netflix", {"scene_cinema"}),
    ("je suis en train d'écrire une fonction de rappels pour toi, commence à la coder", {"claude_code"}),
    ("raconte-moi une blague", set()),
]


def main() -> None:
    if "--tools" in sys.argv:
        print(", ".join(sorted(t.name for t in REGISTRY.values() if not t.owner_only)))
        return
    router, calls = Router(), []

    def fake(name, args, **_):
        calls.append(name)
        return {"tv_status": {"state": "on"}}.get(name, "ok (simulé)")

    audit = mock.Mock()
    ok = 0
    with mock.patch.object(llm, "execute", fake):
        for text, want in CASES:
            calls.clear()
            routed = router.route(text)
            if routed:
                got, via, answer = {routed[0]}, "routeur", ""
            else:
                answer = llm.ask(text, audit=audit, confirm=lambda *a: True, strong_auth=lambda *a: True,
                                 gaming=lambda: False)
                got, via = set(calls), "LLM"
            good = want is None or got == want
            ok += good
            print(f"{'OK ' if good else 'KO '} [{via}] {text!r}\n      attendu={want} obtenu={sorted(got)} | {answer[:80]}")
    print(f"\n{ok}/{len(CASES)}")


main()
