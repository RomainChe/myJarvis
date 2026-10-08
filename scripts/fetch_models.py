"""Télécharge les modèles de la voix (Phase 4) depuis des sources HTTPS épinglées.

Usage : python scripts/fetch_models.py [--manifest models/MANIFEST.json] [--dest models]
Stdlib seulement. Chaque fichier : URL épinglée (révision/tag), taille et SHA-256 du manifeste.
Téléchargé en `.part`, renommé seulement si le SHA-256 correspond. Un fichier déjà bon est gardé.
"""
import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # lancé par chemin (python scripts/fetch_models.py) : le dépôt n'est pas encore importable
    sys.path.insert(0, str(ROOT))
from jarvis.core.modelcheck import CHUNK, is_good  # noqa: E402
# Hôtes exacts ou suffixes (redirections de CDN) acceptés, HTTPS seulement.
HOSTS = {"huggingface.co", "github.com", "objects.githubusercontent.com",
         "release-assets.githubusercontent.com"}
SUFFIXES = (".hf.co", ".huggingface.co")
TIMEOUT = 60


def host_ok(url):
    p = urllib.parse.urlsplit(url)
    h = (p.hostname or "").lower()
    return p.scheme == "https" and (h in HOSTS or h.endswith(SUFFIXES))


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_ok(newurl):
            raise urllib.error.URLError(f"redirection refusée : {urllib.parse.urlsplit(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_Redirect)


def fetch(url, dest, size, sha):
    """Retourne 'ok' (déjà bon) ou 'téléchargé'. Lève ValueError si le hash ne correspond pas."""
    if not host_ok(url):
        raise ValueError(f"source non autorisée : {url}")
    if is_good(dest, size, sha):
        return "ok"
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    try:
        with _opener.open(urllib.request.Request(url), timeout=TIMEOUT) as r, open(part, "wb") as f:
            while chunk := r.read(CHUNK):
                h.update(chunk)
                f.write(chunk)
        if h.hexdigest() != sha:
            raise ValueError(f"SHA-256 différent pour {dest.name} (attendu {sha[:12]}…, reçu {h.hexdigest()[:12]}…)")
        if part.stat().st_size != size:
            raise ValueError(f"taille différente pour {dest.name}")
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return "téléchargé"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(ROOT / "models" / "MANIFEST.json"))
    ap.add_argument("--dest", default=str(ROOT / "models"))
    a = ap.parse_args(argv)
    dest_root = Path(a.dest).resolve()
    files = json.loads(Path(a.manifest).read_text(encoding="utf-8"))["files"]
    bad = 0
    for e in files:
        dest = (dest_root / e["path"]).resolve()
        if dest_root not in dest.parents:
            print(f"REFUS  {e['path']} : chemin hors du dossier", file=sys.stderr)
            bad += 1
            continue
        try:
            print(f"{fetch(e['url'], dest, e['size'], e['sha256']):10} {e['path']}")
        except (ValueError, OSError) as ex:  # URLError est un OSError
            print(f"ÉCHEC  {e['path']} : {ex}", file=sys.stderr)
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
