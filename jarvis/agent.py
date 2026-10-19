"""Agent PC (service Windows du PC principal) : `python -m jarvis.agent serve|catalog`.

Expose les outils `jarvis/tools/pc/*` au Core du mini-PC (jarvis/core/agentlink.py). Écoute sur l'adresse Tailscale
`JARVIS_AGENT_HOST` (jamais 0.0.0.0), port `JARVIS_AGENT_PORT` (8788). Pare-feu Windows : n'autoriser que le mini-PC.
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import keyring.errors

import jarvis.tools.pc  # noqa: F401  (enregistre les outils PC)
from jarvis.core import agentlink
from jarvis.core.host import trusted_host
from jarvis.core.secrets import get_secret
from jarvis.core.tools import REGISTRY

TRACE = Path.home() / ".jarvis" / "agent.log"
BIND_WAIT_S, BIND_RETRY_S = 180, 5  # au démarrage de Windows, l'adresse Tailscale arrive après la session
PC_TOOLS = frozenset(n for n, t in REGISTRY.items() if t.run.__module__.startswith("jarvis.tools.pc"))


def trace(op: str, name: str, args, ok: bool) -> None:
    """Trace locale de l'agent (le journal d'audit du Core fait foi) : arguments masqués, jamais les résultats."""
    TRACE.parent.mkdir(parents=True, exist_ok=True)
    with TRACE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(time.time()), "op": op, "tool": name, "args": args, "ok": ok}, ensure_ascii=False) + "\n")


def make_handler(key: str):
    replay, lock = agentlink.Replay(), threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        timeout = 10  # un client qui annonce un corps sans l'envoyer ne garde pas son thread

        def log_message(self, *a):  # pas de journal HTTP : la trace est celle de `trace`
            pass

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if self.path != "/call" or not 0 < n <= agentlink.BODY_MAX:
                return self._send(404)
            signed, reply = agentlink.handle(key, replay, self.rfile.read(n), self.headers.get("X-Jarvis-Sig"),
                                             REGISTRY, PC_TOOLS, lock, trace)
            if not signed:
                return self._send(401)
            body = json.dumps(reply).encode()
            self._send(200, body, agentlink.sign(key, body, agentlink.REP))

        def _send(self, code: int, body: bytes = b"", sig: str = ""):
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            if sig:
                self.send_header("X-Jarvis-Sig", sig)
            self.end_headers()
            self.wfile.write(body)

    return Handler


def bind_server(host: str, port: int, handler, *, make=ThreadingHTTPServer, sleep=time.sleep):
    """Serveur lié à host:port ; réessaie tant que l'adresse n'existe pas encore (Tailscale pas prêt), puis abandonne."""
    for _ in range(BIND_WAIT_S // BIND_RETRY_S):
        try:
            return make((host, port), handler)
        except OSError:
            sleep(BIND_RETRY_S)
    return make((host, port), handler)


def main(argv: list[str]) -> int:
    if argv == ["catalog"]:  # régénère jarvis/pc_catalog.json après tout ajout ou changement d'outil PC
        data = json.dumps(agentlink.build_catalog(REGISTRY, PC_TOOLS), indent=1, ensure_ascii=False) + "\n"
        agentlink.CATALOG.write_text(data, encoding="utf-8")
        print(f"{len(PC_TOOLS)} outils écrits dans {agentlink.CATALOG.name}")
        return 0
    if argv != ["serve"]:
        print(__doc__)
        return 2
    host, port = os.environ.get("JARVIS_AGENT_HOST", ""), int(os.environ.get("JARVIS_AGENT_PORT", "8788"))
    if not trusted_host(host):
        print("JARVIS_AGENT_HOST : adresse Tailscale (100.64.0.0/10), *.ts.net ou boucle locale requise")
        return 2
    try:
        key = get_secret("agent_key")
    except keyring.errors.KeyringError:
        key = None
    if not key:
        print("clé absente : python -m jarvis secret set agent_key")
        return 2
    print(f"Agent PC sur {host}:{port} ({len(PC_TOOLS)} outils)")
    bind_server(host, port, make_handler(key)).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
