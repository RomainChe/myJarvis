"""Portefeuille Ledger (Phase 6 point 8, piste Ledger), lecture seule : soldes BTC et ETH en euros, onglet Finances.

Config : `~/.jarvis/crypto.json` (`{"btc": "xpub…", "eth": "0x…"}`, l'une ou l'autre), jamais dans le dépôt. Jamais de seed
ni de clé privée : seule la clé publique étendue du compte Bitcoin (Native SegWit, m/84'/0'/0') et l'adresse Ethereum.
Les adresses BTC sont dérivées sur le PC (BIP32 + bech32) ; l'xpub ne quitte jamais le PC, seules les adresses partent vers
mempool.space (comme dans n'importe quel explorateur). ETH : nœud public, `eth_getBalance`. Cours : CoinGecko. Tout sans clé.
Rien n'est écrit sur disque : cache en mémoire, rafraîchi en tâche de fond au plus toutes les 15 min. Seuls des nombres sortent
des réponses. Pas d'outil LLM ; la lecture est journalisée par la route (`bank_read`).
"""
import hashlib
import hmac
import json
import math
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec

CONFIG = Path.home() / ".jarvis" / "crypto.json"
MEMPOOL = "https://mempool.space/api/address/"
ETH_RPC = "https://ethereum-rpc.publicnode.com"
PRICES = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=eur"
TTL_S, GAP, MAX_ADDR, PAUSE_S, DEADLINE_S = 900, 20, 500, 1.0, 600  # GAP = limite d'écart BIP44 (celle de Ledger Live) ; PAUSE_S : quota de mempool.space
VERSIONS = (bytes.fromhex("0488b21e"), bytes.fromhex("04b24746"))  # xpub (affichée par Ledger Live), zpub
ETH_ADDR = re.compile(r"0x[0-9a-fA-F]{40}")
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
P = 2**256 - 2**32 - 977  # corps de secp256k1


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # une redirection (vers http:// ou un autre hôte) emporterait les adresses
        return None


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
_lock = threading.Lock()
_state = {"at": None, "data": None, "busy": False}


# ---- configuration ------------------------------------------------------------------------------------------------------

def parse_xpub(s: str) -> tuple[bytes, bytes]:
    """xpub/zpub de compte (profondeur 3) -> (chain code, clé publique compressée). ValueError si invalide."""
    if len(s) != 111:
        raise ValueError("longueur")
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)  # ValueError si caractère hors base58
    raw = n.to_bytes(82, "big")
    body, check = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] != check:
        raise ValueError("somme de contrôle")
    if body[:4] not in VERSIONS or body[4] != 3 or body[45] not in (2, 3):
        raise ValueError("xpub de compte Bitcoin attendue")
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), body[45:78])  # ValueError si le point n'est pas sur la courbe
    return body[13:45], body[45:78]


def load_config(path: Path = CONFIG) -> dict | None:
    """{"btc": (chain code, clé) | None, "eth": adresse | None, "errors": [...]}, ou None si aucun fichier."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"btc": None, "eth": None, "errors": ["crypto.json illisible"]}
    raw = raw if isinstance(raw, dict) else {}
    cfg = {"btc": None, "eth": None, "errors": []}
    if raw.get("btc"):
        try:
            cfg["btc"] = parse_xpub(str(raw["btc"]).strip())
        except ValueError:
            cfg["errors"].append("Bitcoin : xpub invalide")
    if raw.get("eth"):
        eth = str(raw["eth"]).strip()
        if ETH_ADDR.fullmatch(eth):
            cfg["eth"] = eth
        else:
            cfg["errors"].append("Ethereum : adresse invalide")
    return cfg


# ---- dérivation BIP32 (publique) et adresses bech32 ---------------------------------------------------------------------

def _point(pub: bytes) -> tuple[int, int]:
    x = int.from_bytes(pub[1:], "big")
    y = pow((x**3 + 7) % P, (P + 1) // 4, P)
    return x, y if y % 2 == pub[0] % 2 else P - y


def child(key: tuple[bytes, bytes], i: int) -> tuple[bytes, bytes]:
    """CKDpub non durci : (chain code, clé compressée) de l'enfant i."""
    code, pub = key
    h = hmac.new(code, pub + i.to_bytes(4, "big"), hashlib.sha512).digest()
    t = ec.derive_private_key(int.from_bytes(h[:32], "big"), ec.SECP256K1()).public_key().public_numbers()  # IL·G
    (x1, y1), (x2, y2) = _point(pub), (t.x, t.y)
    if x1 == x2:  # doublage ou point à l'infini : probabilité ≈ 2^-128, BIP32 dit de passer à l'index suivant
        raise ValueError("index invalide")
    lam = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x = (lam * lam - x1 - x2) % P
    y = (lam * (x1 - x) - y1) % P
    return h[32:], bytes([2 + y % 2]) + x.to_bytes(32, "big")


def _polymod(values) -> int:
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i, g in enumerate((0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)):
            chk ^= g if top >> i & 1 else 0
    return chk


def p2wpkh(pub: bytes) -> str:
    """Adresse Native SegWit (bc1q…) d'une clé publique compressée."""
    h = int.from_bytes(hashlib.new("ripemd160", hashlib.sha256(pub).digest()).digest(), "big")
    data = [0] + [h >> (155 - 5 * k) & 31 for k in range(32)]
    hrp = [3, 3, 0, 2, 3]  # « bc » étendu (BIP173)
    chk = _polymod(hrp + data + [0] * 6) ^ 1
    return "bc1" + "".join(BECH32[d] for d in data + [chk >> 5 * (5 - k) & 31 for k in range(6)])


# ---- lecture réseau -----------------------------------------------------------------------------------------------------

def _get(url: str, body: dict | None = None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    for attempt in (0, 1):
        try:
            with _opener.open(req, timeout=5) as r:  # sans proxy
                return json.loads(r.read(1_000_000))
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt:
                raise
            time.sleep(10)  # quota dépassé : une seule nouvelle tentative


def _sats(stats) -> int:
    stats = stats if isinstance(stats, dict) else {}
    a, b = stats.get("funded_txo_sum"), stats.get("spent_txo_sum")
    if not (type(a) is int and type(b) is int):
        raise ValueError("réponse inattendue")
    return a - b


def btc_balance(key: tuple[bytes, bytes], get=_get) -> float:
    """Somme des adresses de réception (0) et de monnaie (1), arrêt après GAP adresses jamais utilisées."""
    sats, deadline = 0, time.monotonic() + DEADLINE_S
    for chain in (0, 1):
        ck, gap = child(key, chain), 0
        for i in range(MAX_ADDR):  # ponytail: un appel par adresse (~45 pour un petit portefeuille), lot si l'explorateur limite
            if time.monotonic() > deadline:  # explorateur très lent : abandon plutôt qu'un thread occupé des heures
                raise TimeoutError("lecture trop longue")
            time.sleep(PAUSE_S)
            r = get(MEMPOOL + p2wpkh(child(ck, i)[1]))
            used = any(isinstance(r.get(k), dict) and r[k].get("tx_count") for k in ("chain_stats", "mempool_stats"))
            if not used:
                gap += 1
                if gap >= GAP:
                    break
                continue
            gap = 0
            sats += _sats(r.get("chain_stats")) + _sats(r.get("mempool_stats"))
    return sats / 1e8


def eth_balance(addr: str, get=_get) -> float:
    r = get(ETH_RPC, {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]})
    wei = r.get("result") if isinstance(r, dict) else None
    if not (isinstance(wei, str) and re.fullmatch(r"0x[0-9a-fA-F]{1,64}", wei)):
        raise ValueError("réponse inattendue")
    return int(wei, 16) / 1e18


def prices(get=_get) -> dict:
    r = get(PRICES)
    out = {}
    for sym, cid in (("BTC", "bitcoin"), ("ETH", "ethereum")):
        v = (r.get(cid) or {}).get("eur") if isinstance(r, dict) else None
        out[sym] = float(v) if isinstance(v, (int, float)) and math.isfinite(v) and v > 0 else None  # Infinity = route en 500
    return out


def refresh(cfg: dict, get=_get, previous: dict | None = None) -> dict:
    """Relit chaque actif ; un actif en échec garde sa dernière valeur connue et ajoute une erreur sans détail."""
    old = {a["asset"]: a for a in (previous or {}).get("assets", [])}
    errors = list(cfg["errors"])
    try:
        eur = prices(get)
    except Exception:  # réseau, JSON, réponse inattendue : le cours manque, les quantités restent
        eur, errors = {"BTC": None, "ETH": None}, errors + ["cours indisponible"]
    assets = []
    for sym, name, src, read in (("BTC", "Bitcoin", cfg["btc"], btc_balance), ("ETH", "Ethereum", cfg["eth"], eth_balance)):
        if not src:
            continue
        try:
            amount = read(src, get)
        except Exception:
            errors.append(f"{name} : lecture impossible")
            if sym in old:
                assets.append(old[sym])
            continue
        assets.append({"asset": sym, "name": name, "amount": round(amount, 8),
                       "eur": round(amount * eur[sym], 2) if eur[sym] else None})
    return {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "assets": assets, "errors": errors}


def view(config=load_config, get=_get, clock=time.monotonic,
         start=lambda f: threading.Thread(target=f, daemon=True).start()) -> dict | None:
    """Dernières valeurs connues (aucun appel réseau dans la requête) ; lance un rafraîchissement si elles ont > 15 min.

    None si `crypto.json` est absent. `refreshing` : une lecture est en cours (l'onglet repasse plus tard).
    """
    cfg = config()
    if cfg is None:
        return None

    def run():
        with _lock:
            previous = _state["data"]
        try:
            data = refresh(cfg, get, previous)
        except Exception:  # bug imprévu : anciennes valeurs gardées, busy libéré, nouvelle lecture après TTL_S
            data = {**(previous or {"updated_at": None, "assets": []}), "errors": ["Ledger : lecture impossible"]}
        with _lock:
            _state.update(data=data, busy=False)

    with _lock:
        stale = not _state["busy"] and (_state["at"] is None or clock() - _state["at"] > TTL_S)
        if stale:
            _state.update(at=clock(), busy=True)
    if stale:
        start(run)
    with _lock:
        return {**(_state["data"] or {"updated_at": None, "assets": [], "errors": []}), "refreshing": _state["busy"]}
