"""Sauvegarde à chaud de la base SQLite de JARVIS (journal d'audit + mémoire), avec rotation.

    python -m scripts.backup [--dest DOSSIER] [--keep N]

Lancer depuis la racine du dépôt. Source : JARVIS_DB, sinon ~/.jarvis/jarvis.db.
Destination par défaut : ~/.jarvis/backups. Conserve les N copies les plus récentes.
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from jarvis.__main__ import DB_PATH

PREFIX = "jarvis-"


def backup(src: Path, dest_dir: Path, keep: int) -> Path:
    """Copie `src` dans `dest_dir` via l'API backup de sqlite3, vérifie la copie, puis applique la rotation."""
    if keep < 1:
        raise ValueError("keep doit être >= 1")
    src = Path(src).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"base introuvable : {src}")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{PREFIX}{datetime.now():%Y%m%d-%H%M%S-%f}.db"

    # Lecture seule : ne crée jamais une base vide si la source disparaît entre-temps.
    source = sqlite3.connect(f"{src.as_uri()}?mode=ro", uri=True)
    copy = sqlite3.connect(target)
    try:
        source.backup(copy)
        ok = copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        copy.close()
        source.close()
    if not ok:
        target.unlink()
        raise RuntimeError("copie corrompue, sauvegarde annulée (anciennes copies conservées)")

    # Rotation seulement après une copie valide : on ne perd jamais la dernière bonne sauvegarde.
    for old in sorted(dest_dir.glob(f"{PREFIX}*.db"))[:-keep]:
        old.unlink()
    return target


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", type=Path, default=Path.home() / ".jarvis" / "backups")
    parser.add_argument("--keep", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        print(backup(DB_PATH, args.dest, args.keep))
    except (ValueError, FileNotFoundError, RuntimeError, sqlite3.Error) as e:
        print(f"Échec de la sauvegarde : {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
