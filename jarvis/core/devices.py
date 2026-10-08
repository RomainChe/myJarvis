"""Appareils autorisés (PWA) : token de 256 bits, seul son SHA-256 est stocké ; enrôlement par code à usage unique.

Le token authentifie à lui seul : ni l'IP source ni un en-tête Tailscale ne comptent (tout arrive de 127.0.0.1).
Un code d'enrôlement ne se crée que depuis le PC (`python -m jarvis device add`), jamais par une route HTTP.
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

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created REAL NOT NULL,
    last_used REAL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS enroll_codes (code_hash TEXT PRIMARY KEY, expires REAL NOT NULL);
"""


def _h(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class Devices:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)
        self.fails, self.locked_until = 0, 0.0  # en mémoire : un redémarrage remet le compteur à zéro

    def new_code(self) -> str:
        code = secrets.token_urlsafe(16)
        with self.lock:
            self.db.execute("DELETE FROM enroll_codes WHERE expires < ?", (_now(),))
            self.db.execute("INSERT INTO enroll_codes VALUES (?, ?)", (_h(code), _now() + CODE_TTL_S))
        return code

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
            cur = self.db.execute("INSERT INTO devices (name, token_hash, created) VALUES (?, ?, ?)",
                                  (name, _h(token), now))
            return cur.lastrowid, token

    def check(self, token: str) -> tuple[int, str] | None:
        """(id, nom) de l'appareil si le token est valide et non révoqué. Vérifié en base à chaque requête."""
        digest = _h(token)
        with self.lock:
            row = self.db.execute("SELECT id, name, token_hash FROM devices WHERE token_hash = ? AND revoked = 0",
                                  (digest,)).fetchone()
            if row is None or not hmac.compare_digest(row[2], digest):
                return None
            self.db.execute("UPDATE devices SET last_used = ? WHERE id = ?", (_now(), row[0]))
        return row[0], row[1]

    def revoke(self, device_id: int) -> bool:
        with self.lock:
            return self.db.execute("UPDATE devices SET revoked = 1 WHERE id = ? AND revoked = 0",
                                   (device_id,)).rowcount == 1

    def list(self) -> list[tuple]:
        with self.lock:
            return self.db.execute("SELECT id, name, created, last_used, revoked FROM devices ORDER BY id").fetchall()
