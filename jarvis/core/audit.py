"""Journal d'audit SQLite en ajout seul : les triggers interdisent UPDATE et DELETE.

Chaque ligne porte sha256(hash précédent + contenu) : `verify()` détecte une modification ou une
suppression faite à la main (erreur, outil maladroit). Ce n'est PAS une protection contre un processus
malveillant de l'utilisateur : le code est public, il peut recalculer toute la chaîne. Un HMAC n'y
changerait rien, sa clé (fichier ou keyring) serait lisible par ce même processus. La garantie viendra
de l'empreinte de la dernière ligne recopiée hors du PC (sauvegarde, Phase 5).
"""
import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone

from .tools import STR_MAX

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
    ref INTEGER,
    hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'journal d''audit en ajout seul'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'journal d''audit en ajout seul'); END;
"""

RESULT_MAX = 500
VALUE_MAX = STR_MAX  # par valeur, égal à la limite de check_args : un appel valide est journalisé en entier
NAME_MAX = 100
# ponytail: plafond global contre un appel invalide aux clés innombrables ; ~16 paramètres texte pleins.
ARGS_MAX = 20 * STR_MAX
FIELDS = "ts, source, tool, args, level, decision, result, ref"


def _hash(prev: str, row: tuple) -> str:
    return hashlib.sha256(json.dumps([prev, *row], ensure_ascii=False).encode()).hexdigest()


def _short(args):
    if type(args) is not dict:
        return args
    return {str(k)[:NAME_MAX]: v[:VALUE_MAX] if isinstance(v, str) else v for k, v in args.items()}


class Audit:
    def __init__(self, path: str):
        # Autocommit + verrou : une seule connexion utilisable depuis plusieurs threads (pool FastAPI).
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.lock = threading.Lock()
        # Sans cela, INSERT OR REPLACE supprime une ligne sans déclencher le trigger DELETE.
        self.db.execute("PRAGMA recursive_triggers = ON")
        self.db.executescript(SCHEMA)

    def log(self, source: str, tool: str, args: dict, level: int | None, decision: str, result,
            ref: int | None = None) -> int:
        """Ajoute une ligne et renvoie son id ; `ref` lie une ligne de résultat à sa ligne « en cours »."""
        row = (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source[:NAME_MAX],
            tool[:NAME_MAX],
            json.dumps(_short(args), ensure_ascii=False, default=str)[:ARGS_MAX],
            level,
            decision,
            None if result is None else str(result)[:RESULT_MAX],
            ref,
        )
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")  # verrou d'écriture avant de lire le dernier hash
            try:
                last = self.db.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
                cur = self.db.execute(f"INSERT INTO audit ({FIELDS}, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                      (*row, _hash(last[0] if last else "", row)))
                self.db.execute("COMMIT")
                return cur.lastrowid
            except BaseException:
                if self.db.in_transaction:  # SQLite annule déjà seul certaines erreurs (disque plein)
                    self.db.execute("ROLLBACK")
                raise

    def verify(self) -> bool:
        """Vrai si la chaîne de hachage est intacte."""
        prev = ""
        for *row, h in self.db.execute(f"SELECT {FIELDS}, hash FROM audit ORDER BY id"):
            if h is None or h != _hash(prev, tuple(row)):
                return False
            prev = h
        return True

    def last(self, n: int = 20) -> list[tuple]:
        return self.db.execute(
            f"SELECT {FIELDS} FROM audit ORDER BY id DESC LIMIT ?", (max(n, 0),)
        ).fetchall()
