"""Interface texte minimale.

    python -m jarvis "<phrase>"
    python -m jarvis run <outil> [clé=valeur ...]
    python -m jarvis audit [n]
    python -m jarvis secret set|check <nom>
    python -m jarvis ha check
    python -m jarvis veille fetch                      (copie les envois « [Veille ...] » du compte mail dans ~/.jarvis/veille/, lecture seule)
    python -m jarvis finance fetch                     (copie les rapports « [Dépenses] » du compte mail dans ~/.jarvis/finance/, lecture seule)
    python -m jarvis bank key <app_id> <fichier.pem> <redirect_url> | link "<banque>" [pays] | status | fetch [daily]
                                                       (Enable Banking, lecture seule ; terminal interactif)
    python -m jarvis device add | list | revoke <id>   (terminal interactif)
    python -m jarvis passkey add <id appareil>         (ouvre 120 s pour enregistrer une clé d'accès, terminal interactif)
    python -m jarvis push test <id appareil>           (envoie une notification d'essai)
    python -m jarvis level list | set <outil> <0-3>    (relever est libre ; abaisser exige N3)
    python -m jarvis say "<texte>"                     (lit le texte à voix haute, source `voix`)
    python -m jarvis mic [listen] | on | off | devices (écoute « hey jarvis » ; `off` = kill switch persistant ; JARVIS_AUDIO_IN)
    python -m jarvis serve                             (127.0.0.1 seulement)
"""
import getpass
import imaplib
import json
import os
import sys
import threading
from pathlib import Path

if sys.stdout is None or sys.stderr is None:  # pythonw (tâche planifiée) : sans sortie standard, une lib native plante (0xC0000005)
    sys.stdout = sys.stderr = open(os.devnull, "w")

os.environ["HF_HUB_OFFLINE"] = "1"  # (9) avant tout import voix : aucun accès réseau des bibliothèques de modèles

import keyring.errors
import segno

from jarvis.core import ha, levels
from jarvis.core.audit import Audit
from jarvis.core.devices import CODE_TTL_S, Devices
from jarvis.core.llm import LLMUnavailable, ask
from jarvis.core.permissions import Refused, execute
from jarvis.core.push import Push, subject_from_env
from jarvis.core.router import Router
from jarvis.core.secrets import get_secret, set_secret
from jarvis.core.tools import Tool
from jarvis.core.webauthn import Passkeys
from jarvis.server import HOST, make_server, port_from_env, ts_host_from_env
import jarvis.tools.dev  # noqa: F401  (enregistre l'outil Claude Code)
import jarvis.tools.home  # noqa: F401  (enregistre les outils domotique)
import jarvis.tools.mail  # noqa: F401  (enregistre le connecteur mail)
import jarvis.tools.social  # noqa: F401  (enregistre le planning lol-clipper)
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
    print("Action N3 refusée : la CLI n'a pas d'authentification forte (WebAuthn existe seulement dans la PWA).")
    return False


def start_mic(audit: Audit):
    """Micro toujours à l'écoute tant que `~/.jarvis/mic_off` n'existe pas ; échec = serveur sans micro, jamais bloquant."""
    try:
        from jarvis.core.chat import Chat
        from jarvis.core.mic import Mic, threshold_from_env
        from jarvis.core.stt import Transcriber
        from jarvis.core.tts import Speaker
        from jarvis.core.voice import Listener, Voice
        voice = Voice(Chat(audit), Speaker(audit))
        mic = Mic(Listener(voice, Transcriber(), lambda text, answer: None), audit, voice.speaker, threshold=threshold_from_env())
        threading.Thread(target=mic.run, daemon=True).start()
        return mic
    except Exception:
        print("Micro indisponible : le serveur démarre sans écoute vocale.", file=sys.stderr)
        return None


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
        mic = start_mic(audit)
        server = make_server(devices, audit, port, ts_host=ts_host, mic=mic)
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
            try:
                segno.make(url, error="m").terminal(compact=True)
            except UnicodeEncodeError:  # console non UTF-8 (cp1252) : le lien ci-dessus suffit
                print("(QR non affichable dans cette console : utilise le lien.)")
            return 0
        ok = devices.revoke(int(argv[2]))
        audit.log("cli", "device_revoke", {"id": int(argv[2])}, 3, "confirmé", "révoqué" if ok else "introuvable")
        print("Appareil révoqué." if ok else "Appareil introuvable ou déjà révoqué.")
        return 0 if ok else 1
    print("Usage : device add | device list | device revoke <id> | serve")
    return 2


def passkey_cmd(argv: list[str], audit: Audit) -> int:
    if len(argv) != 3 or argv[1] != "add" or not argv[2].isdigit():
        print("Usage : passkey add <id appareil>")
        return 2
    if not sys.stdin.isatty():
        print("Refusé : cette commande exige un terminal interactif.")
        return 1
    ok = Passkeys(Devices(str(DB_PATH)), None).open_window(int(argv[2]))
    audit.log("cli", "passkey_add", {"id": int(argv[2])}, 3, "confirmé" if ok else "refusé",
              "fenêtre d'enregistrement ouverte" if ok else "appareil introuvable ou révoqué")
    print("Sur l'appareil que tu as en main (et lui seul), ouvre Réglages > Clé d'accès dans les 2 minutes." if ok else "Appareil introuvable ou révoqué.")
    return 0 if ok else 1


def mic_cmd(argv: list[str], audit: Audit) -> int:
    from jarvis.core.mic import Mic, threshold_from_env
    sub = argv[1] if len(argv) > 1 else "listen"
    if sub == "devices":
        import sounddevice
        for i, d in enumerate(sounddevice.query_devices()):
            if d["max_input_channels"] > 0:
                print(i, d["name"])
        return 0
    from jarvis.core.chat import Chat
    from jarvis.core.stt import Transcriber
    from jarvis.core.tts import Speaker
    from jarvis.core.voice import Listener, Voice
    voice = Voice(Chat(audit), Speaker(audit))
    listener = Listener(voice, Transcriber(), lambda text, answer: print(f"> {text}\n{answer}") if sys.stdout.isatty() else None)  # jamais vers un fichier
    mic = Mic(listener, audit, voice.speaker, on_state=lambda s: print(f"[{s}]"), threshold=threshold_from_env())
    if sub in ("on", "off"):
        if sub == "on" and not sys.stdin.isatty():  # réarmer le micro exige un terminal
            print("Réarmer le micro exige un terminal interactif.")
            return 1
        mic.disable() if sub == "off" else mic.enable()
        audit.log("cli", "mic_switch", {"état": sub}, None, "auto", "ok")
        print("micro coupé" if sub == "off" else "micro autorisé")
        return 0
    if sub != "listen":
        print(__doc__)
        return 2
    print("Dis « hey jarvis » puis une phrase. Ctrl+C pour quitter.")
    try:
        mic.run()
    except KeyboardInterrupt:
        pass
    for err in (mic.error, listener.error, voice.speaker.error):
        if err:
            print(err)
    return 1 if mic.error else 0


def push_cmd(argv: list[str], audit: Audit) -> int:
    if len(argv) != 3 or argv[1] != "test" or not argv[2].isdigit():
        print("Usage : push test <id appareil>")
        return 2
    ok = Push(Devices(str(DB_PATH)), subject_from_env()).send(int(argv[2]))
    audit.log("cli", "push_test", {"id": int(argv[2])}, None, "auto", "remise" if ok else "non remise")
    print("Notification remise." if ok else "Non remise : appareil sans abonnement, révoqué, ou service de push injoignable.")
    return 0 if ok else 1


def bank_cmd(argv: list[str], audit: Audit) -> int:
    from jarvis.core import banking
    if argv[1] not in ("key", "link", "status", "fetch"):
        print(__doc__)
        return 2
    what = f"bank_{argv[1]}"
    # Configurer et lier exigent un humain ; `fetch` et `status` tournent aussi en tâche planifiée (pythonw : stdin absent).
    # ponytail: un script lancé par Jarvis peut déclencher `fetch` ; impact borné (cache chiffré, quota PSD2 de la banque).
    if argv[1] in ("key", "link") and not (sys.stdin and sys.stdin.isatty()):
        audit.log("cli", what, {}, 2, "refusé", "terminal non interactif")
        print("Refusé : cette commande exige un terminal interactif.")
        return 1
    try:
        if len(argv) == 5 and argv[1] == "key":
            banking.configure(argv[2], Path(argv[3]).read_bytes(), argv[4])
            audit.log("cli", "bank_key", {}, 2, "auto", "application enregistrée")
            print(f"Enregistré (chiffré). Supprime maintenant {argv[3]}.")
        elif len(argv) in (3, 4) and argv[1] == "link":
            link = banking.start_link(argv[2], argv[3] if len(argv) == 4 else "FR")
            print(f"Ouvre ce lien, connecte-toi à la banque, puis colle l'adresse de la page d'arrivée :\n{link['url']}")
            n = banking.finish_link(link, input("Adresse de retour : "))
            audit.log("cli", "bank_link", {"bank": link["aspsp"]["name"]}, 2, "auto", f"{n} compte(s)")
            print(f"{n} compte(s) lié(s).")
        elif argv[1:] == ["status"]:
            for s in banking.status():
                print(f"{s['bank']} | {s['accounts']} compte(s) | consentement : {'?' if s['days_left'] is None else s['days_left']} j")
        elif argv[1:] in (["fetch"], ["fetch", "daily"]):
            if argv[-1] == "daily" and banking.fetched_today():  # tâche à l'ouverture de session : une seule fois par jour
                print("Déjà récupéré aujourd'hui.")
                return 0
            r = banking.fetch()
            audit.log("cli", "bank_fetch", {}, 2, "auto", f"{r['accounts']} compte(s), {len(r['errors'])} échec(s)")
            print(f"{r['accounts']} compte(s), {r['transactions']} transaction(s).", *r["errors"], sep="\n")
            return 1 if r["errors"] else 0
        else:
            print(__doc__)
            return 2
    except (banking.BankError, OSError) as e:
        audit.log("cli", what, {}, 2, "auto", "échec")
        print(e if isinstance(e, banking.BankError) else f"fichier illisible : {type(e).__name__}")
        return 1
    except keyring.errors.KeyringError:
        audit.log("cli", what, {}, 2, "auto", "échec : coffre indisponible")
        print("coffre Windows indisponible")
        return 1
    except (EOFError, KeyboardInterrupt):
        audit.log("cli", what, {}, 2, "auto", "annulé")
        print("\nSaisie annulée.")
        return 1
    return 0


def level_cmd(argv: list[str]) -> int:
    if argv == ["level", "list"]:
        for name, base, floor, now in levels.table():
            print(f"{name} | registre N{base} | plancher N{floor} | effectif N{now}")
        return 0
    if len(argv) == 4 and argv[1] == "set" and argv[3] in ("0", "1", "2", "3"):
        if not (sys.stdin and sys.stdin.isatty()):
            print("Refusé : cette commande exige un terminal interactif.")
            return 1
        try:
            print(levels.set_level(argv[2], int(argv[3]), strong_auth=False, source="cli"))  # CLI sans WebAuthn : abaisser est refusé
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
    if argv in (["finance", "fetch"], ["veille", "fetch"]):
        from jarvis.core import finance, finance_fetch, veille
        what, fetch = (("finance_fetch", lambda: finance_fetch.fetch_reports()) if argv[0] == "finance" else
                       ("veille_fetch", lambda: finance_fetch.fetch_mails(veille.veille_dir(), '"[Veille"', veille.parse, veille.name, "veille-*.eml")))
        try:
            n = fetch()
        except (RuntimeError, OSError, ValueError, imaplib.IMAP4.error) as e:  # texte serveur/mail jamais affiché
            audit.log("cli", what, {}, 2, "auto", "échec")
            print(f"Récupération impossible : {e if isinstance(e, RuntimeError) else type(e).__name__}")
            return 1
        audit.log("cli", what, {}, 2, "auto", f"{n} mail(s) écrit(s)")
        print(f"{n} mail(s) enregistré(s).")
        return 0
    if argv[0] == "say":
        if len(argv) < 2:
            print(__doc__)
            return 2
        from jarvis.core.chat import Chat
        from jarvis.core.tts import Speaker
        from jarvis.core.voice import Voice
        voice = Voice(Chat(audit), Speaker(audit))
        voice.say(" ".join(argv[1:]))
        if voice.speaker.error:
            print(voice.speaker.error)
            return 1
        return 0
    if argv[0] == "mic":
        return mic_cmd(argv, audit)
    if argv[0] == "passkey":
        return passkey_cmd(argv, audit)
    if argv[0] == "push":
        return push_cmd(argv, audit)
    if argv[0] == "level":
        return level_cmd(argv)
    if argv[0] == "bank" and len(argv) > 1:
        return bank_cmd(argv, audit)
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
