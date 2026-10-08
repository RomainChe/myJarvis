"""Interface texte minimale.

    python -m jarvis "<phrase>"
    python -m jarvis run <outil> [clé=valeur ...]
    python -m jarvis audit [n]
    python -m jarvis secret set|check <nom>
    python -m jarvis ha check
    python -m jarvis device add | list | revoke <id>   (terminal interactif)
    python -m jarvis level list | set <outil> <0-3>    (relever est libre ; abaisser exige N3)
    python -m jarvis serve                             (127.0.0.1 seulement)
"""
import getpass
import json
import os
import sys
from pathlib import Path

import keyring.errors
import segno

from jarvis.core import ha, levels
from jarvis.core.audit import Audit
from jarvis.core.devices import CODE_TTL_S, Devices
from jarvis.core.llm import LLMUnavailable, ask
from jarvis.core.permissions import Refused, execute
from jarvis.core.router import Router
from jarvis.core.secrets import get_secret, set_secret
from jarvis.core.tools import Tool
from jarvis.server import HOST, make_server, port_from_env, ts_host_from_env
import jarvis.tools.home  # noqa: F401  (enregistre les outils domotique)
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
    return input(f"Confirmer {tool.name} {tool.preview(args)} ? [o/N] ").strip().lower() == "o"


def no_strong_auth(tool: Tool, args: dict) -> bool:
    print("Action N3 refusée : la CLI n'a pas d'authentification forte (WebAuthn en Phase 3).")
    return False


def device_or_serve(argv: list[str], audit: Audit) -> int:
    """Gestion des appareils de la PWA et lancement du serveur local : uniquement depuis le PC, jamais par HTTP."""
    devices = Devices(str(DB_PATH))
    sub = argv[1] if len(argv) > 1 else ""
    if argv == ["serve"] or sub == "add" and len(argv) == 2:  # list et revoke ne dépendent d'aucune variable réseau
        try:
            port, ts_host = port_from_env(), ts_host_from_env()
        except ValueError as e:
            print(e if "TS_HOST" in str(e) else "JARVIS_PORT doit être un entier entre 1024 et 65535.")
            return 2
    if argv == ["serve"]:
        server = make_server(devices, audit, port, ts_host=ts_host)
        print(f"Serveur local sur http://{HOST}:{port}" + (f" et https://{ts_host} (via tailscale serve)" if ts_host else "")
              + " (Ctrl+C pour arrêter)", file=sys.stderr)
        server.run()
        return 0
    if sub == "list" and len(argv) == 2:
        for row in devices.list():
            print(" | ".join("" if v is None else str(v) for v in row))
        return 0
    if sub == "add" and len(argv) == 2 or sub == "revoke" and len(argv) == 3 and argv[2].isdigit():
        if not sys.stdin.isatty():  # action d'un humain devant le PC, comme une confirmation N3
            print("Refusé : cette commande exige un terminal interactif.")
            return 1
        if sub == "add":
            code = devices.new_code()
            audit.log("cli", "device_add", {}, 3, "confirmé", "code d'enrôlement créé")
            print(f"Code d'enrôlement (à usage unique, valable {CODE_TTL_S // 60} min) : {code}")
            url = f"https://{ts_host}/#code={code}" if ts_host else f"http://{HOST}:{port}/#code={code}"
            print(f"Sur le téléphone, ouvre : {url}")  # le code est dans le fragment (#) : jamais envoyé au serveur
            segno.make(url, error="m").terminal(compact=True)
            return 0
        ok = devices.revoke(int(argv[2]))
        audit.log("cli", "device_revoke", {"id": int(argv[2])}, 3, "confirmé", "révoqué" if ok else "introuvable")
        print("Appareil révoqué." if ok else "Appareil introuvable ou déjà révoqué.")
        return 0 if ok else 1
    print("Usage : device add | device list | device revoke <id> | serve")
    return 2


def level_cmd(argv: list[str]) -> int:
    if argv == ["level", "list"]:
        for name, base, floor, now in levels.table():
            print(f"{name} | registre N{base} | plancher N{floor} | effectif N{now}")
        return 0
    if len(argv) == 4 and argv[1] == "set" and argv[3] in ("0", "1", "2", "3"):
        if not sys.stdin.isatty():
            print("Refusé : cette commande exige un terminal interactif.")
            return 1
        try:
            print(levels.set_level(argv[2], int(argv[3]), strong_auth=False))  # CLI sans WebAuthn : abaisser est refusé
        except (ValueError, PermissionError) as e:
            print(e)
            return 1
        return 0
    print("Usage : level list | level set <outil> <0-3>")
    return 2


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    if argv[0] == "secret":  # avant le journal : pas besoin de la base, et la valeur n'est jamais affichée
        if len(argv) != 3 or argv[1] not in ("set", "check"):
            print(__doc__)
            return 2
        try:
            if argv[1] == "set":
                set_secret(argv[2], getpass.getpass(f"Valeur de {argv[2]} (invisible) : "))
                print("Enregistré dans le coffre Windows.")
            else:
                print("présent" if get_secret(argv[2]) else "absent")
        except ValueError as e:
            print(e)
            return 2
        except keyring.errors.KeyringError:
            print("coffre Windows indisponible")
            return 1
        except (EOFError, KeyboardInterrupt):
            print("\nSaisie annulée.")
            return 1
        return 0
    if argv == ["ha", "check"]:
        try:
            print(f"Home Assistant {ha.version()} joignable, token accepté.")
        except ha.HAError as e:
            print(e)
            return 1
        return 0
    if str(DB_PATH) == ":memory:" or str(DB_PATH).startswith("file:"):
        print("JARVIS_DB doit être un chemin de fichier : le journal d'audit doit persister.")
        return 2
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    audit = Audit(str(DB_PATH))
    if argv[0] == "audit":
        for row in audit.last(int(argv[1]) if len(argv) > 1 else 20):
            print(" | ".join("" if v is None else str(v) for v in row))
        return 0
    levels.load(audit)
    if argv[0] == "level":
        return level_cmd(argv)
    if argv[0] == "device" or argv == ["serve"]:
        return device_or_serve(argv, audit)
    if argv[0] == "run":
        if len(argv) < 2:
            print(__doc__)
            return 2
        name, args = argv[1], argv[2:]
    else:
        text = " ".join(argv)
        routed = Router().route(text)
        if routed is None:
            try:
                print(ask(text, audit=audit, confirm=confirm, strong_auth=no_strong_auth))
            except LLMUnavailable as e:
                print(e)
                return 1
            except (EOFError, KeyboardInterrupt):
                print("\nAction annulée.")
                return 1
            except Exception as e:  # pas de trace : elle pourrait contenir des arguments ou des noms de fichiers
                print(f"Erreur interne : {type(e).__name__}")
                return 1
            return 0
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
    except Exception as e:  # echec d'execution (OSError, delai depasse) : deja journalise, pas de trace Python
        print(f"Erreur d'exécution : {type(e).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
