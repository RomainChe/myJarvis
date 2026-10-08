"""Onglet Réseaux de la PWA (Phase 6 point 3, étape 1, N0, lecture seule).

Lit les fichiers que lol-clipper dépose à côté de ses vidéos : `<vidéo>.youtube.json` / `.tiktok.json` (mises en ligne) et
`<vidéo>.publish.todo` (mises en ligne programmées). Dossier : `~/.jarvis/social.json` (`{"clips_dir": "..."}`), par défaut
`~/Videos/LoL Clips`. Rien du contenu des fichiers n'est relayé tel quel : plateforme, date et lien (préfixe de plateforme
vérifié) en sortent, le titre vient du nom de fichier. Pas de ligne d'audit : lecture N0.
"""
import json
from itertools import islice
from datetime import datetime
from pathlib import Path

CONFIG = Path.home() / ".jarvis" / "social.json"
DEFAULT_DIR = Path.home() / "Videos" / "LoL Clips"
FOLDERS = ("Montage", "Parties")
LINKS = {"youtube": "https://youtu.be/", "tiktok": "https://www.tiktok.com/"}
MAX_BYTES, MAX_ROWS, MAX_FILES = 4096, 20, 500


def clips_dir(path: Path = CONFIG) -> Path:
    try:
        return Path(json.loads(Path(path).read_text(encoding="utf-8"))["clips_dir"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_DIR


def _read(f: Path) -> dict | None:
    try:
        with f.open("rb") as h:
            data = json.loads(h.read(MAX_BYTES))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _title(f: Path, suffix: str) -> str:
    return f.name[: -len(suffix)][:80]


def snapshot(root: Path | None = None) -> dict:
    root = Path(root) if root else clips_dir()
    published, scheduled = [], []
    for folder in FOLDERS:
        for platform, link in LINKS.items():
            suffix = f".{platform}.json"
            for f in islice((root / folder).glob(f"*{suffix}"), MAX_FILES):
                data = _read(f) if not f.is_symlink() else None
                if data is None:
                    continue
                url = data.get("url")
                try:
                    at = datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="minutes")
                except OSError:
                    continue
                published.append({"platform": platform, "title": _title(f, suffix), "at": at,
                                  "url": url if isinstance(url, str) and url.startswith(link) else None,
                                  "privacy": data.get("privacy") if data.get("privacy") in ("public", "private", "unlisted") else None})
        for f in islice((root / folder).glob("*.publish.todo"), MAX_FILES):
            data = _read(f) if not f.is_symlink() else None
            try:
                at = datetime.fromisoformat(data["publish_at"]).isoformat(timespec="minutes")
            except (TypeError, KeyError, ValueError):
                continue
            only = data.get("only")
            scheduled.append({"platform": only if only in LINKS else "all", "title": _title(f, ".publish.todo"), "at": at})
    published.sort(key=lambda r: r["at"], reverse=True)
    scheduled.sort(key=lambda r: r["at"])
    return {"configured": root.is_dir(), "published": published[:MAX_ROWS], "scheduled": scheduled[:MAX_ROWS]}
