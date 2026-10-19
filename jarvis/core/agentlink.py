"""Lien Core ↔ agent PC (docs/MIGRATION_CORE_MINIPC.md, lot 3).

Le Core garde la garde de permissions, les confirmations et le journal d'audit ; l'agent n'exécute que les outils du
catalogue. Chaque message est signé HMAC-SHA256 (clé `agent_key`), horodaté et à nonce unique ; la réponse est signée aussi.
"""
import hashlib
import hmac
import json
import os
import secrets as rand
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

import keyring.errors

from .host import trusted_base_url
from .secrets import get_secret
from .tools import REGISTRY, Level, masked, tool

SKEW_S = 30
BODY_MAX = 65536
TIMEOUT_S = 30
URL_ENV = "JARVIS_AGENT_URL"
CATALOG = Path(__file__).resolve().parents[1] / "pc_catalog.json"
TYPES = {"str": str, "int": int, "float": float, "bool": bool}
FLAGS = ("private", "external", "taint_blocked", "owner_only")
OPS = ("run", "describe")
REQ, REP = b"req\n", b"rep\n"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # le corps signé ne doit jamais partir vers un autre hôte
        return None


_open = urllib.request.build_opener(_NoRedirect).open


class AgentError(RuntimeError):
    """Agent injoignable, clé absente, signature refusée ou outil en erreur : jamais une action « supposée faite »."""


def sign(key: str, data: bytes, direction: bytes) -> str:
    """`direction` (REQ ou REP) : une requête signée ne vaut jamais comme réponse."""
    return hmac.new(key.encode(), direction + data, hashlib.sha256).hexdigest()


def verify(key: str, data: bytes, sig: str | None, direction: bytes) -> bool:
    return hmac.compare_digest(sign(key, data, direction).encode(), (sig or "").encode())


class Replay:
    """Refuse un horodatage trop éloigné de l'horloge ou un nonce déjà vu dans la fenêtre."""

    def __init__(self, now: Callable[[], float] = time.time):
        self._now, self._seen, self._lock = now, {}, threading.Lock()
        self._start = now()  # cache vide au redémarrage : une requête capturée avant n'est plus rejouable

    def fresh(self, ts: Any, nonce: Any) -> bool:
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not isinstance(nonce, str)                 or not 16 <= len(nonce) <= 64:
            return False
        t = self._now()
        if not abs(t - ts) <= SKEW_S or ts < self._start:  # forme négative : NaN est refusé aussi
            return False
        with self._lock:
            self._seen = {n: e for n, e in self._seen.items() if e > t}
            if nonce in self._seen:
                return False
            self._seen[nonce] = t + 2 * SKEW_S
        return True


# ---- catalogue : les métadonnées des outils PC, connues du Core même PC éteint ----

def build_catalog(registry, names) -> list[dict]:
    out = []
    for n in sorted(names):
        t = registry[n]
        out.append({"name": n, "description": t.description, "level": int(t.level),
                    "params": {k: v.__name__ for k, v in t.params.items()}, "hidden": list(t.hidden),
                    "describe": t.describe is not None, **{f: getattr(t, f) for f in FLAGS}})
    return out


# ---- côté agent ----

def handle(key: str, replay: Replay, raw: bytes, sig: str | None, registry, allowed, lock, log) -> tuple[bool, dict]:
    """(signé ?, réponse). Faux : à renvoyer en 401 sans corps. La garde (niveaux, confirmations) est celle du Core."""
    if len(raw) > BODY_MAX or not verify(key, raw, sig, REQ):
        return False, {}
    try:
        req = json.loads(raw)
        op, name, args, nonce = req["op"], req["tool"], req["args"], req["nonce"]
        if not replay.fresh(req["ts"], nonce) or op not in OPS or type(args) is not dict or type(name) is not str:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return False, {}
    if name not in allowed or name not in registry:
        return True, {"nonce": nonce, "ok": False, "error": f"outil inconnu de l'agent : {name[:60]}"}
    t = registry[name]
    try:
        t.check_args(args)
        if op == "describe":
            result = t.describe(**args) if t.describe else ""
        else:
            with lock:  # les outils appellent l'API Windows : un à la fois
                result = t.run(**args)
        json.dumps(result)
        reply = {"nonce": nonce, "ok": True, "result": result}
    except Exception as e:  # noqa: BLE001 (l'erreur remonte au Core, qui la journalise)
        reply = {"nonce": nonce, "ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    log(op, name, masked(args, t.hidden), reply["ok"])
    return True, reply


# ---- côté Core ----

def agent_url() -> str | None:
    raw = os.environ.get(URL_ENV, "").strip().rstrip("/")
    return trusted_base_url(raw, URL_ENV) if raw else None


def call(op: str, name: str, args: dict, *, urlopen=_open, timeout: float = TIMEOUT_S) -> Any:
    base = agent_url()
    if not base:
        raise AgentError("agent PC non configuré")
    try:
        key = get_secret("agent_key")
    except keyring.errors.KeyringError:
        key = None
    if not key:
        raise AgentError("clé de l'agent PC absente")
    nonce = rand.token_hex(16)
    body = json.dumps({"op": op, "tool": name, "args": args, "ts": time.time(), "nonce": nonce}).encode()
    req = urllib.request.Request(base + "/call", body, {"Content-Type": "application/json", "X-Jarvis-Sig": sign(key, body, REQ)})
    try:
        with urlopen(req, timeout=timeout) as r:
            raw, sig = r.read(BODY_MAX + 1), r.headers.get("X-Jarvis-Sig")
    except OSError as e:  # refus, délai, 401 : le PC est éteint, la clé diffère ou l'horloge dérive
        raise AgentError(f"PC injoignable ({type(e).__name__})") from None
    if len(raw) > BODY_MAX or not verify(key, raw, sig, REP):
        raise AgentError("réponse de l'agent non signée")
    try:
        reply = json.loads(raw)
        ok, result, echoed = reply["ok"], reply.get("result"), reply["nonce"]
    except (ValueError, KeyError, TypeError):
        raise AgentError("réponse de l'agent illisible") from None
    if echoed != nonce:
        raise AgentError("réponse de l'agent rejouée")
    if ok is not True:
        raise AgentError(str(reply.get("error", "erreur de l'agent"))[:200])
    return result


def _proxy(name: str, with_describe: bool, e: dict) -> None:
    describe = (lambda **a: call("describe", name, a)) if with_describe else None
    tool(name, e["description"], Level(e["level"]), hidden=tuple(e["hidden"]), describe=describe,
         **{f: e[f] for f in FLAGS}, **{k: TYPES[v] for k, v in e["params"].items()})(lambda **a: call("run", name, a))


def register_proxies(catalog: Path = CATALOG) -> int:
    """Enregistre les outils PC du catalogue, exécutés par l'agent. Idempotent. Sans `JARVIS_AGENT_URL`, chaque appel
    échoue clairement (« agent PC non configuré ») : le catalogue du routeur reste valide sur tout Core."""
    todo = [e for e in json.loads(catalog.read_text(encoding="utf-8")) if e["name"] not in REGISTRY]
    for e in todo:
        _proxy(e["name"], e["describe"], e)
    return len(todo)
