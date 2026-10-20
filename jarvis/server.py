"""Serveur local de la PWA (étape 1 : authentification seulement, aucune route d'outil).

Écoute sur 127.0.0.1 en dur (aucune option) ; l'exposition viendra de `tailscale serve`, jamais d'un port ouvert.
Garde-fous : Host et Origin vérifiés (DNS rebinding, CSRF), pas de CORS, corps borné, en-têtes de sécurité,
erreurs génériques, échecs d'authentification comptés globalement (toutes les requêtes viennent de 127.0.0.1).
"""
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Literal

os.environ["HF_HUB_OFFLINE"] = "1"  # (9) avant tout import voix : le serveur n'ouvre jamais le réseau pour un modèle

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field, StrictBool, StrictInt

from jarvis.core import levels, memory, reminders
from jarvis.core.audit import Audit
from jarvis.core.chat import TEXT_MAX, Chat
from jarvis.core.voice import Voice
from jarvis.core.dashboard import Dashboard
from jarvis.core.devices import Devices
from jarvis.core.banking import view as bank_view
from jarvis.core import binance
from jarvis.core.crypto import view as crypto_view
from jarvis.core.portfolio import view as portfolio_view
from jarvis.core.finance import snapshot as finance_snapshot
from jarvis.core.veille import snapshot as veille_snapshot
from jarvis.core import bienetre as bienetre_core
from jarvis.core import conseils
from jarvis.core import conso as conso_core
from jarvis.core import minipc
from jarvis.core import voyages as voyages_core
from jarvis.core.voyages import snapshot as voyages_snapshot
from jarvis.core.social import from_pc as social_from_pc, snapshot as social_snapshot, with_youtube
from jarvis.core.youtube_stats import YouTubeStats
from jarvis.core.push import Push, subject_from_env
from jarvis.core.webauthn import Passkeys
from jarvis.core import agentlink
from jarvis.core.host import HAS_PC_TOOLS

PANEL_TIMEOUT_S = 3  # PC éteint : l'encart ne bloque pas
BIENETRE_OFFLINE = {"configured": True, "offline": True, "running": False, "error": None, "at": None, "items": [],
                    "counts": None, "previous": None}

if HAS_PC_TOOLS:
    from jarvis.tools.pc.system import system_status
else:
    def system_status():  # Core du mini-PC : mesures du PC par l'agent ; PC éteint, l'encart système reste vide
        return agentlink.call("run", "system_status", {}, timeout=PANEL_TIMEOUT_S)

HOST = "127.0.0.1"  # volontairement non configurable
BODY_MAX = 8192
AUTH_FAIL_MAX, AUTH_FAIL_WINDOW_S = 10, 60
VOICES_MAX = 64  # micros distincts (appareil/client) gardés en mémoire
VOICE_MAX = 20  # phrases par appareil et par minute : une phrase dite en prend ~5 s
# ponytail: plafond par appareil et par minute sur toutes les routes (l'écran en fait ~60) : borne le journal gonflé par un pair
# valide à QUOTA_MAX + 1 lignes/min ; un quota par route si l'usage légitime s'en approche.
QUOTA_MAX, QUOTA_WINDOW_S = 240, 60
HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",  # redondant avec frame-ancestors, pour les vieux navigateurs
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=(), payment=(), usb=()",  # micro : bouton « parler » de la PWA
}
STT_TYPES = {"audio/webm", "audio/ogg", "audio/mp4"}  # ce que MediaRecorder produit (Chrome/Android, Firefox, Safari)
STT_BODY_MAX = 512 * 1024  # ~30 s d'Opus ; la durée décodée est bornée à part (STT_SECONDS_MAX)
STT_SECONDS_MAX = 30
STT_MAX = 6  # transcriptions par appareil et par minute : une phrase de 30 s occupe Whisper plusieurs secondes
_now = time.monotonic  # remplacé dans les tests
WEB_DIR = Path(__file__).parent / "web"
# Fichiers statiques : dossier plat, extensions de cette liste seulement. Un chemin ne sert que s'il est EXACTEMENT
# le nom d'un de ces fichiers (jamais de jointure avec la saisie : pas de traversée de chemin).
WEB_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
             ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
             ".webmanifest": "application/manifest+json", ".woff2": "font/woff2"}
AUDIT_ROWS = 50
RESULT_MAX = 120  # minimisation : le journal en garde 500, l'écran n'en a pas besoin
ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def port_from_env() -> int:
    port = int(os.environ.get("JARVIS_PORT") or 8765)
    if not 1024 <= port <= 65535:
        raise ValueError("JARVIS_PORT doit être entre 1024 et 65535")
    return port


TS_HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+\.ts\.net")


def ts_host_from_env() -> str | None:
    """Nom Tailscale de ce PC (JARVIS_TS_HOST), exact : ni joker, ni port, ni chemin, ni majuscule.

    Il vient de l'environnement, jamais du dépôt public. Absent : seul 127.0.0.1 est accepté.
    """
    host = (os.environ.get("JARVIS_TS_HOST") or "").strip()
    if not host:
        return None
    if len(host) > 253 or not TS_HOST.fullmatch(host):
        raise ValueError("JARVIS_TS_HOST doit être le nom exact de ce PC sur le tailnet (…ts.net, minuscules)")
    return host


class Enroll(BaseModel):
    code: str = Field(max_length=64)
    name: str = Field(max_length=40)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=TEXT_MAX)


class VoiceIn(BaseModel):
    text: str = Field(min_length=1, max_length=TEXT_MAX)
    client: str = Field(default="pc", max_length=32, pattern=r"^[a-z0-9_-]+$")  # micro d'origine (multi-micros plus tard)


B64 = Field(max_length=1400, pattern=r"^[A-Za-z0-9_-]+$")


class Assertion(BaseModel):
    id: str = Field(max_length=1400, pattern=r"^[A-Za-z0-9_-]+$")
    clientDataJSON: str = B64
    authenticatorData: str = B64
    signature: str = B64


class Destination(BaseModel):  # formulaire de l'onglet Voyages ; contenu revalidé par l'outil voyage_destination
    destination: str = Field(max_length=40)
    depart_from: str = Field(max_length=10)
    depart_to: str = Field(max_length=10)
    stay_days: str = Field(max_length=40)
    return_date: str = Field(max_length=10)
    origins: str = Field(max_length=400)
    alert_below: StrictInt = Field(ge=0, le=20_000)


class Tarif(BaseModel):  # prix du kWh saisi dans l'onglet Consommation
    price_kwh: float = Field(gt=0, le=conso_core.MAX_PRICE)


class Confirm(BaseModel):
    approve: StrictBool  # « oui » ou 1 ne confirment rien : seul `true` confirme
    assertion: Assertion | None = None  # N3 : signature WebAuthn du défi de cette demande


class IdIn(BaseModel):  # oublier un souvenir, annuler un rappel : par numéro seulement, jamais par mot
    id: int = Field(ge=1, le=10**9, strict=True)


class Subscription(BaseModel):
    endpoint: str = Field(max_length=600)
    p256dh: str = Field(max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    auth: str = Field(max_length=40, pattern=r"^[A-Za-z0-9_-]+$")


class Attestation(BaseModel):
    clientDataJSON: str = B64
    attestationObject: str = Field(max_length=4000, pattern=r"^[A-Za-z0-9_-]+$")


class MicIn(BaseModel):
    on: StrictBool
    assertion: Assertion | None = None  # réarmer avec une clé d'accès enregistrée : signature du défi « mic:on »


class AssertionIn(BaseModel):
    assertion: Assertion


class ChallengeIn(BaseModel):  # actions protégées par la clé d'accès hors chat : liste fermée
    action: Literal["devices:revoke"]


class LevelIn(BaseModel):
    tool: str = Field(max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    level: int = Field(ge=0, le=3, strict=True)
    assertion: Assertion | None = None  # abaisser un niveau = N3 : signature WebAuthn de (outil, niveau)


def create_app(devices: Devices, audit: Audit, port: int, chat: Chat | None = None,
               web_dir: Path = WEB_DIR, ts_host: str | None = None, push: Push | None = None, mic=None,
               stt=None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)  # pas de /docs ni de schéma public
    # Host accepté -> Origin attendu pour ce Host. Liste fermée : jamais de joker, jamais de confiance dans l'IP source
    # ni dans les en-têtes Tailscale (derrière `tailscale serve`, tout arrive de 127.0.0.1).
    hosts = {f"{HOST}:{port}": f"http://{HOST}:{port}"}
    if ts_host:
        hosts[ts_host] = f"https://{ts_host}"
    failures: deque[float] = deque()
    quota: dict[int, deque[float]] = {}  # appareil -> instants des requêtes de la dernière minute
    quota_logged: dict[int, float] = {}  # une seule ligne de journal par appareil et par fenêtre
    counters = threading.Lock()  # les routes sync tournent dans un pool : deque et dict partagés
    reads_logged: dict[tuple[int, str], float] = {}  # (appareil, lecture) -> dernière ligne de journal
    passkeys = Passkeys(devices, ts_host)  # sans nom Tailscale (HTTPS), WebAuthn est désactivé : N3 reste refusé
    push = push or Push(devices, subject_from_env())
    dashboard = Dashboard(system_status)
    youtube = YouTubeStats()
    chat = chat or Chat(audit, passkeys, push)
    if chat.push is None:
        chat.push = push
    if chat.passkeys is None:  # Chat fourni sans clés (tests) : mêmes clés que les routes
        chat.passkeys = passkeys

    def reply(status: int, detail: str, **extra) -> JSONResponse:
        return JSONResponse({"detail": detail}, status_code=status, headers={**HEADERS, **extra})

    def limited() -> bool:
        with counters:
            while failures and _now() - failures[0] > AUTH_FAIL_WINDOW_S:
                failures.popleft()
            return len(failures) >= AUTH_FAIL_MAX

    def log_read(device: int, tool: str, detail: str, decision: str = "auto") -> None:
        """Une ligne par appareil et par minute et par lecture : un token volé ne gonfle pas le journal à 240/min.
        Trace avant lecture (journal en échec = rien lu) ; la ligne de la minute couvre les lectures suivantes."""
        with counters:
            last = reads_logged.get((device, tool))
            if last is not None and 0 <= _now() - last < QUOTA_WINDOW_S:
                return
        audit.log(f"pwa:{device}", tool, {}, 2, decision, detail)  # lève si le journal échoue : rien n'est mémorisé
        with counters:
            reads_logged[(device, tool)] = _now()

    def authenticate(request: Request, allow: tuple[str, ...] = ()) -> tuple[int, str] | JSONResponse:
        """`allow` : portées limitées admises sur cette route (une clé « full » passe toujours)."""
        header = request.headers.get("authorization")
        if header is None:  # une page web ne peut pas poser cet en-tête (pas de CORS) : ni compté, ni journalisé,
            return reply(401, "non autorisé")  # sinon elle bloquerait les appareils légitimes (constat 2)
        scheme, _, token = header.partition(" ")
        found = devices.check_scoped(token) if scheme == "Bearer" and 0 < len(token) <= 200 else None
        if found is not None and found[2] != "full" and found[2] not in allow:  # clé de portée limitée : refusée hors de ses routes
            with counters:
                log_it = _now() - quota_logged.get(found[0], -QUOTA_WINDOW_S) >= QUOTA_WINDOW_S
                if log_it:
                    quota_logged[found[0]] = _now()
            if log_it:  # une ligne par minute : une clé voix détournée ne gonfle pas le journal
                audit.log(f"pwa:{found[0]}", "scope", {}, None, "refusé", f"clé de portée {found[2]} hors de ses routes")
            return reply(403, "portée insuffisante")
        if found is not None:  # un token valide n'est jamais bloqué par le compteur d'échecs
            found = found[:2]
            with counters:
                recent = quota.setdefault(found[0], deque())
                while recent and _now() - recent[0] > QUOTA_WINDOW_S:
                    recent.popleft()
                over = len(recent) >= QUOTA_MAX
                log_it = over and _now() - quota_logged.get(found[0], -QUOTA_WINDOW_S) >= QUOTA_WINDOW_S
                if log_it:
                    quota_logged[found[0]] = _now()
                if not over:
                    recent.append(_now())
            if over:
                if log_it:
                    audit.log(f"pwa:{found[0]}", "quota", {}, None, "refusé", f"plus de {QUOTA_MAX} requêtes par minute")
                return reply(429, "trop de requêtes", **{"Retry-After": str(QUOTA_WINDOW_S)})
            return found
        if limited():
            return reply(429, "trop d'échecs", **{"Retry-After": str(AUTH_FAIL_WINDOW_S)})
        with counters:
            failures.append(_now())
        audit.log("pwa:?", "auth", {}, None, "refusé", "token invalide ou révoqué")  # jamais le token
        return reply(401, "non autorisé")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        origin = hosts.get(host)
        if origin is None:  # DNS rebinding : une page web ne peut pas viser 127.0.0.1 sous un autre nom
            return reply(400, "requête invalide")
        if "transfer-encoding" in request.headers:  # CL + TE contourneraient la borne du corps (constat 1)
            return reply(411, "longueur requise")
        if request.method != "GET":
            if request.headers.get("origin") != origin:  # absent ou différent : refus (CSRF)
                return reply(403, "origine refusée")
            audio = request.url.path == "/api/stt"  # seule route qui reçoit autre chose que du JSON
            kind = request.headers.get("content-type", "").split(";")[0].strip()
            if kind not in (STT_TYPES if audio else {"application/json"}):
                return reply(415, "audio attendu" if audio else "JSON attendu")
            length = request.headers.get("content-length", "")
            if not (length.isascii() and length.isdigit()):
                return reply(411, "longueur requise")
            if int(length) > (STT_BODY_MAX if audio else BODY_MAX):
                return reply(413, "corps trop gros")
        response = await call_next(request)
        for key, value in HEADERS.items():
            response.headers[key] = value
        if host == ts_host:  # HTTPS réel (certificat Tailscale) : le navigateur n'essaiera plus jamais le HTTP clair
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError):
        return reply(422, "requête invalide")  # le 422 par défaut renvoie les valeurs reçues

    @app.exception_handler(StarletteHTTPException)
    async def refused(request: Request, exc: StarletteHTTPException):
        return reply(exc.status_code, "requête invalide")  # ex. corps JSON illisible (400) : jamais le texte par défaut

    @app.exception_handler(Exception)
    async def failed(request: Request, exc: Exception):
        return reply(500, "erreur interne")

    @app.get("/api/ping")
    def ping(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        return {"ok": True, "device": auth[1]}

    @app.post("/api/chat", status_code=202)
    def chat_start(body: ChatIn, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        job = chat.start(auth[0], body.text)
        return reply(429, "une demande est déjà en cours") if job is None else {"job": job}

    voices: dict[str, Voice] = {}  # (appareil/client) -> Voice : « hors ligne » ne vaut que pour le micro qui l'a dit
    voice_calls: dict[int, deque[float]] = {}

    stt_slot = threading.BoundedSemaphore(1)  # une transcription à la fois : jamais de file de threads bloqués derrière Whisper

    def voice_over_quota(device: int, cap: int = VOICE_MAX) -> bool:  # compteur commun à /api/voice et /api/stt
        with counters:
            recent = voice_calls.setdefault(device, deque())
            while recent and _now() - recent[0] > QUOTA_WINDOW_S:
                recent.popleft()
            over = len(recent) >= cap
            if not over:
                recent.append(_now())
        return over

    @app.post("/api/stt")
    async def stt_say(request: Request):
        """Audio du micro du téléphone -> texte (Whisper du PC). Ne lance aucune action : le texte repart par /api/chat."""
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        if stt is None:
            return reply(503, "reconnaissance vocale indisponible")
        if voice_over_quota(auth[0], STT_MAX):
            return reply(429, "trop de requêtes", **{"Retry-After": str(QUOTA_WINDOW_S)})
        if not stt_slot.acquire(blocking=False):
            return reply(503, "reconnaissance vocale occupée")
        try:
            from jarvis.core.stt import AudioTooLong, BadAudio, STTError, decode_audio  # import tardif : extra `voice`
            raw, kind = await request.body(), request.headers["content-type"].split(";")[0].strip()

            def run():
                pcm = decode_audio(raw, kind, STT_SECONDS_MAX)  # en mémoire seulement : l'audio ne touche jamais le disque
                return stt.transcribe(pcm), len(pcm) / 16000

            try:
                text, seconds = await run_in_threadpool(run)
            except AudioTooLong:
                code, why = 413, "audio trop long"
            except BadAudio:
                code, why = 422, "audio illisible"
            except STTError:
                code, why = 503, "reconnaissance vocale indisponible"
            else:
                audit.log(f"pwa:{auth[0]}", "stt", {"secondes": round(seconds, 1)}, None, "auto", "voix du téléphone transcrite")  # jamais le texte
                return {"text": text}
            audit.log(f"pwa:{auth[0]}", "stt", {}, None, "refusé", why)
            return reply(code, why)
        finally:
            stt_slot.release()

    @app.post("/api/voice")
    def voice_say(body: VoiceIn, request: Request):
        """Texte reconnu par un client voix -> réponse à lire. Plafond N0/N1 (cf. Voice.handle) ; le texte est une donnée."""
        auth = authenticate(request, allow=("voice", "tv"))
        if isinstance(auth, JSONResponse):
            return auth
        if voice_over_quota(auth[0]):
            return reply(429, "trop de requêtes", **{"Retry-After": str(QUOTA_WINDOW_S)})
        key = f"{auth[0]}/{body.client}"
        with counters:
            voice = voices.get(key)
            if voice is None:
                if len(voices) >= VOICES_MAX:  # `client` est libre : la table ne grandit pas sans limite
                    return reply(429, "trop de micros")
                voice = voices[key] = Voice(chat)  # sans lecteur : la réponse est lue par le client voix du PC
        return {"answer": voice.handle(body.text, key)}

    @app.get("/api/chat/{job_id}")
    def chat_status(job_id: str, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        status = chat.status(auth[0], job_id) if ID.fullmatch(job_id) else None
        return reply(404, "introuvable") if status is None else status

    @app.post("/api/confirm/{confirmation_id}")
    def chat_confirm(confirmation_id: str, body: Confirm, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        assertion = body.assertion.model_dump() if body.assertion else None
        if not (ID.fullmatch(confirmation_id) and chat.approve(auth[0], confirmation_id, body.approve, assertion)):
            return reply(404, "introuvable")  # inconnue, expirée, déjà servie ou d'un autre appareil : même réponse
        return {"ok": True}

    @app.get("/api/audit")
    def audit_rows(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        with audit.lock:  # la connexion du journal est partagée avec les écritures des autres threads
            rows = audit.last(AUDIT_ROWS)
        # Ni la colonne `hash`, ni les arguments : l'écran n'en a pas besoin.
        return {"rows": [{"ts": r[0], "source": r[1], "tool": r[2], "level": r[4], "decision": r[5], "result": (r[6] or "")[:RESULT_MAX]}
                         for r in rows]}

    @app.get("/api/devices")
    def device_list(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        return {"devices": [{"id": r[0], "name": r[1], "created": r[2], "last_used": r[3], "revoked": bool(r[4]), "scope": r[5]}
                            for r in devices.list()], "current": auth[0]}

    @app.post("/api/token")
    def token_rotate(request: Request):  # D6 : la PWA renouvelle son token à chaque ouverture (90 jours glissants)
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        token = devices.rotate(auth[0], request.headers["authorization"].partition(" ")[2])
        if token is None:
            return reply(401, "non autorisé")
        log_read(auth[0], "token_rotate", "token renouvelé")
        return {"token": token}

    @app.post("/api/devices/revoke-others")
    def devices_revoke_others(body: AssertionIn, request: Request):  # téléphone perdu : couper tous les autres d'un coup
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        source = f"pwa:{auth[0]}"
        if not passkeys.verify(auth[0], "devices:revoke", body.assertion.model_dump()):  # un token volé ne chasse pas le propriétaire
            audit.log(source, "device_revoke", {"tous": True}, 3, "refusé", "assertion absente ou invalide")
            return reply(403, "authentification forte requise")
        audit.log(source, "device_revoke", {"tous": True}, 3, "confirmé", "révocation des autres appareils")  # trace d'abord
        revoked = devices.revoke_all(keep=auth[0])
        # Le token de CET appareil change aussi, sans ancien valable : une copie volée sur ce même appareil est coupée.
        return {"revoked": revoked, "token": devices.rotate(auth[0], "", clean=True)}

    @app.get("/api/push")
    def push_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        return {"key": push.public_key(), "subscribed": push.subscribed(auth[0])}

    @app.post("/api/push")
    def push_subscribe(body: Subscription, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        if not push.subscribe(auth[0], body.endpoint, body.p256dh, body.auth):
            return reply(422, "requête invalide")
        audit.log(f"pwa:{auth[0]}", "push_subscribe", {}, None, "auto", "notifications activées")
        return {"ok": True}

    @app.post("/api/push/unsubscribe")
    def push_unsubscribe(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        push.unsubscribe(auth[0])
        audit.log(f"pwa:{auth[0]}", "push_unsubscribe", {}, None, "auto", "notifications désactivées")
        return {"ok": True}

    @app.get("/api/passkey")
    def passkey_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        return {"enabled": bool(ts_host), "registered": passkeys.has(auth[0])}

    @app.post("/api/passkey/options")
    def passkey_options(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        options = passkeys.creation_options(auth[0], auth[1])
        if options is None:  # WebAuthn désactivé, ou aucune fenêtre ouverte depuis le PC pour cet appareil
            return reply(403, "enregistrement non autorisé : lance « python -m jarvis passkey add <id> » sur le PC")
        return options

    @app.post("/api/passkey")
    def passkey_register(body: Attestation, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        ok = passkeys.register(auth[0], body.clientDataJSON, body.attestationObject)
        audit.log(f"pwa:{auth[0]}", "passkey_register", {}, 3, "confirmé" if ok else "refusé",
                  "clé d'accès enregistrée" if ok else "enregistrement refusé")
        return {"ok": True} if ok else reply(403, "enregistrement refusé")

    @app.post("/api/passkey/challenge")
    def passkey_challenge(body: ChallengeIn, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        options = passkeys.request_options(auth[0], body.action)
        return reply(403, "aucune clé d'accès pour cet appareil") if options is None else options

    @app.get("/api/levels")
    def level_list(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        return {"levels": [{"tool": n, "registry": b, "floor": f, "level": e, **levels.label(levels.REGISTRY[n])}
                           for n, b, f, e in levels.table()]}

    @app.post("/api/levels/challenge")
    def level_challenge(body: LevelIn, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        if body.tool not in levels.REGISTRY:  # pas de défi signable pour un outil qui n'existe pas
            return reply(422, "requête invalide")
        options = passkeys.request_options(auth[0], f"level:{body.tool}:{body.level}")
        return reply(403, "aucune clé d'accès pour cet appareil") if options is None else options

    @app.post("/api/levels")
    def level_set(body: LevelIn, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        strong = bool(body.assertion) and passkeys.verify(auth[0], f"level:{body.tool}:{body.level}", body.assertion.model_dump())
        if body.assertion and not strong:
            audit.log(f"pwa:{auth[0]}", "webauthn", {"tool": body.tool, "level": body.level}, 3, "refusé", "assertion invalide")
        try:
            return {"result": levels.set_level(body.tool, body.level, strong_auth=strong, source=f"pwa:{auth[0]}")}
        except PermissionError:  # déjà journalisé par set_level
            return reply(403, "authentification forte requise")
        except ValueError:
            return reply(422, "requête invalide")

    @app.get("/api/dashboard")
    def dashboard_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        return dashboard.snapshot()

    @app.get("/api/tv")
    def tv_state(request: Request):
        """Écran d'accueil de la TV (partagée avec des invités) : météo et nombre de rappels, rien d'autre (N0)."""
        auth = authenticate(request, allow=("tv",))
        if isinstance(auth, JSONResponse):
            return auth
        snap = dashboard.snapshot()
        weather = snap["weather"] or {}
        try:
            due = len(reminders.pending())
        except RuntimeError:
            due = None
        log_read(auth[0], "tv_read", "écran TV lu")
        return {"location": snap["location"], "reminders": due,
                "weather": {k: weather.get(k) for k in ("temp_c", "sky", "min_c", "max_c")} if weather else None}

    @app.get("/api/minipc")
    def minipc_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        return minipc.status(audit, port)

    @app.get("/api/social")
    def social_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        if HAS_PC_TOOLS:
            return with_youtube(social_snapshot(), youtube)
        return social_from_pc()

    voyages_core.on_fetch = lambda ok: audit.log("pwa:voyages", "voyages_sync", {}, 0, "auto", "ok" if ok else "échec")

    @app.get("/api/voyages")
    def voyages_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        return voyages_snapshot()

    @app.post("/api/voyages/destination", status_code=202)
    def voyages_destination(body: Destination, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        job = chat.start(auth[0], f"voyage_destination {body.destination}", ("voyage_destination", body.model_dump()))
        return reply(429, "une demande est déjà en cours") if job is None else {"job": job}

    @app.get("/api/conso")
    def conso_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        return conso_core.snapshot() | {"home": conso_core.home_snapshot(), "advice": conseils.snapshot()}  # lecture N0 du cache local : pas de ligne au journal (comme /api/voyages)

    @app.put("/api/conso/tarif")
    def conso_tarif(body: Tarif, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            conso_core.save_price(body.price_kwh)
        except OSError:
            audit.log(f"pwa:{auth[0]}", "conso_tarif", {}, 1, "auto", "erreur : prix non enregistré")
            return reply(500, "enregistrement impossible")
        audit.log(f"pwa:{auth[0]}", "conso_tarif", {}, 1, "auto", "prix du kWh modifié")  # le montant reste hors journal
        return {"price_kwh": conso_core.load_price()}

    @app.get("/api/finance")
    def finance_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        log_read(auth[0], "finance_read", "rapports financiers lus")
        return finance_snapshot()

    @app.get("/api/finance/bank")
    def bank_state(request: Request):  # route à part : le résumé du dashboard n'appelle que /api/finance, sans données bancaires
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        log_read(auth[0], "bank_read", "comptes bancaires, Ledger et portefeuille lus")
        binance.refresh_if_stale()  # historique Binance relu en tâche de fond au plus une fois par jour
        return {"bank": bank_view(), "crypto": binance.enrich(crypto_view()), "portfolio": portfolio_view()}

    bienetre_core.on_run = lambda ok: audit.log("serve", "bienetre_run", {}, 0, "auto", "ok" if ok else "échec")

    @app.get("/api/bienetre")
    def bienetre_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        log_read(auth[0], "bienetre_read", "bilan de santé du PC lu")
        if HAS_PC_TOOLS:
            return bienetre_core.snapshot()
        try:
            snap = agentlink.call("run", "pc_bienetre", {}, timeout=PANEL_TIMEOUT_S)
            if not isinstance(snap, dict):
                return BIENETRE_OFFLINE
            if snap.pop("started", False):
                audit.log("serve", "bienetre_run", {}, 0, "auto", "lancé sur le PC")
            return snap
        except agentlink.AgentError:
            return BIENETRE_OFFLINE

    @app.get("/api/veille")
    def veille_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        log_read(auth[0], "veille_read", "veille IA lue")
        return veille_snapshot()

    @app.get("/api/memory")
    def memory_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            rows = memory.facts()
        except RuntimeError:
            return reply(503, "indisponible")
        log_read(auth[0], "memory_read", "souvenirs lus")  # le texte ne va jamais au journal
        return {"facts": [{"id": i, "text": t} for i, t in rows]}

    @app.post("/api/memory/forget")
    def memory_forget(body: IdIn, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            n = memory.forget(f"#{body.id}")
        except RuntimeError:
            return reply(503, "indisponible")
        if not n:
            return reply(404, "introuvable")
        audit.log(f"pwa:{auth[0]}", "memory_forget", {}, 1, "auto", f"souvenir {body.id} oublié")
        return {"ok": True}

    @app.get("/api/reminders")
    def reminders_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            rows = reminders.pending()
        except RuntimeError:
            return reply(503, "indisponible")
        log_read(auth[0], "reminder_read", "rappels lus")
        return {"reminders": [{"id": i, "due": due, "label": label, "kind": kind} for i, due, label, kind in rows]}

    @app.post("/api/reminders/cancel")
    def reminders_cancel(body: IdIn, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            done = reminders.cancel(body.id)
        except RuntimeError:
            return reply(503, "indisponible")
        if done is None:
            return reply(404, "introuvable")
        audit.log(f"pwa:{auth[0]}", "reminder_cancel", {}, 1, "auto", f"rappel {body.id} annulé")
        return {"ok": True}

    @app.get("/api/mic")
    def mic_state(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        return {"available": mic is not None, "on": mic is not None and not mic.disabled(), "state": mic.state if mic else None}

    @app.post("/api/mic/challenge")
    def mic_challenge(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        options = passkeys.request_options(auth[0], "mic:on")
        return reply(403, "aucune clé d'accès pour cet appareil") if options is None else options

    @app.post("/api/mic")
    def mic_set(body: MicIn, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        if mic is None:
            return reply(404, "introuvable")
        source = f"pwa:{auth[0]}"
        if not body.on:  # couper est toujours libre
            mic.disable()
            audit.log(source, "mic_switch", {"état": "off"}, None, "auto", "micro coupé")
            return {"on": False}
        # Réarmer = N3 : la signature d'une clé d'accès est toujours exigée, sans clé enregistrée on refuse (un token volé
        # ne rallume jamais le micro ; repli : `python -m jarvis mic on` au terminal).
        if not (passkeys.has(auth[0]) and body.assertion and passkeys.verify(auth[0], "mic:on", body.assertion.model_dump())):
            audit.log(source, "mic_switch", {"état": "on"}, None, "refusé", "clé d'accès requise")
            return reply(403, "authentification forte requise")
        audit.log(source, "mic_switch", {"état": "on"}, None, "auto", "micro autorisé")  # trace d'abord : journal en échec = pas d'écoute
        mic.enable()
        return {"on": True}

    @app.post("/api/enroll")
    def enroll(body: Enroll):
        locked = devices.locked()
        try:
            result = devices.enroll(body.code, body.name)
        except ValueError:
            return reply(422, "requête invalide")
        if result is None:  # même réponse pour un code faux, expiré, déjà utilisé ou verrouillé
            if not locked:  # verrouillé : rien dans l'audit (append-only, il ne se purge pas), constat 3
                audit.log("pwa:?", "enroll", {}, None, "refusé", "code invalide")
            return reply(401, "code invalide")
        audit.log(f"pwa:{result[0]}", "enroll", {"name": body.name.strip()}, None, "auto", "appareil enrôlé")
        return {"id": result[0], "token": result[1]}

    files = {p.name: p for p in web_dir.iterdir() if p.is_file() and p.suffix in WEB_TYPES} if web_dir.is_dir() else {}

    @app.get("/")
    @app.get("/{name}")
    def static(name: str = "index.html"):  # le shell ne contient aucun secret : pas d'authentification
        path = files.get(name)
        if path is None:
            return reply(404, "introuvable")
        return Response(path.read_bytes(), media_type=WEB_TYPES[path.suffix])

    return app


def make_server(devices: Devices, audit: Audit, port: int, chat: Chat | None = None,
                web_dir: Path = WEB_DIR, ts_host: str | None = None, push: Push | None = None, mic=None,
                stt=None) -> uvicorn.Server:
    config = uvicorn.Config(create_app(devices, audit, port, chat, web_dir, ts_host, push, mic, stt), host=HOST, port=port, access_log=False,
                            server_header=False, proxy_headers=False, log_level="warning")
    return uvicorn.Server(config)
