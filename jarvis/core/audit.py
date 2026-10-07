"""Journal d'audit SQLite en ajout seul : les triggers interdisent UPDATE et DELETE.

Chaque ligne porte sha256(hash précédent + contenu) : `verify()` détecte une ligne supprimée ou
modifiée en contournant les triggers. Supprimer la dernière ligne reste indétectable sans une
empreinte recopiée hors de la base (sauvegarde, Phase 5).
"""
import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    tool TEXT NOT NULL,
    args TEXT NOT NULL,
    level INTEGER,
    decision TEXT NOT NULL,
    result TEXT,
    hash TEXT
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'journal d''audit en ajout seul'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'journal d''audit en ajout seul'); END;
"""

RESULT_MAX = 500
ARGS_MAX = 2000
FIELDS = "ts, source, tool, args, level, decision, result"


def _hash(prev: str, row: tuple) -> str:
    return hashlib.sha256(json.dumps([prev, *row], ensure_ascii=False).encode()).hexdigest()


class Audit:
    def __init__(self, path: str):
        # Autocommit + verrou : une seule connexion utilisable depuis plusieurs threads (pool FastAPI).
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.lock = threading.Lock()
        # Sans cela, INSERT OR REPLACE supprime une ligne sans déclencher le trigger DELETE.
        self.db.execute("PRAGMA recursive_triggers = ON")
        self.db.executescript(SCHEMA)
        if "hash" not in {r[1] for r in self.db.execute("PRAGMA table_info(audit)")}:
            self.db.execute("ALTER TABLE audit ADD COLUMN hash TEXT")  # journal créé avant le chaînage

    def log(self, source: str, tool: str, args: dict, level: int | None, decision: str, result) -> None:
        row = (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source,
            tool,
            json.dumps(args, ensure_ascii=False, default=str)[:ARGS_MAX],
            level,
            decision,
            None if result is None else str(result)[:RESULT_MAX],
        )
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")  # verrou d'écriture avant de lire le dernier hash
            try:
                last = self.db.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
                prev = (last and last[0]) or ""
                self.db.execute(f"INSERT INTO audit ({FIELDS}, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (*row, _hash(prev, row)))
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:  # SQLite annule déjà seul certaines erreurs (disque plein)
                    self.db.execute("ROLLBACK")
                raise

    def verify(self) -> bool:
        """Vrai si la chaîne de hachage est intacte (les lignes antérieures au chaînage sont ignorées)."""
        prev = ""
        for *row, h in self.db.execute(f"SELECT {FIELDS}, hash FROM audit ORDER BY id"):
            if h is None and prev == "":
                continue
            if h != _hash(prev, tuple(row)):
                return False
            prev = h
        return True

    def last(self, n: int = 20) -> list[tuple]:
        return self.db.execute(
            f"SELECT {FIELDS} FROM audit ORDER BY id DESC LIMIT ?", (max(n, 0),)
        ).fetchall()
