"""Où tourne ce Core : les outils PC (Windows, ctypes) ne se chargent que sur le PC principal.

Core sur le mini-PC (Linux) : `HAS_PC_TOOLS` est faux, les outils PC viendront de l'agent PC (docs/MIGRATION_CORE_MINIPC.md,
lot 3). `JARVIS_PC_TOOLS=0` force le même mode sous Windows (essais).
"""
import ipaddress
import os
import sys
from urllib.parse import urlsplit

HAS_PC_TOOLS = sys.platform == "win32" and os.environ.get("JARVIS_PC_TOOLS") != "0"


def trusted_host(host: str) -> bool:
    """Boucle locale, `localhost`, IP Tailscale (100.64.0.0/10) ou `*.ts.net` : seuls hôtes où un secret ou un prompt part en clair."""
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return host == "localhost" or host.endswith(".ts.net")


def trusted_base_url(url: str, var: str) -> str:
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not trusted_host(u.hostname or "") or u.username or u.path or u.query or u.fragment:
        raise ValueError(f"{var} : http(s)://hôte[:port] avec boucle locale, IP Tailscale ou *.ts.net")
    return url
