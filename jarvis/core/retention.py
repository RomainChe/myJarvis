"""Durées de conservation (D5) : purge des fichiers et des relevés périmés, archivage du journal d'audit.

    python -m jarvis purge [--dry-run]

Appelée aussi au démarrage de `serve`. Une ligne `purge` au journal résume chaque passage (comptes seulement).
"""
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home() / ".jarvis"
DAYS = {"audit": 365, "captures": 7, "finance": 120, "veille": 120, "social": 365}
ARCHIVE_DIR = Path(os.environ.get("JARVIS_ARCHIVE_DIR") or HOME / "audit-archive")


def purge_dir(directory: Path, pattern: str, days: int, now: float | None = None, dry: bool = False) -> int:
    """Supprime les fichiers `pattern` de `directory` plus vieux que `days` jours (date de modification)."""
    limit = (time.time() if now is None else now) - days * 86400
    n = 0
    for f in Path(directory).glob(pattern):
        try:
            if f.is_file() and not f.is_symlink() and f.stat().st_mtime < limit:
                if not dry:
                    f.unlink()
                n += 1
        except OSError:  # fichier ouvert ou disparu : repris au prochain passage
            pass
    return n


def purge_social(db: Path, days: int, today=None, dry: bool = False) -> int:
    """Relevés YouTube plus vieux que `days` jours (table `yt`, une ligne par jour)."""
    if not Path(db).is_file():
        return 0
    cutoff = ((today or datetime.now().date()) - timedelta(days=days)).isoformat()
    cx = sqlite3.connect(db)
    try:
        sql = "FROM yt WHERE day < ?"
        if dry:
            return cx.execute("SELECT COUNT(*) " + sql, (cutoff,)).fetchone()[0]
        with cx:
            return cx.execute("DELETE " + sql, (cutoff,)).rowcount
    except sqlite3.OperationalError:  # base sans table yt
        return 0
    finally:
        cx.close()


def run(audit, *, dry: bool = False, now: datetime | None = None, archive_dir: Path = ARCHIVE_DIR,
        captures=None, finance=None, veille=None, social: Path = HOME / "social.db") -> dict:
    """Un passage complet ; renvoie les comptes. Aucun contenu n'est écrit au journal."""
    if captures is None:
        captures = (HOME / "captures", Path.home() / "Pictures" / "Jarvis")  # + ancien dossier des captures
    if finance is None or veille is None:
        from jarvis.core import finance as _f, veille as _v
        finance, veille = finance or _f.finance_dir(), veille or _v.veille_dir()
    now = now or datetime.now(timezone.utc)
    ts = now.timestamp()
    out = {
        "captures": sum(purge_dir(d, "capture-*.png", DAYS["captures"], ts, dry) for d in captures),
        "finance": purge_dir(finance, "semaine-*.eml", DAYS["finance"], ts, dry),
        "veille": purge_dir(veille, "veille-*.eml", DAYS["veille"], ts, dry),
        "social": purge_social(social, DAYS["social"], now.date(), dry),
        "audit": 0,
    }
    if not dry:
        cutoff = (now - timedelta(days=DAYS["audit"])).isoformat(timespec="seconds")
        try:
            out["audit"] = audit.archive_before(cutoff, archive_dir)
        except (RuntimeError, OSError, sqlite3.Error) as e:
            out["audit_erreur"] = type(e).__name__
    return out
