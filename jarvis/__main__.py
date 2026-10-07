"""Interface texte minimale.

    python -m jarvis "<phrase>"
    python -m jarvis run <outil> [clé=valeur ...]
    python -m jarvis audit [n]
"""
import json
import os
import sys
from pathlib import Path

from jarvis.core.audit import Audit
from jarvis.core.permissions import Refused, execute
from jarvis.core.router import Router
from jarvis.core.tools import Tool, masked
import jarvis.tools.pc  # noqa: F401  (enregistre les outils PC)

DB_PATH = Path(os.environ.get("JARVIS_DB") or Path.home() / ".jarvis" / "jarvis.db")


def parse_args(pairs: list[str]) -> dict:
    args = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep:
            raise ValueError(f"argument attendu sous la forme clé=valeur : {pair}")
        try:
            args[key] = json.loads(raw)  # 30 -> int, true -> bool
        except json.JSONDecodeError:
            args[key] = raw
    return args


def confirm(tool: Tool, args: dict) -> bool:
    if not sys.stdin.isatty():  # `echo o | jarvis run ...` : pas d'humain devant l'écran
        print("Confirmation refusée : la CLI exige un terminal interactif.")
        return False
    return input(f"Confirmer {tool.name} {masked(args)} ? [o/N] ").strip().lower() == "o"


def no_strong_auth(tool: Tool, args: dict) -> bool:
    print("Action N3 refusée : la CLI n'a pas d'authentification forte (WebAuthn en Phase 3).")
    return False


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    if str(DB_PATH) == ":memory:" or str(DB_PATH).startswith("file:"):
        print("JARVIS_DB doit être un chemin de fichier : le journal d'audit doit persister.")
        return 2
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    audit = Audit(str(DB_PATH))
    if argv[0] == "audit":
        for row in audit.last(int(argv[1]) if len(argv) > 1 else 20):
            print(" | ".join("" if v is None else str(v) for v in row))
        return 0
    if argv[0] == "run":
        if len(argv) < 2:
            print(__doc__)
            return 2
        name, args = argv[1], argv[2:]
    else:
        routed = Router().route(" ".join(argv))
        if routed is None:
            print("Je n'ai pas compris. Le LLM local prendra le relais à l'étape 5 de la Phase 1.")
            return 1
        name, args = routed
    print(f"journal : {DB_PATH}", file=sys.stderr)
    try:
        print(execute(name, parse_args(args) if isinstance(args, list) else args, source="cli", audit=audit,
                      confirm=confirm, strong_auth=no_strong_auth))
    except (ValueError, Refused) as e:
        print(e)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nAction annulée.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
