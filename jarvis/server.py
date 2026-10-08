"""Serveur local de la PWA (étape 1 : authentification seulement, aucune route d'outil).

Écoute sur 127.0.0.1 en dur (aucune option) ; l'exposition viendra de `tailscale serve`, jamais d'un port ouvert.
Garde-fous : Host et Origin vérifiés (DNS rebinding, CSRF), pas de CORS, corps borné, en-têtes de sécurité,
erreurs génériques, échecs d'authentification comptés globalement (toutes les requêtes viennent de 127.0.0.1).
"""
import os
import re
import time
from collections import deque
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, StrictBool

from jarvis.core import levels
from jarvis.core.audit import Audit
from jarvis.core.chat import TEXT_MAX, Chat
from jarvis.core.devices import Devices
from jarvis.core.webauthn import Passkeys

HOST = "127.0.0.1"  # volontairement non configurable
BODY_MAX = 8192
AUTH_FAIL_MAX, AUTH_FAIL_WINDOW_S = 10, 60
HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",  # redondant avec frame-ancestors, pour les vieux navigateurs
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}
_now = time.monotonic  # remplacé dans les tests
WEB_DIR = Path(__file__).parent / "web"
# Fichiers statiques : dossier plat, extensions de cette liste seulement. Un chemin ne sert que s'il est EXACTEMENT
# le nom d'un de ces fichiers (jamais de jointure avec la saisie : pas de traversée de chemin).
WEB_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
             ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
             ".webmanifest": "application/manifest+json"}
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


B64 = Field(max_length=1400, pattern=r"^[A-Za-z0-9_-]+$")


class Assertion(BaseModel):
    id: str = Field(max_length=1400, pattern=r"^[A-Za-z0-9_-]+$")
    clientDataJSON: str = B64
    authenticatorData: str = B64
    signature: str = B64


class Confirm(BaseModel):
    approve: StrictBool  # « oui » ou 1 ne confirment rien : seul `true` confirme
    assertion: Assertion | None = None  # N3 : signature WebAuthn du défi de cette demande


class Attestation(BaseModel):
    clientDataJSON: str = B64
    attestationObject: str = Field(max_length=4000, pattern=r"^[A-Za-z0-9_-]+$")


class LevelIn(BaseModel):
    tool: str = Field(max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    level: int = Field(ge=0, le=3, strict=True)
    assertion: Assertion | None = None  # abaisser un niveau = N3 : signature WebAuthn de (outil, niveau)


def create_app(devices: Devices, audit: Audit, port: int, chat: Chat | None = None,
               web_dir: Path = WEB_DIR, ts_host: str | None = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)  # pas de /docs ni de schéma public
    # Host accepté -> Origin attendu pour ce Host. Liste fermée : jamais de joker, jamais de confiance dans l'IP source
    # ni dans les en-têtes Tailscale (derrière `tailscale serve`, tout arrive de 127.0.0.1).
    hosts = {f"{HOST}:{port}": f"http://{HOST}:{port}"}
    if ts_host:
        hosts[ts_host] = f"https://{ts_host}"
    failures: deque[float] = deque()
    passkeys = Passkeys(devices, ts_host)  # sans nom Tailscale (HTTPS), WebAuthn est désactivé : N3 reste refusé
    chat = chat or Chat(audit, passkeys)
    if chat.passkeys is None:  # Chat fourni sans clés (tests) : mêmes clés que les routes
        chat.passkeys = passkeys

    def reply(status: int, detail: str, **extra) -> JSONResponse:
        return JSONResponse({"detail": detail}, status_code=status, headers={**HEADERS, **extra})

    def limited() -> bool:
        while failures and _now() - failures[0] > AUTH_FAIL_WINDOW_S:
            failures.popleft()
        return len(failures) >= AUTH_FAIL_MAX

    def authenticate(request: Request) -> tuple[int, str] | JSONResponse:
        header = request.headers.get("authorization")
        if header is None:  # une page web ne peut pas poser cet en-tête (pas de CORS) : ni compté, ni journalisé,
            return reply(401, "non autorisé")  # sinon elle bloquerait les appareils légitimes (constat 2)
        scheme, _, token = header.partition(" ")
        found = devices.check(token) if scheme == "Bearer" and 0 < len(token) <= 200 else None
        if found is not None:  # un token valide n'est jamais bloqué par le compteur
            return found
        if limited():
            return reply(429, "trop d'échecs", **{"Retry-After": str(AUTH_FAIL_WINDOW_S)})
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
            if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                return reply(415, "JSON attendu")
            length = request.headers.get("content-length", "")
            if not length.isdigit():
                return reply(411, "longueur requise")
            if int(length) > BODY_MAX:
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
        return {"devices": [{"id": r[0], "name": r[1], "created": r[2], "last_used": r[3], "revoked": bool(r[4])}
                            for r in devices.list()], "current": auth[0]}

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

    @app.get("/api/levels")
    def level_list(request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
        return {"levels": [{"tool": n, "registry": b, "floor": f, "level": e} for n, b, f, e in levels.table()]}

    @app.post("/api/levels/challenge")
    def level_challenge(body: LevelIn, request: Request):
        auth = authenticate(request)
        if isinstance(auth, JSONResponse):
            return auth
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
            return {"result": levels.set_level(body.tool, body.level, strong_auth=strong)}
        except PermissionError:  # déjà journalisé par set_level
            return reply(403, "authentification forte requise")
        except ValueError:
            return reply(422, "requête invalide")

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
                web_dir: Path = WEB_DIR, ts_host: str | None = None) -> uvicorn.Server:
    config = uvicorn.Config(create_app(devices, audit, port, chat, web_dir, ts_host), host=HOST, port=port, access_log=False,
                            server_header=False, proxy_headers=False, log_level="warning")
    return uvicorn.Server(config)
