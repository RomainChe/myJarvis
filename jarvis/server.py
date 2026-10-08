"""Serveur local de la PWA (étape 1 : authentification seulement, aucune route d'outil).

Écoute sur 127.0.0.1 en dur (aucune option) ; l'exposition viendra de `tailscale serve`, jamais d'un port ouvert.
Garde-fous : Host et Origin vérifiés (DNS rebinding, CSRF), pas de CORS, corps borné, en-têtes de sécurité,
erreurs génériques, échecs d'authentification comptés globalement (toutes les requêtes viennent de 127.0.0.1).
"""
import os
import re
import time
from collections import deque

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool

from jarvis.core.audit import Audit
from jarvis.core.chat import TEXT_MAX, Chat
from jarvis.core.devices import Devices

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
}
_now = time.monotonic  # remplacé dans les tests
ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def port_from_env() -> int:
    port = int(os.environ.get("JARVIS_PORT") or 8765)
    if not 1024 <= port <= 65535:
        raise ValueError("JARVIS_PORT doit être entre 1024 et 65535")
    return port


class Enroll(BaseModel):
    code: str = Field(max_length=64)
    name: str = Field(max_length=40)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=TEXT_MAX)


class Confirm(BaseModel):
    approve: StrictBool  # « oui » ou 1 ne confirment rien : seul `true` confirme


def create_app(devices: Devices, audit: Audit, port: int, chat: Chat | None = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)  # pas de /docs ni de schéma public
    host, origin = f"{HOST}:{port}", f"http://{HOST}:{port}"
    failures: deque[float] = deque()
    chat = chat or Chat(audit)

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
        if request.headers.get("host") != host:  # DNS rebinding : une page web ne peut pas viser 127.0.0.1
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
        if not (ID.fullmatch(confirmation_id) and chat.approve(auth[0], confirmation_id, body.approve)):
            return reply(404, "introuvable")  # inconnue, expirée, déjà servie ou d'un autre appareil : même réponse
        return {"ok": True}

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

    return app


def make_server(devices: Devices, audit: Audit, port: int, chat: Chat | None = None) -> uvicorn.Server:
    config = uvicorn.Config(create_app(devices, audit, port, chat), host=HOST, port=port, access_log=False,
                            server_header=False, proxy_headers=False, log_level="warning")
    return uvicorn.Server(config)
