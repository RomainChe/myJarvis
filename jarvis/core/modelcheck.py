"""Vérification d'un fichier de modèle (taille + SHA-256), partagée par le cœur et scripts/fetch_models.py."""
import hashlib

CHUNK = 1 << 20


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def is_good(path, size, sha):
    return path.is_file() and path.stat().st_size == size and sha256_of(path) == sha
