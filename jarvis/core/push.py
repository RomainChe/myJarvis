"""Notifications Web Push (RFC 8030, chiffrement RFC 8291 aes128gcm, VAPID RFC 8292), avec `cryptography` seulement.

- La clé VAPID (P-256) est générée au premier usage et rangée dans le coffre Windows (`vapid_key`), jamais dans un fichier.
- Un abonnement par appareil. Le point d'arrivée doit être HTTPS chez un service de push connu (liste fermée) : un
  abonnement forgé ne peut pas faire émettre de requête du PC vers une adresse interne. Les redirections sont refusées.
- Le contenu est générique (« une action attend ta confirmation ») : ni outil, ni aperçu, ni donnée personnelle ne sort
  du PC vers le service de push.
"""
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .secrets import get_secret, set_secret
from .webauthn import b64u, unb64u

_wall = time.time
# Hôtes exacts (Chrome/FCM, Firefox, Safari) + sous-domaines Windows : pas de joker sur googleapis.com (storage, etc.).
PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com")
PUSH_SUFFIXES = (".notify.windows.com",)
ENDPOINT_MAX = 600
TIMEOUT_S = 10
RECORD_SIZE = 4096
PAYLOAD = {"title": "Jarvis", "body": "Une action attend ta confirmation."}
_UNCOMPRESSED = (serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def subject_from_env() -> str:
    """Contact VAPID (`mailto:` ou https), fourni par le propriétaire hors du dépôt ; neutre par défaut."""
    subject = (os.environ.get("JARVIS_PUSH_CONTACT") or "").strip()
    if subject and not (subject.startswith(("mailto:", "https://")) and subject.isprintable() and len(subject) <= 200):
        raise ValueError("JARVIS_PUSH_CONTACT doit commencer par mailto: ou https://")
    return subject or "mailto:jarvis@example.invalid"


def endpoint_ok(endpoint: str) -> bool:
    try:
        u = urllib.parse.urlsplit(endpoint)
        host = u.hostname or ""
        return (len(endpoint) <= ENDPOINT_MAX and u.scheme == "https" and u.port in (None, 443) and not u.username
                and not u.password and (host in PUSH_HOSTS or host.endswith(PUSH_SUFFIXES)))
    except ValueError:
        return False


def encrypt(payload: bytes, p256dh: bytes, auth: bytes) -> bytes:
    """Corps aes128gcm (RFC 8291) d'un message pour l'abonné (clé publique `p256dh`, secret `auth`)."""
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    ours = ephemeral.public_key().public_bytes(*_UNCOMPRESSED)
    shared = ephemeral.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256dh))
    ikm = HKDF(hashes.SHA256(), 32, auth, b"WebPush: info\0" + p256dh + ours).derive(shared)
    salt = os.urandom(16)
    key = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\0").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\0").derive(ikm)
    sealed = AESGCM(key).encrypt(nonce, payload + b"\x02", None)
    return salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(ours)]) + ours + sealed


class Push:
    def __init__(self, devices, subject: str, get=get_secret, put=set_secret):
        self.devices, self.subject, self._get, self._put = devices, subject, get, put
        self._key: ec.EllipticCurvePrivateKey | None = None
        self.lock = threading.Lock()

    def key(self) -> ec.EllipticCurvePrivateKey:
        with self.lock:
            if self._key is None:
                stored = self._get("vapid_key")
                if stored:
                    self._key = ec.derive_private_key(int.from_bytes(unb64u(stored), "big"), ec.SECP256R1())
                else:
                    self._key = ec.generate_private_key(ec.SECP256R1())
                    self._put("vapid_key", b64u(self._key.private_numbers().private_value.to_bytes(32, "big")))
            return self._key

    def public_key(self) -> str:
        """Clé d'application pour pushManager.subscribe (point non compressé, base64url)."""
        return b64u(self.key().public_key().public_bytes(*_UNCOMPRESSED))

    def subscribe(self, device: int, endpoint: str, p256dh: str, auth: str) -> bool:
        try:
            ok = (endpoint_ok(endpoint) and len(unb64u(auth)) == 16 and len(unb64u(p256dh)) == 65
                  and ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(p256dh)))
        except ValueError:
            return False
        if not ok:
            return False
        with self.devices.lock:
            self.devices.db.execute("INSERT OR REPLACE INTO push_subs VALUES (?, ?, ?, ?)", (device, endpoint, p256dh, auth))
        return True

    def unsubscribe(self, device: int) -> None:
        with self.devices.lock:
            self.devices.db.execute("DELETE FROM push_subs WHERE device_id = ?", (device,))

    def subscribed(self, device: int) -> bool:
        with self.devices.lock:
            return self.devices.db.execute("SELECT 1 FROM push_subs WHERE device_id = ?", (device,)).fetchone() is not None

    def _vapid(self, endpoint: str) -> str:
        u = urllib.parse.urlsplit(endpoint)
        head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
        claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(_wall()) + 12 * 3600, "sub": self.subject}).encode())
        r, s = decode_dss_signature(self.key().sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
        return f"vapid t={head}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}, k={self.public_key()}"

    def _post(self, endpoint: str, body: bytes) -> int:
        """Code HTTP du service de push (0 si injoignable)."""
        req = urllib.request.Request(endpoint, data=body, method="POST", headers={
            "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": "60", "Urgency": "high",
            "Authorization": self._vapid(endpoint)})
        try:
            with urllib.request.build_opener(_NoRedirect).open(req, timeout=TIMEOUT_S) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except (OSError, ValueError, http.client.HTTPException):
            return 0

    def send(self, device: int, payload: dict = PAYLOAD) -> bool:
        """Envoie au seul appareil non révoqué ; un abonnement expiré (404/410) est supprimé."""
        with self.devices.lock:
            row = self.devices.db.execute(
                "SELECT s.endpoint, s.p256dh, s.auth FROM push_subs s JOIN devices d ON d.id = s.device_id "
                "WHERE s.device_id = ? AND d.revoked = 0", (device,)).fetchone()
        if row is None or not endpoint_ok(row[0]):
            return False
        status = self._post(row[0], encrypt(json.dumps(payload).encode(), unb64u(row[1]), unb64u(row[2])))
        if status in (404, 410):
            self.unsubscribe(device)
        return 200 <= status < 300

    def notify(self, device: int, audit=None) -> None:
        """Envoi en arrière-plan : une panne du service de push ne bloque jamais une confirmation."""
        def run():
            try:
                ok = self.send(device)
            except Exception:  # noqa: BLE001 (clé indisponible, réseau) : la notification est un confort, pas une garde
                ok = False
            if audit is not None and not ok and self.subscribed(device):
                audit.log(f"pwa:{device}", "push", {}, None, "auto", "notification non remise")
        threading.Thread(target=run, daemon=True).start()
