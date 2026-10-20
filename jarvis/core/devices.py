"""Appareils autorisés (PWA) : token de 256 bits, seul son SHA-256 est stocké ; enrôlement par code à usage unique.

Le token authentifie à lui seul : ni l'IP source ni un en-tête Tailscale ne comptent (tout arrive de 127.0.0.1).
Un code d'enrôlement ne se crée que depuis le PC (`python -m jarvis device add`), jamais par une route HTTP.
Un token expire `TOKEN_TTL_S` après son dernier renouvellement (D6) ; la PWA le renouvelle à chaque ouverture. L'ancien
reste valable jusqu'au premier usage du nouveau : une réponse perdue ne coupe pas l'appareil.
"""
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time

_now = time.time  # remplacé dans les tests
CODE_TTL_S = 120
MAX_FAILS = 5  # échecs d'enrôlement avant de brûler tous les codes en attente
LOCKOUT_S = 300
NAME_MAX = 40
SCOPES = ("full", "voice", "tv")  # « voice » : n'ouvre que POST /api/voice (micro du salon) ; « tv » : /api/voice, GET /api/tv et POST /api/token (TV partagée, N0/N1)
TOKEN_TTL_S = 90 * 86400

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created REAL NOT NULL,
    last_used REAL,
    revoked INTEGER NOT NULL DEFAULT 0,
    expires REAL,
    prev_hash TEXT
);
CREATE TABLE IF NOT EXISTS enroll_codes (code_hash TEXT PRIMARY KEY, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS push_subs (device_id INTEGER PRIMARY KEY, endpoint TEXT NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL);
"""


def _h(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class Devices:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(devices)")}
        for col in ("expires REAL", "prev_hash TEXT"):  # base créée avant D6
            if col.split()[0] not in cols:
                self.db.execute(f"ALTER TABLE devices ADD COLUMN {col}")
        self.db.execute("UPDATE devices SET expires = ? WHERE expires IS NULL", (_now() + TOKEN_TTL_S,))
        if "scope" not in [r[1] for r in self.db.execute("PRAGMA table_info(devices)")]:  # base d'avant le lot 4c
            self.db.execute("ALTER TABLE devices ADD COLUMN scope TEXT NOT NULL DEFAULT 'full'")  # appareils existants : accès complet
        self.fails, self.locked_until = 0, 0.0  # en mémoire : un redémarrage remet le compteur à zéro

    def new_code(self) -> str:
        code = secrets.token_urlsafe(16)
        with self.lock:
            self.db.execute("DELETE FROM enroll_codes WHERE expires < ?", (_now(),))
            self.db.execute("INSERT INTO enroll_codes VALUES (?, ?)", (_h(code), _now() + CODE_TTL_S))
        return code

    def locked(self) -> bool:
        return _now() < self.locked_until

    def enroll(self, code: str, name: str) -> tuple[int, str] | None:
        """(id, token) si le code est valide ; None sinon, sans dire pourquoi (faux, expiré, déjà utilisé, verrouillé)."""
        name = name.strip()
        if not name or len(name) > NAME_MAX or not name.isprintable():
            raise ValueError("nom d'appareil invalide")
        with self.lock:
            now = _now()
            if now < self.locked_until:
                return None
            cur = self.db.execute("DELETE FROM enroll_codes WHERE code_hash = ? AND expires >= ?", (_h(code), now))
            if cur.rowcount != 1:  # DELETE atomique : un code ne sert qu'une fois, même en requêtes simultanées
                self.fails += 1
                if self.fails >= MAX_FAILS:
                    self.db.execute("DELETE FROM enroll_codes")
                    self.fails, self.locked_until = 0, now + LOCKOUT_S
                return None
            self.fails = 0
            token = secrets.token_urlsafe(32)
            cur = self.db.execute("INSERT INTO devices (name, token_hash, created, expires) VALUES (?, ?, ?, ?)",
                                  (name, _h(token), now, now + TOKEN_TTL_S))
            return cur.lastrowid, token

    def add_scoped(self, name: str, scope: str) -> tuple[int, str]:
        """Crée un appareil de portée limitée (CLI seulement) : (id, token), le token n'est montré qu'une fois."""
        name = name.strip()
        if not name or len(name) > NAME_MAX or not name.isprintable() or scope not in SCOPES:
            raise ValueError("nom ou portée invalide")
        token = secrets.token_urlsafe(32)
        with self.lock:
            cur = self.db.execute("INSERT INTO devices (name, token_hash, created, expires, scope) VALUES (?, ?, ?, ?, ?)",
                                  (name, _h(token), _now(), _now() + TOKEN_TTL_S, scope))
        return cur.lastrowid, token

    def check(self, token: str) -> tuple[int, str] | None:
        """(id, nom) de l'appareil si le token est valide, non expiré et non révoqué. Vérifié en base à chaque requête."""
        found = self.check_scoped(token)
        return found and found[:2]

    def check_scoped(self, token: str) -> tuple[int, str, str] | None:
        """(id, nom, portée) : comme `check`, pour que l'appelant refuse une clé de portée limitée hors de sa route.

        Le token précédent (avant renouvellement) est accepté jusqu'au premier usage du nouveau.
        """
        digest = _h(token)
        with self.lock:
            row = self.db.execute("SELECT id, name, token_hash, prev_hash, scope FROM devices "
                                  "WHERE (token_hash = ? OR prev_hash = ?) AND revoked = 0 AND expires >= ?",
                                  (digest, digest, _now())).fetchone()
            if row is None or not (hmac.compare_digest(row[2], digest) or hmac.compare_digest(row[3] or "", digest)):
                return None
            current = hmac.compare_digest(row[2], digest)
            self.db.execute("UPDATE devices SET last_used = ?" + (", prev_hash = NULL" if current else "") + " WHERE id = ?",
                            (_now(), row[0]))
        return row[0], row[1], row[4]

    def rotate(self, device_id: int, used: str, clean: bool = False) -> str | None:
        """Nouveau token valable `TOKEN_TTL_S` ; None si l'appareil est révoqué entre-temps.

        `used` = token présenté : si c'est le précédent (réponse du dernier renouvellement perdue), il reste valable.
        `clean` : aucun ancien token ne reste valable (révocation : une copie volée de CET appareil meurt aussi).
        """
        token = secrets.token_urlsafe(32)
        with self.lock:
            ok = self.db.execute("UPDATE devices SET prev_hash = CASE WHEN ? THEN NULL WHEN prev_hash = ? THEN prev_hash ELSE token_hash END, "
                                 "token_hash = ?, expires = ? WHERE id = ? AND revoked = 0 AND expires >= ?",
                                 (clean, _h(used), _h(token), _now() + TOKEN_TTL_S, device_id, _now())).rowcount
        return token if ok == 1 else None

    def revoke(self, device_id: int) -> bool:
        with self.lock:
            self.db.execute("DELETE FROM push_subs WHERE device_id = ?", (device_id,))  # plus de notification vers un appareil révoqué
            return self.db.execute("UPDATE devices SET revoked = 1 WHERE id = ? AND revoked = 0",
                                   (device_id,)).rowcount == 1

    def revoke_all(self, keep: int | None = None) -> int:
        """Révoque tous les appareils sauf `keep` ; nombre d'appareils révoqués."""
        ids = [r[0] for r in self.list() if not r[4] and r[0] != keep]
        return sum(self.revoke(i) for i in ids)

    def list(self) -> list[tuple]:
        with self.lock:
            return self.db.execute("SELECT id, name, created, last_used, revoked, scope FROM devices ORDER BY id").fetchall()
