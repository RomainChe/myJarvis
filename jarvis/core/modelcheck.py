"""Vérification d'un fichier de modèle (taille + SHA-256), partagée par le cœur et scripts/fetch_models.py."""
import hashlib

CHUNK = 1 << 20


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


_verified = {}  # chemin -> (taille, mtime_ns, sha) déjà haché avec succès : un fichier inchangé n'est pas re-haché


def is_good(path, size, sha):
    """Taille + SHA-256. Le résultat positif est mémorisé tant que (taille, date de modification) ne bougent pas : on
    peut donc revérifier à CHAQUE chargement (modèle rechargé après un jeu) sans relire 1,6 Go ; un fichier remplacé
    après la vérification est re-haché et refusé. ponytail: un attaquant qui sait rétablir la date garde le même
    niveau de confiance que le code du dépôt ; ouvrir le fichier une fois et le charger depuis ce handle si besoin."""
    if not path.is_file():
        return False
    st = path.stat()
    if st.st_size != size:
        return False
    key, stamp = str(path), (st.st_size, st.st_mtime_ns, sha)
    if _verified.get(key) == stamp:
        return True
    if sha256_of(path) != sha:
        _verified.pop(key, None)
        return False
    _verified[key] = stamp
    return True


def check_manifest(manifest, models):
    """Chemins présents dans `models` dont la taille ou le SHA-256 ne correspond pas au manifeste (les absents sont ignorés :
    toutes les voix ne sont pas téléchargées)."""
    import json
    bad = []
    for e in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        path = models / e["path"]
        if path.exists() and not is_good(path, e["size"], e["sha256"]):
            bad.append(e["path"])
    return bad
