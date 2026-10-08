"""WebAuthn minimal (clés d'accès) : seule source de `strong_auth=True` pour les actions N3 et pour abaisser un niveau.

- Algorithme unique ES256 (P-256), attestation « none », vérification de l'utilisateur (biométrie/PIN) obligatoire.
- Le RP ID est le nom Tailscale du PC : WebAuthn est inutilisable (désactivé) sur http://127.0.0.1.
- Un défi est aléatoire, lié à (appareil, action) côté serveur, valable 60 s, à usage unique même si la vérification échoue.
- Enregistrer une clé exige une fenêtre de 120 s ouverte depuis le PC (`python -m jarvis passkey add <id>`) : un token
  volé ne suffit pas à ajouter sa propre clé.
"""
import base64
import hashlib
import json
import secrets
import sqlite3
import threading
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

_now = time.monotonic  # remplacé dans les tests
_wall = time.time
CHALLENGE_TTL_S = 60
WINDOW_TTL_S = 120
CHALLENGES_MAX = 50
CHALLENGES_PER_DEVICE = 5  # un appareil ne peut pas évincer les défis des autres
UP, UV, AT, ED = 0x01, 0x04, 0x40, 0x80

SCHEMA = """
CREATE TABLE IF NOT EXISTS credentials (
    cred_id BLOB PRIMARY KEY,
    device_id INTEGER NOT NULL,
    x BLOB NOT NULL,
    y BLOB NOT NULL,
    sign_count INTEGER NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS passkey_windows (device_id INTEGER PRIMARY KEY, expires REAL NOT NULL);
"""


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    if not isinstance(text, str) or not text.isascii():
        raise ValueError("base64url invalide")
    return base64.b64decode(text.replace("-", "+").replace("_", "/") + "=" * (-len(text) % 4), validate=True)


def cbor(data: bytes, pos: int = 0, depth: int = 0):
    """Décodeur CBOR minimal (entiers, octets, texte, tableaux, tables) : (valeur, position suivante). Le reste est refusé."""
    if depth > 8 or pos >= len(data):
        raise ValueError("CBOR invalide")
    kind, info = data[pos] >> 5, data[pos] & 31
    pos += 1
    if info < 24:
        n = info
    elif info in (24, 25, 26):
        size = 1 << (info - 24)
        if pos + size > len(data):
            raise ValueError("CBOR invalide")
        n, pos = int.from_bytes(data[pos:pos + size], "big"), pos + size
    else:  # 27 (64 bits), 28-30 réservés, 31 indéfini : jamais produits par un authentificateur WebAuthn
        raise ValueError("CBOR non pris en charge")
    if kind == 0:
        return n, pos
    if kind == 1:
        return -1 - n, pos
    if kind in (2, 3):
        if pos + n > len(data):
            raise ValueError("CBOR invalide")
        raw = data[pos:pos + n]
        return (raw if kind == 2 else raw.decode()), pos + n
    if kind == 4 or kind == 5:
        if n > 32:
            raise ValueError("CBOR trop grand")
        items = []
        for _ in range(n * (2 if kind == 5 else 1)):
            item, pos = cbor(data, pos, depth + 1)
            items.append(item)
        return (items, pos) if kind == 4 else (dict(zip(items[::2], items[1::2])), pos)
    raise ValueError("CBOR non pris en charge")


class Passkeys:
    def __init__(self, devices, rp_id: str | None):
        self.devices, self.rp_id = devices, rp_id
        self.challenges: dict[str, tuple[int, str, float]] = {}
        self.lock = threading.Lock()
        with devices.lock:
            devices.db.executescript(SCHEMA)

    # ---- fenêtre d'enregistrement (ouverte depuis le PC seulement) -------------------------------
    def open_window(self, device_id: int) -> bool:
        with self.devices.lock:
            if self.devices.db.execute("SELECT 1 FROM devices WHERE id = ? AND revoked = 0", (device_id,)).fetchone() is None:
                return False
            self.devices.db.execute("DELETE FROM passkey_windows WHERE expires < ?", (_wall(),))
            self.devices.db.execute("INSERT OR REPLACE INTO passkey_windows VALUES (?, ?)", (device_id, _wall() + WINDOW_TTL_S))
        return True

    def _window_open(self, device: int) -> bool:
        with self.devices.lock:
            return self.devices.db.execute("SELECT 1 FROM passkey_windows WHERE device_id = ? AND expires >= ?",
                                           (device, _wall())).fetchone() is not None

    # ---- défis ------------------------------------------------------------------------------------
    def _challenge(self, device: int, action: str) -> str:
        now, challenge = _now(), b64u(secrets.token_bytes(32))
        with self.lock:
            for k in [k for k, v in self.challenges.items() if v[2] < now]:
                del self.challenges[k]
            own = [k for k, v in self.challenges.items() if v[0] == device]
            if len(own) >= CHALLENGES_PER_DEVICE:
                del self.challenges[own[0]]
            if len(self.challenges) >= CHALLENGES_MAX:
                del self.challenges[next(iter(self.challenges))]
            self.challenges[challenge] = (device, action, now + CHALLENGE_TTL_S)
        return challenge

    def _credentials(self, device: int) -> list[bytes]:
        with self.devices.lock:
            return [r[0] for r in self.devices.db.execute(
                "SELECT cred_id FROM credentials c JOIN devices d ON d.id = c.device_id "
                "WHERE c.device_id = ? AND d.revoked = 0", (device,))]

    def has(self, device: int) -> bool:
        return bool(self.rp_id) and bool(self._credentials(device))

    def request_options(self, device: int, action: str) -> dict | None:
        """Options de navigator.credentials.get pour (appareil, action) ; None sans clé enregistrée."""
        ids = self._credentials(device)
        if not self.rp_id or not ids:
            return None
        return {"challenge": self._challenge(device, action), "rpId": self.rp_id, "userVerification": "required",
                "timeout": CHALLENGE_TTL_S * 1000, "allowCredentials": [{"type": "public-key", "id": b64u(i)} for i in ids]}

    def creation_options(self, device: int, name: str) -> dict | None:
        """Options de navigator.credentials.create ; None si le PC n'a pas ouvert de fenêtre pour cet appareil."""
        if not self.rp_id or not self._window_open(device):
            return None
        return {"challenge": self._challenge(device, "register"), "rp": {"id": self.rp_id, "name": "JARVIS"},
                "user": {"id": b64u(device.to_bytes(8, "big")), "name": name, "displayName": name},
                "pubKeyCredParams": [{"type": "public-key", "alg": -7}], "attestation": "none",
                "authenticatorSelection": {"userVerification": "required", "residentKey": "discouraged"},
                "timeout": CHALLENGE_TTL_S * 1000,
                "excludeCredentials": [{"type": "public-key", "id": b64u(i)} for i in self._credentials(device)]}

    def _client_data(self, device: int, action: str, kind: str, raw: bytes) -> bool:
        """Défi non expiré, à usage unique, lié à (appareil, action), avec le bon type et la bonne origine."""
        try:
            data = json.loads(raw)
            record = self._pop(data["challenge"])
            return (data["type"] == kind and data["origin"] == f"https://{self.rp_id}" and data.get("crossOrigin") is not True
                    and record is not None and record[:2] == (device, action) and record[2] >= _now())
        except (ValueError, KeyError, TypeError):
            return False

    def _pop(self, challenge):
        with self.lock:
            return self.challenges.pop(challenge, None) if isinstance(challenge, str) else None

    def _auth_data_ok(self, auth: bytes) -> bool:
        return len(auth) >= 37 and auth[:32] == hashlib.sha256(self.rp_id.encode()).digest() and auth[32] & (UP | UV) == UP | UV

    # ---- enregistrement ---------------------------------------------------------------------------
    def register(self, device: int, clientDataJSON: str, attestationObject: str) -> bool:  # noqa: N803 (noms du JSON WebAuthn)
        try:
            client, att = unb64u(clientDataJSON), cbor(unb64u(attestationObject))[0]
            auth = att["authData"]
            ok = (self.rp_id and att["fmt"] == "none" and self._client_data(device, "register", "webauthn.create", client)
                  and self._auth_data_ok(auth) and auth[32] & AT and not auth[32] & ED and len(auth) > 55)
            if not ok:
                return False
            cred_len = int.from_bytes(auth[53:55], "big")
            cred_id, end = auth[55:55 + cred_len], 55 + cred_len
            key, stop = cbor(auth, end)
            if (stop != len(auth) or not 0 < cred_len <= 1023 or len(cred_id) != cred_len
                    or key.get(1) != 2 or key.get(3) != -7 or key.get(-1) != 1
                    or not all(isinstance(key.get(i), bytes) and len(key[i]) == 32 for i in (-2, -3))):
                return False
            ec.EllipticCurvePublicNumbers(int.from_bytes(key[-2], "big"), int.from_bytes(key[-3], "big"),
                                          ec.SECP256R1()).public_key()  # refuse un point hors de la courbe
            with self.devices.lock:
                # La fenêtre ne sert qu'une fois ; DELETE atomique comme pour les codes d'enrôlement.
                if self.devices.db.execute("DELETE FROM passkey_windows WHERE device_id = ? AND expires >= ?",
                                           (device, _wall())).rowcount != 1:
                    return False
                self.devices.db.execute("INSERT INTO credentials VALUES (?, ?, ?, ?, ?, ?)",
                                        (cred_id, device, key[-2], key[-3], int.from_bytes(auth[33:37], "big"), _wall()))
            return True
        except (ValueError, KeyError, TypeError, AttributeError, IndexError, sqlite3.IntegrityError):
            return False  # y compris un point hors de la courbe (ValueError) et un identifiant déjà connu

    # ---- vérification d'une assertion --------------------------------------------------------------
    def verify(self, device: int, action: str, assertion: dict) -> bool:
        """Vrai seulement si l'utilisateur a signé le défi de CETTE action avec une clé de CET appareil."""
        try:
            cred_id = unb64u(assertion["id"])
            client, auth, sig = (unb64u(assertion[k]) for k in ("clientDataJSON", "authenticatorData", "signature"))
            ok = self.rp_id and self._client_data(device, action, "webauthn.get", client) and self._auth_data_ok(auth)
            if not ok:
                return False
            with self.devices.lock:
                row = self.devices.db.execute(
                    "SELECT c.x, c.y, c.sign_count FROM credentials c JOIN devices d ON d.id = c.device_id "
                    "WHERE c.cred_id = ? AND c.device_id = ? AND d.revoked = 0", (cred_id, device)).fetchone()
            if row is None:
                return False
            key = ec.EllipticCurvePublicNumbers(int.from_bytes(row[0], "big"), int.from_bytes(row[1], "big"),
                                                ec.SECP256R1()).public_key()
            key.verify(sig, auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
            count = int.from_bytes(auth[33:37], "big")
            if (count or row[2]) and count <= row[2]:  # compteur qui ne progresse pas : clé clonée possible
                return False
            with self.devices.lock:
                self.devices.db.execute("UPDATE credentials SET sign_count = ? WHERE cred_id = ?", (count, cred_id))
            return True
        except (ValueError, KeyError, TypeError, InvalidSignature):
            return False
