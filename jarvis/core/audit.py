"""Journal d'audit SQLite en ajout seul : les triggers interdisent UPDATE et DELETE."""
import json
import sqlite3
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
    result TEXT
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'journal d''audit en ajout seul'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'journal d''audit en ajout seul'); END;
"""

RESULT_MAX = 500


class Audit:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def log(self, source: str, tool: str, args: dict, level: int | None, decision: str, result) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO audit (ts, source, tool, args, level, decision, result) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    source,
                    tool,
                    json.dumps(args, ensure_ascii=False, default=str),
                    level,
                    decision,
                    None if result is None else str(result)[:RESULT_MAX],
                ),
            )

    def last(self, n: int = 20) -> list[tuple]:
        return self.db.execute(
            "SELECT ts, source, tool, args, level, decision, result FROM audit ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
