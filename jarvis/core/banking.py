"""Agrégation bancaire Enable Banking (Phase 6 point 8), lecture seule : soldes et transactions, aucun ordre de paiement.

La clé privée RSA de l'application est trop longue pour le coffre Windows (≈ 1 280 caractères max) : le coffre garde une clé
Fernet (`bank_key`) qui chiffre `~/.jarvis/bank.enc` (identifiant d'application, clé PEM, sessions) et `~/.jarvis/bank-data.enc`
(cache des comptes). Aucun outil LLM ; chaque appel est journalisé par l'appelant (N2). Les messages d'erreur ne contiennent
jamais un corps de réponse, un jeton ou un identifiant de session.
"""
import base64
import http.client
import json
import secrets as rnd
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import keyring.errors
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from jarvis.core.secrets import get_secret, set_secret

API = "https://api.enablebanking.com"
STORE = Path.home() / ".jarvis" / "bank.enc"
CACHE = Path.home() / ".jarvis" / "bank-data.enc"
TIMEOUT, MAX_BYTES, MAX_PAGES, MAX_TX = 20, 5_000_000, 20, 2000
DAYS = 90  # historique lu, et durée de consentement demandée (Trade Republic plafonne à 90 j)
JWT_TTL = 3600  # s (Enable Banking refuse > 24 h)


class BankError(Exception):
    """Message sans jeton, session ni corps de réponse."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # le JWT ne part que vers API
        return None


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


# ---- stockage chiffré ---------------------------------------------------------------------------------------------------

def _fernet(create: bool = False) -> Fernet:
    key = get_secret("bank_key")
    if not key:
        if not create:
            raise BankError("aucune configuration : python -m jarvis bank key <app_id> <fichier.pem> <redirect_url>")
        key = Fernet.generate_key().decode()
        set_secret("bank_key", key)
    return Fernet(key.encode())


def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(_fernet().decrypt(path.read_bytes()))
    except (InvalidToken, ValueError):
        raise BankError(f"{path.name} illisible (clé du coffre changée ?)") from None


def _save(path: Path, data, create: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(_fernet(create).encrypt(json.dumps(data).encode()))
    tmp.replace(path)


def _id_ok(v) -> bool:
    """Identifiant inséré dans un chemin d'URL : court, alphanumérique et « - » seulement."""
    return isinstance(v, str) and 0 < len(v) <= 100 and all(c.isascii() and (c.isalnum() or c == "-") for c in v)


def configure(app_id: str, pem: bytes, redirect: str) -> None:
    """Range l'application dans `bank.enc` (le .pem d'origine est à supprimer par le propriétaire ensuite)."""
    if not _id_ok(app_id):
        raise BankError("identifiant d'application invalide")
    try:
        key = serialization.load_pem_private_key(pem, password=None)
    except (ValueError, TypeError):
        raise BankError("clé PEM illisible (clé privée RSA sans mot de passe attendue)") from None
    if not isinstance(key, rsa.RSAPrivateKey):
        raise BankError("la clé doit être RSA")
    if urllib.parse.urlsplit(redirect).scheme != "https":
        raise BankError("redirect_url doit être en https (celle déclarée dans l'application Enable Banking)")
    store = _load(STORE, {})
    store.update(app_id=app_id, pem=pem.decode(), redirect=redirect)
    store.setdefault("sessions", [])
    _save(STORE, store, create=True)


# ---- API ----------------------------------------------------------------------------------------------------------------

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jwt(app_id: str, pem: str, now: int | None = None) -> str:
    now = int(time.time()) if now is None else now
    head = _b64(json.dumps({"typ": "JWT", "alg": "RS256", "kid": app_id}).encode())
    body = _b64(json.dumps({"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": now, "exp": now + JWT_TTL}).encode())
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    sig = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{_b64(sig)}"


def _call(store: dict, method: str, path: str, body: dict | None = None, query: dict | None = None) -> dict:
    url = API + path + ("?" + urllib.parse.urlencode(query) if query else "")
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {jwt(store['app_id'], store['pem'])}", "Content-Type": "application/json"})
    try:
        with _opener.open(req, timeout=TIMEOUT) as r:
            raw = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise BankError({401: "application refusée (identifiant ou clé)", 403: "accès refusé (consentement expiré ou compte non lié)",
                         404: "introuvable", 422: "demande refusée par la banque ou consentement expiré",
                         429: "trop de requêtes (limite de la banque : réessayer demain)"}.get(e.code, f"Enable Banking a répondu {e.code}")) from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise BankError("Enable Banking injoignable") from None
    if len(raw) > MAX_BYTES:
        raise BankError("réponse trop volumineuse")
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise BankError("réponse illisible") from None
    if not isinstance(data, dict):
        raise BankError("réponse inattendue")
    return data


# ---- liaison d'une banque -----------------------------------------------------------------------------------------------

def start_link(bank: str, country: str = "FR") -> dict:
    """POST /auth : renvoie {url, state, aspsp} ; le propriétaire ouvre l'URL puis colle l'adresse de retour dans `finish_link`."""
    store = _load(STORE, None)
    if not store:
        raise BankError("aucune configuration : python -m jarvis bank key …")
    aspsps = _call(store, "GET", "/aspsps", query={"country": country.upper()}).get("aspsps") or []
    found = [a for a in aspsps if isinstance(a, dict) and str(a.get("name", "")).casefold() == bank.casefold()]
    if not found:
        near = sorted(str(a.get("name")) for a in aspsps if isinstance(a, dict) and bank.casefold() in str(a.get("name", "")).casefold())
        raise BankError(f"banque inconnue en {country.upper()}" + (f" ; proches : {', '.join(near[:10])}" if near else ""))
    aspsp = found[0]
    max_s = aspsp.get("maximum_consent_validity")
    seconds = min(DAYS * 86400, max_s if isinstance(max_s, int) and max_s > 0 else DAYS * 86400) - 60
    valid = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    state = rnd.token_urlsafe(16)
    r = _call(store, "POST", "/auth", body={"access": {"valid_until": valid}, "aspsp": {"name": aspsp["name"], "country": aspsp["country"]},
                                             "state": state, "redirect_url": store["redirect"], "psu_type": "personal"})
    if not isinstance(r.get("url"), str) or not r["url"].startswith("https://"):
        raise BankError("réponse inattendue")
    return {"url": r["url"], "state": state, "aspsp": {"name": aspsp["name"], "country": aspsp["country"]}}


def finish_link(link: dict, returned_url: str) -> int:
    """Adresse de retour collée → POST /sessions ; garde l'id de session et les comptes. Renvoie le nombre de comptes."""
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(returned_url.strip()).query)
    if q.get("state") != [link["state"]]:
        raise BankError("adresse de retour invalide (state différent : lien d'une autre demande ?)")
    if "error" in q or not q.get("code") or len(q["code"][0]) > 2000:
        raise BankError("autorisation refusée ou annulée à la banque")
    store = _load(STORE, None)
    if not store:
        raise BankError("configuration disparue : python -m jarvis bank key …")
    r = _call(store, "POST", "/sessions", body={"code": q["code"][0]})
    accounts = [_account(a) for a in r.get("accounts") or [] if isinstance(a, dict) and _id_ok(a.get("uid"))]
    if not isinstance(r.get("session_id"), str) or not accounts:
        raise BankError("aucun compte autorisé (en mode restreint : lier d'abord les comptes dans le Control Panel)")
    until = (r.get("access") or {}).get("valid_until")
    sessions = [s for s in store["sessions"] if s["bank"] != link["aspsp"]["name"]]  # une session par banque : la nouvelle remplace
    sessions.append({"id": r["session_id"], "bank": link["aspsp"]["name"], "country": link["aspsp"]["country"],
                     "valid_until": until if isinstance(until, str) else None, "accounts": accounts})
    store["sessions"] = sessions
    _save(STORE, store)
    return len(accounts)


def _account(a: dict) -> dict:
    iban = str((a.get("account_id") or {}).get("iban") or "")
    name = str(a.get("name") or a.get("product") or "Compte")[:40]
    return {"uid": a["uid"], "name": name + (f" ••{iban[-4:]}" if iban else ""), "currency": str(a.get("currency") or "EUR")[:3]}


# ---- lecture ------------------------------------------------------------------------------------------------------------

def status() -> list[dict]:
    """Sessions connues : banque, nombre de comptes, jours de consentement restants (sans identifiant)."""
    out = []
    for s in (_load(STORE, None) or {}).get("sessions", []):
        days = None
        try:
            days = (datetime.fromisoformat(s["valid_until"]) - datetime.now(timezone.utc)).days
        except (TypeError, ValueError):
            pass
        out.append({"bank": s["bank"], "accounts": len(s["accounts"]), "days_left": days})
    return out


def _amount(x: dict) -> float | None:
    try:
        return round(float(x.get("amount")), 2)
    except (TypeError, ValueError, AttributeError):  # x absent ou pas un dict
        return None


def _tx(t) -> dict | None:
    if not isinstance(t, dict):
        return None
    amount = _amount(t.get("transaction_amount"))
    if amount is None:
        return None
    if t.get("credit_debit_indicator") == "DBIT":
        amount = -abs(amount)
    other = t.get("creditor") if amount < 0 else t.get("debtor")
    other = other if isinstance(other, dict) else {}
    info = t.get("remittance_information") or []
    label = str(other.get("name") or (info[0] if isinstance(info, list) and info else "") or "")[:80]
    return {"date": str(t.get("booking_date") or t.get("value_date") or "")[:10], "amount": amount, "label": label}


def _balance(balances: list) -> float | None:
    """Solde comptable (CLBD) de préférence, sinon disponible, sinon le premier."""
    by = {b.get("balance_type"): b for b in balances if isinstance(b, dict)}
    for kind in ("CLBD", "ITAV", "XPCD", "ITBD"):
        if kind in by:
            return _amount(by[kind].get("balance_amount"))
    return _amount(balances[0].get("balance_amount")) if balances and isinstance(balances[0], dict) else None


def fetch(today: date | None = None) -> dict:
    """Lit soldes et transactions des `DAYS` derniers jours de chaque compte lié, écrit le cache chiffré.

    Renvoie {"accounts": n, "transactions": n, "errors": [banque : message]} ; une banque en échec n'empêche pas les autres.
    """
    store = _load(STORE, None)
    if not store or not store.get("sessions"):
        raise BankError("aucune banque liée : python -m jarvis bank link \"<banque>\"")
    since = ((today or date.today()) - timedelta(days=DAYS)).isoformat()
    accounts, errors = [], []
    for s in store["sessions"]:
        try:
            for a in s["accounts"]:
                bal = _call(store, "GET", f"/accounts/{a['uid']}/balances").get("balances")
                bal = bal if isinstance(bal, list) else []
                txs, key = [], None
                for _ in range(MAX_PAGES):  # ponytail: pages bornées, MAX_PAGES × page banque suffit pour 90 j de compte perso
                    r = _call(store, "GET", f"/accounts/{a['uid']}/transactions", query={"date_from": since, **({"continuation_key": key} if key else {})})
                    page = r.get("transactions")
                    txs += [x for x in map(_tx, page if isinstance(page, list) else []) if x]
                    key = r.get("continuation_key")
                    if not key or len(txs) >= MAX_TX:
                        break
                accounts.append({"bank": s["bank"], "name": a["name"], "currency": a["currency"], "balance": _balance(bal),
                                 "transactions": sorted(txs[:MAX_TX], key=lambda x: x["date"], reverse=True)})
        except BankError as e:
            errors.append(f"{s['bank']} : {e}")
    if accounts:
        _save(CACHE, {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "accounts": accounts})
    return {"accounts": len(accounts), "transactions": sum(len(a["transactions"]) for a in accounts), "errors": errors}



def view(limit: int = 30) -> dict | None:
    """Pour l'onglet Finances : soldes par compte et les `limit` dernières opérations, sans uid ni session.

    None si rien n'a encore été récupéré ou si le cache est illisible (coffre indisponible) : l'onglet reste utilisable.
    """
    try:
        data = _load(CACHE, None)
    except (BankError, keyring.errors.KeyringError):
        return None
    if not data:
        return None
    accounts = data.get("accounts") or []
    txs = [dict(t, account=f"{a['bank']} · {a['name']}", currency=a["currency"]) for a in accounts for t in a["transactions"]]
    return {"fetched_at": data.get("fetched_at"),
            "accounts": [{k: a[k] for k in ("bank", "name", "currency", "balance")} for a in accounts],
            "transactions": sorted(txs, key=lambda t: t["date"], reverse=True)[:limit]}
