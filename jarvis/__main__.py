"""Interface texte minimale.

    python -m jarvis "<phrase>"
    python -m jarvis run <outil> [clé=valeur ...]
    python -m jarvis audit [n]
    python -m jarvis doctor [--watch]     bilan de santé ; --watch relance le Core s'il est muet (chaque minute)
    python -m jarvis purge [--dry-run]    conservation : captures 7 j, finance et veille 120 j, journal archivé après 12 mois
    python -m jarvis secret set|check <nom>
    python -m jarvis secret export <dossier>   (un fichier 0600 par secret, pour systemd-creds)
    python -m jarvis ha check
    python -m jarvis veille fetch                      (copie les envois « [Veille ...] » du compte mail dans ~/.jarvis/veille/, lecture seule)
    python -m jarvis finance fetch                     (copie les rapports « [Dépenses] » du compte mail dans ~/.jarvis/finance/, lecture seule)
    python -m jarvis bank key <app_id> <fichier.pem> <redirect_url> | link "<banque>" [pays] | status | fetch [daily]
                                                       (Enable Banking, lecture seule ; terminal interactif)
    python -m jarvis portfolio import <export.csv>     (copie l'export de transactions Trade Republic dans ~/.jarvis/, lecture seule)
    python -m jarvis portfolio base <cto> <pea>        (valeurs du jour lues dans l'appli ; l'épargne Trade Republic s'y ajoute ensuite)
    python -m jarvis binance fetch [catégorie ...]      (historique Binance en lecture seule -> ~/.jarvis/binance-history.json ; clé dans .env)
    python -m jarvis device add [--voice <nom>] | list | revoke <id|all>   (terminal interactif)
    python -m jarvis passkey add <id appareil>         (ouvre 120 s pour enregistrer une clé d'accès, terminal interactif)
    python -m jarvis push test <id appareil>           (envoie une notification d'essai)
    python -m jarvis level list | set <outil> <0-3>    (relever est libre ; abaisser exige N3)
    python -m jarvis say "<texte>"                     (lit le texte à voix haute, source `voix`)
    python -m jarvis voice   (PC : micro + Whisper + Piper en local, texte envoyé au Core ; JARVIS_CORE_URL, clé voice_key)
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

from jarvis.core import ha, levels, memory, reminders
from jarvis.core.audit import Audit
from jarvis.core.devices import CODE_TTL_S, Devices
from jarvis.core.llm import LLMUnavailable, ask
from jarvis.core.permissions import Refused, execute
from jarvis.core.push import Push, subject_from_env
from jarvis.core.router import Router
from jarvis.core.secrets import export_all, get_secret, set_secret
from jarvis.core.tools import Tool
from jarvis.core.webauthn import Passkeys
from jarvis.server import HOST, make_server, port_from_env, ts_host_from_env
import jarvis.tools.assist  # noqa: F401  (enregistre minuteurs, rappels et briefing)
import jarvis.tools.dev  # noqa: F401  (enregistre l'outil Claude Code)
import jarvis.tools.home  # noqa: F401  (enregistre les outils domotique)
from jarvis.tools.home import pcplug
import jarvis.tools.mail  # noqa: F401  (enregistre le connecteur mail)
import jarvis.tools.voyages  # noqa: F401  (enregistre les outils voyages)
import jarvis.tools.conso  # noqa: F401  (enregistre conso_pc)
from jarvis.core.host import load_pc_tools

load_pc_tools()  # outils PC réels, ou proxys vers l'agent PC sur le mini-PC

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


def check_models(audit: Audit) -> None:
    """Au démarrage : tout modèle présent doit correspondre au manifeste (sinon signalé et journalisé). Réchauffe aussi le
    cache de `is_good`, donc le premier chargement vocal ne re-hache pas 1,6 Go. Sans bloquer le démarrage."""
    try:
        from jarvis.core.modelcheck import check_manifest
        models = Path(__file__).resolve().parent.parent / "models"
        if not (models / "MANIFEST.json").is_file():
            return
        for path in check_manifest(models / "MANIFEST.json", models):
            print(f"ATTENTION modèle modifié ou corrompu : {path}", file=sys.stderr)
            audit.log("cli", "model_check", {"path": path}, None, "refusé", "modèle différent du manifeste")
    except Exception:
        print("Contrôle des modèles impossible.", file=sys.stderr)


def start_mic(audit: Audit):
    """Micro toujours à l'écoute tant que `~/.jarvis/mic_off` n'existe pas ; échec = serveur sans micro, jamais bloquant."""
    from jarvis.core.host import HAS_PC_TOOLS
    if not HAS_PC_TOOLS:  # Core du mini-PC : ni micro ni GPU, la voix vient du client du PC (`python -m jarvis voice`)
        return None
    try:
        from jarvis.core.chat import Chat
        from jarvis.core.mic import Mic, threshold_from_env, wake_name_from_env
        from jarvis.core.stt import Transcriber
        from jarvis.core.tts import Speaker
        from jarvis.core.voice import Listener, Voice
        voice = Voice(Chat(audit), Speaker(audit))
        mic = Mic(Listener(voice, Transcriber(), lambda text, answer: None), audit, voice.speaker, threshold=threshold_from_env(), wake_name=wake_name_from_env())
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
        for problem in audit.health():  # on démarre quand même : le propriétaire doit le savoir, pas être bloqué
            print(f"ATTENTION journal d'audit : {problem}", file=sys.stderr)
            audit.log("cli", "audit_health", {}, None, "refusé", problem)
            try:  # stderr va vers devnull sous pythonw : le push est le seul signal
                from jarvis.core import doctor
                doctor.notify_all(str(DB_PATH), doctor.HEALTH_ALERT)
            except Exception:  # noqa: BLE001 (le journal garde la trace)
                pass
        threading.Thread(target=check_models, args=(audit,), daemon=True).start()
        threading.Thread(target=_purge, args=(audit,), daemon=True).start()
        mic = start_mic(audit)
        threading.Thread(target=_reminders, args=(audit, mic), daemon=True).start()
        threading.Thread(target=_voyages_watch, args=(audit,), daemon=True).start()
        threading.Thread(target=_conso_watch, daemon=True).start()
        threading.Thread(target=_drivers_watch, args=(audit,), daemon=True).start()
        threading.Thread(target=_conso_home_watch, args=(audit,), daemon=True).start()
        server = make_server(devices, audit, port, ts_host=ts_host, mic=mic,
                             stt=getattr(mic.on_utterance, "stt", None) if mic else None)  # même modèle que le micro du PC
        threading.Thread(target=_bienetre, daemon=True).start()
        print(f"Serveur local sur http://{HOST}:{port}" + (f" et https://{ts_host} (via tailscale serve)" if ts_host else "")
              + " (Ctrl+C pour arrêter)", file=sys.stderr)
        server.run()
        return 0
    if sub == "list" and len(argv) == 2:
        for row in devices.list():
            print(" | ".join("" if v is None else str(v) for v in row))
        return 0
    if sub == "add" and len(argv) in (2, 4) and (len(argv) == 2 or argv[2] in ("--voice", "--tv")) or sub == "revoke" and len(argv) == 3 and (argv[2].isdigit() or argv[2] == "all"):
        if not sys.stdin.isatty():  # action d'un humain devant le PC, comme une confirmation N3
            print("Refusé : cette commande exige un terminal interactif.")
            return 1
        if sub == "add" and len(argv) == 4:  # appareil de portée limitée : voix (/api/voice, micro du salon) ou tv (écran de la TV)
            scope = argv[2][2:]
            try:
                dev_id, token = devices.add_scoped(argv[3], scope)
            except ValueError as e:
                print(e)
                return 2
            audit.log("cli", "device_add", {"scope": scope, "id": dev_id}, 3, "confirmé", f"appareil de portée {scope} créé")
            where = "à coller dans Home Assistant" if scope == "voice" else "à donner à l'appli de la TV (android-tv/README.md)"
            print(f"Appareil {dev_id} (portée {scope}). Clé, affichée une seule fois, {where} : {token}")
            return 0
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
        if argv[2] == "all":  # téléphone perdu ou token volé : tout couper, puis réenrôler
            n = devices.revoke_all()
            audit.log("cli", "device_revoke", {"tous": True}, 3, "confirmé", f"{n} appareil(s) révoqué(s)")
            print(f"{n} appareil(s) révoqué(s).")
            return 0
        ok = devices.revoke(int(argv[2]))
        audit.log("cli", "device_revoke", {"id": int(argv[2])}, 3, "confirmé", "révoqué" if ok else "introuvable")
        print("Appareil révoqué." if ok else "Appareil introuvable ou déjà révoqué.")
        return 0 if ok else 1
    print("Usage : device add [--voice <nom>] | device list | device revoke <id|all> | serve")
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
    from jarvis.core.mic import Mic, threshold_from_env, wake_name_from_env
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
    mic = Mic(listener, audit, voice.speaker, on_state=lambda s: print(f"[{s}]"), threshold=threshold_from_env(), wake_name=wake_name_from_env())
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
            # tâche planifiée plusieurs fois par jour : une lecture complète, puis seulement les banques en échec (quota)
            todo = banking.pending_today() if argv[-1] == "daily" else None
            if todo == []:
                print("Déjà récupéré aujourd'hui.")
                return 0
            r = banking.fetch(banks=todo)
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


def _voyages_watch(audit) -> None:
    """Toutes les heures : vol Japon sous 650 € (escales respectées) -> push générique, sans prix ni itinéraire."""
    import time
    from jarvis.core import doctor, voyages
    body = {"title": "Jarvis", "body": f"Un vol pour le Japon est passé sous {voyages.DEAL_BELOW} €. Ouvre le tableau de bord."}
    while True:
        time.sleep(60)  # le serveur démarre d'abord
        try:
            if voyages.check_deal(lambda: doctor.notify_all(str(DB_PATH), body)):
                audit.log("pwa:voyages", "voyages_deal", {}, 0, "auto", "notification envoyée")
        except Exception:  # noqa: BLE001 (réseau, git, push : réessai à la prochaine heure)
            pass
        time.sleep(voyages.FETCH_EVERY_S)


def _conso_home_watch(audit) -> None:
    """Toutes les heures : relevé quotidien du compteur (au plus un appel par 24 h, voir jarvis/core/enedis.py).
    Une ligne au journal à chaque changement d'état (ok / indisponible), sans valeur."""
    import time
    from jarvis.core import enedis
    last = None
    while True:
        time.sleep(90)  # le serveur démarre d'abord
        try:
            status = enedis.refresh()
        except Exception:  # noqa: BLE001 (disque : réessai à l'heure suivante)
            status = "indisponible"
        if status in ("ok", "indisponible") and status != last:
            audit.log("pwa:conso", "conso_enedis_fetch", {}, 0, "auto", status)
        last = status if status != "à jour" else last
        time.sleep(3600)


def _conso_watch() -> None:
    """Chaque minute : puissance de la prise du PC -> énergie du jour (jarvis/core/conso.py). Lecture seule, rien au journal."""
    import time
    from jarvis.core import conso
    from jarvis.tools.home import pcplug
    while True:
        try:
            conso.sample(pcplug.watts())  # inf (prise illisible) : trou, pas de mesure inventée
        except Exception:  # noqa: BLE001 (disque, HA : réessai à la minute suivante)
            pass
        time.sleep(conso.SAMPLE_S)


def _reminders(audit, mic) -> None:
    """Annonce minuteurs, rappels et briefing du matin : voix du PC (sauf hors ligne) + push sans le texte."""
    import time
    from jarvis.core import agentlink, doctor
    from jarvis.tools.assist import build_briefing
    try:
        at = reminders.briefing_time()
    except ValueError as e:
        print(e, file=sys.stderr)
        at = None
    voice = getattr(getattr(mic, "on_utterance", None), "voice", None)  # Listener -> Voice

    def announce(kind: str, label: str, late: float) -> str:
        if kind == "briefing":
            spoken, body = build_briefing(), "Ton briefing du matin est prêt : demande « briefing »."
        else:
            spoken = ("Minuteur terminé." if kind == "timer" else "Rappel.") + (f" {label}" if label else "")
            body = "Ton minuteur est terminé." if kind == "timer" else "Un rappel t'attend."
        done = []
        try:
            doctor.notify_all(str(DB_PATH), {"title": "Jarvis", "body": body})
            done.append("push")
        except Exception:  # noqa: BLE001 (clé ou réseau : la voix passe quand même)
            pass
        if voice is None:  # Core du mini-PC : le PC lit par l'agent (PC éteint ou agent absent = push seul)
            try:
                if agentlink.agent_url():
                    agentlink.call("run", "say", {"text": spoken}, timeout=5)
                    done.insert(0, "voix")
            except (agentlink.AgentError, ValueError):
                pass
        if voice is not None and not voice.offline and voice.speaker is not None and not voice.muted:
            for _ in range(40):  # une réponse en cours se termine d'abord (20 s au plus)
                if not voice.speaker.is_speaking():
                    break
                time.sleep(0.5)
            if not voice.speaker.is_speaking():
                voice.say(spoken)
                done.insert(0, "voix")
        return " + ".join(done) or "non remis (ni voix ni push)"

    reminders.run(announce, at)


def _drivers_watch(audit) -> None:
    """Toutes les 6 h : pilote GPU/réseau/système en retard jamais signalé -> push générique, sans nom de pilote."""
    import time
    from jarvis.core import agentlink, doctor, driveralert
    from jarvis.core.host import HAS_PC_TOOLS
    body = {"title": "Jarvis", "body": "Une mise à jour de pilote importante est disponible. Ouvre l'onglet Pilotes."}
    while True:
        time.sleep(180)  # le serveur démarre d'abord
        try:
            if HAS_PC_TOOLS:
                from jarvis.tools.pc.drivers import status
                snap = status()
            else:
                snap = agentlink.call("run", "pc_drivers", {}, timeout=5)
            if isinstance(snap, dict) and driveralert.check(snap, lambda: doctor.notify_all(str(DB_PATH), body)):
                audit.log("pwa:pilotes", "drivers_alert", {}, 0, "auto", "notification envoyée")
        except Exception:  # noqa: BLE001 (PC éteint, push : réessai au prochain tour)
            pass
        time.sleep(6 * 3600)


def _bienetre() -> None:
    """Bilan de santé du PC relancé chaque jour (onglet Bien-être) : un contrôle toutes les 30 min."""
    import time
    from jarvis.core import bienetre
    while True:
        try:
            bienetre.refresh_if_stale()
        except Exception as e:  # noqa: BLE001 (le serveur ne dépend pas du bilan)
            print(f"Bien-être : contrôle du bilan en erreur ({type(e).__name__}).", file=sys.stderr)
        time.sleep(1800)


def _purge(audit) -> None:
    from jarvis.core import retention
    try:
        audit.log("serve", "purge", {}, None, "auto", str(retention.run(audit)))
    except Exception as e:  # le serveur ne dépend pas de la purge
        audit.log("serve", "purge", {}, None, "refusé", type(e).__name__)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    if argv[0] == "secret":  # avant le journal : pas besoin de la base, et la valeur n'est jamais affichée
        if len(argv) != 3 or argv[1] not in ("set", "check", "export"):
            print(__doc__)
            return 2
        try:
            if argv[1] == "export":
                print("Exportés :", ", ".join(export_all(Path(argv[2]))) or "aucun")
            elif argv[1] == "set":
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
    if argv[0] == "doctor":
        from jarvis.core import doctor
        from jarvis.server import port_from_env
        port = port_from_env()
        if "--watch" in argv:
            r = doctor.watch(audit, up=lambda: doctor.http_up(f"http://127.0.0.1:{port}/"),
                             notify=lambda: doctor.notify_all(str(DB_PATH)),
                             notify_health=lambda: doctor.notify_all(str(DB_PATH), doctor.HEALTH_ALERT))
            return 0 if r == "ok" else 1
        checks = doctor.report(audit, port, doctor.backup_dir(), doctor.MODELS)
        for name, problem in checks:
            print(f"{'OK ' if problem is None else 'KO '} {name}" + (f" : {problem}" if problem else ""))
        return 1 if any(p for _, p in checks) else 0
    if argv[0] == "purge":
        from jarvis.core import retention
        report = retention.run(audit, dry="--dry-run" in argv)
        print(report)
        if "--dry-run" not in argv:
            audit.log("cli", "purge", {}, None, "auto", str(report))
        return 0
    if argv[0] == "audit":
        for row in audit.last(int(argv[1]) if len(argv) > 1 else 20):
            print(" | ".join("" if v is None else str(v) for v in row))
        return 0
    levels.load(audit)
    reminders.load(audit)
    pcplug.load(audit)
    memory.load(audit)
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
    if argv[:2] == ["portfolio", "import"] and len(argv) == 3:
        from jarvis.core import portfolio
        try:
            n = portfolio.import_csv(Path(argv[2]))
        except (OSError, ValueError) as e:
            audit.log("cli", "portfolio_import", {}, 2, "auto", "échec")
            print(f"Import impossible : {e if isinstance(e, ValueError) else type(e).__name__}")
            return 1
        audit.log("cli", "portfolio_import", {}, 2, "auto", f"{n} ligne(s)")
        print(f"{n} ligne(s) importée(s).")
        return 0
    if argv[:2] == ["portfolio", "base"] and len(argv) == 4:
        from jarvis.core import banking, portfolio
        try:
            values = {"Compte-titres": float(argv[2].replace(",", ".")), "PEA": float(argv[3].replace(",", "."))}
            bank = banking.view() or {}
            portfolio.set_base(values, savings=bank.get("invest"))
        except (OSError, ValueError) as e:
            audit.log("cli", "portfolio_base", {}, 2, "auto", "échec")
            print(f"Base impossible : {e if isinstance(e, ValueError) else type(e).__name__}")
            return 1
        audit.log("cli", "portfolio_base", {}, 2, "auto", "ok")
        print("Base enregistrée : l'épargne Trade Republic à partir de demain s'y ajoute.")
        return 0
    if argv[:2] == ["binance", "fetch"]:
        from jarvis.core import binance
        try:
            r = binance.run(only=set(argv[2:]) or None)
        except (RuntimeError, OSError) as e:  # message Binance sans secret ; la clé n'est jamais dans une exception
            audit.log("cli", "binance_fetch", {}, 2, "auto", "échec")
            print(f"Récupération impossible : {e if isinstance(e, RuntimeError) else type(e).__name__}")
            return 1
        audit.log("cli", "binance_fetch", {}, 2, "auto", f"{sum(map(len, r['data'].values()))} ligne(s)")
        for name, rows in r["data"].items():
            print(f"{name}: {len(rows)}")
        for name, msg in r["errors"].items():
            print(f"ERREUR {name}: {msg}")
        print(f"Écrit dans {binance.OUT}")
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
    if argv == ["voice"]:  # client voix du PC : le Core est sur le mini-PC
        from jarvis import voice_client
        return voice_client.run(audit)
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
