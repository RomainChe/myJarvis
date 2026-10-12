"""Sauvegarde à chaud de la base SQLite de JARVIS (journal d'audit + mémoire), avec rotation.

    python -m scripts.backup [--dest DOSSIER] [--keep N]     sauvegarde + ancre d'audit
    python -m scripts.backup --check [--dest DOSSIER]         copie > 25 h ou absente = code 1
    python -m scripts.backup --verify [--dest DOSSIER]        restaure la dernière copie à part et la contrôle

Lancer depuis la racine du dépôt. Source : JARVIS_DB, sinon ~/.jarvis/jarvis.db.
Destination : --dest, sinon JARVIS_BACKUP_DIR, sinon ~/.jarvis/backups (même disque : à éviter, D1).
Conserve les N copies les plus récentes. `anchor.json` (dernier id + hash d'audit) est écrit à côté des copies.
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from jarvis.__main__ import DB_PATH
from jarvis.core.audit import Audit, segment_hash
from jarvis.core.retention import ARCHIVE_DIR

PREFIX = "jarvis-"
ANCHOR = "anchor.json"
MAX_AGE_S = 25 * 3600


def backup(src: Path, dest_dir: Path, keep: int, archive_dir: Path = ARCHIVE_DIR) -> Path:
    """Copie `src` dans `dest_dir` via l'API backup de sqlite3, vérifie la copie, puis applique la rotation.

    Refus (RuntimeError, ancre et copies anciennes conservées) si la chaîne d'audit de la copie est rompue ou
    si la ligne de l'ancre précédente n'y est plus : une base réécrite ne remplace jamais l'ancre."""
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
        last = copy.execute("SELECT id, hash FROM audit ORDER BY id DESC LIMIT 1").fetchone() if ok else None
    finally:
        copy.close()
        source.close()
    if not ok:
        target.unlink()
        raise RuntimeError("copie corrompue, sauvegarde annulée (anciennes copies conservées)")

    copy_audit = Audit(str(target))
    try:
        problem = None if copy_audit.verify() else "chaîne d'audit rompue dans la base source"
    finally:
        copy_audit.db.close()
    old = _read_anchor(dest_dir)
    if problem is None and old is not None:
        problem = _anchor_problem(target, old, archive_dir)
    if problem:
        target.unlink()
        raise RuntimeError(f"{problem} : sauvegarde refusée (ancre et anciennes copies conservées)")

    tmp = dest_dir / (ANCHOR + ".tmp")
    tmp.write_text(json.dumps({"copy": target.name, "id": last[0] if last else 0, "hash": last[1] if last else ""}))
    tmp.replace(dest_dir / ANCHOR)

    # Rotation seulement après une copie valide : on ne perd jamais la dernière bonne sauvegarde.
    for old in sorted(dest_dir.glob(f"{PREFIX}*.db"))[:-keep]:
        old.unlink()
    return target


def latest(dest_dir: Path) -> Path | None:
    copies = sorted(Path(dest_dir).glob(f"{PREFIX}*.db"))
    return copies[-1] if copies else None


def check(dest_dir: Path, max_age_s: int = MAX_AGE_S) -> str | None:
    """Message d'alerte si la dernière copie manque ou a plus de 25 h, sinon None."""
    copy = latest(dest_dir)
    if copy is None:
        return f"aucune sauvegarde dans {dest_dir}"
    age = time.time() - copy.stat().st_mtime
    return f"dernière sauvegarde vieille de {age / 3600:.0f} h ({copy.name})" if age > max_age_s else None


def verify(dest_dir: Path, live: Path, archive_dir: Path = ARCHIVE_DIR) -> str | None:
    """Restaure la dernière copie dans un dossier temporaire ; None si saine, sinon la raison.

    Contrôle : chaîne d'audit intacte, copie = ancre, et la base vivante contient toujours la ligne
    ancrée avec le même hash (journal tronqué ou réécrit depuis = écart). Une ligne archivée depuis est
    relue dans les segments de `archive_dir`, chaîne recalculée jusqu'au point de contrôle."""
    copy = latest(dest_dir)
    if copy is None:
        return "aucune copie à vérifier"
    anchor = _read_anchor(dest_dir)
    if not anchor:
        return f"{ANCHOR} absent ou illisible"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        restored = Path(tmp) / "jarvis.db"
        shutil.copy2(copy, restored)
        audit = Audit(str(restored))
        try:
            if not audit.verify():
                return "chaîne d'audit rompue dans la copie"
        finally:
            audit.db.close()
    if anchor.get("copy") == copy.name:
        return _anchor_problem(live, anchor, archive_dir)
    return None


def _anchor_problem(db_path: Path, anchor: dict, archive_dir: Path) -> str | None:
    """None si la ligne ancrée est toujours dans la base (ou dans un segment archivé vérifié), sinon la raison."""
    id_, want = anchor.get("id"), anchor.get("hash")
    if type(id_) is not int or type(want) is not str:
        return f"{ANCHOR} malformé (supprime-le pour repartir d'une ancre neuve)"
    if id_ == 0:
        return None
    row, cp = None, (0, "")
    db = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        row = db.execute("SELECT hash FROM audit WHERE id = ?", (id_,)).fetchone()
        cp = db.execute("SELECT id, hash FROM audit_checkpoint ORDER BY id DESC LIMIT 1").fetchone() or cp
    except sqlite3.Error:
        pass
    finally:
        db.close()
    if id_ <= cp[0]:  # ligne archivée depuis (étape 13) : le point de contrôle seul est forgeable, le segment la porte
        try:
            row = (segment_hash(archive_dir, id_, *cp),)
        except ValueError as e:
            return f"ligne ancrée {id_} non retrouvée dans le journal archivé : {e}"
    if row is None or row[0] != want:
        return f"la base ne contient plus la ligne ancrée {id_} : journal tronqué ou réécrit"
    return None


def _read_anchor(dest_dir: Path) -> dict | None:
    """None si aucune ancre n'existe ; {} si le fichier est illisible (refus plutôt que repartir de zéro)."""
    path = Path(dest_dir) / ANCHOR
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", type=Path,
                        default=Path(os.environ.get("JARVIS_BACKUP_DIR") or Path.home() / ".jarvis" / "backups"))
    parser.add_argument("--keep", type=int, default=30)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.check or args.verify:
        problem = check(args.dest) if args.check else verify(args.dest, DB_PATH)
        print(problem or "OK", file=sys.stderr if problem else sys.stdout)
        return 1 if problem else 0
    if Path(args.dest).resolve().drive.lower() == Path(DB_PATH).resolve().drive.lower():
        print("Attention : destination sur le même disque que la base (D1).", file=sys.stderr)
    try:
        print(backup(DB_PATH, args.dest, args.keep))
    except (ValueError, FileNotFoundError, RuntimeError, sqlite3.Error) as e:
        print(f"Échec de la sauvegarde : {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
