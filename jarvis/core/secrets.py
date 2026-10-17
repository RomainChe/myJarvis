"""Secrets : coffre de l'OS (Windows : Gestionnaire d'identification) ou, sous systemd, identifiants du service
(`LoadCredentialEncrypted=`, exposés par `$CREDENTIALS_DIRECTORY`). Jamais dans le dépôt ni dans un `.env` en clair."""
import os
from pathlib import Path

import keyring

SERVICE = "jarvis"
NAMES = ("ha_token", "vapid_key", "mail_password", "bank_key", "mail_sig_key", "agent_key", "med_token", "med_pdl", "voice_key")  # liste blanche : une faute de frappe ne crée pas un secret orphelin


MAIL_KEY_MIN = 32


def _check(name: str) -> None:
    if name not in NAMES:
        raise ValueError(f"secret inconnu : {name} (attendu : {', '.join(NAMES)})")


def set_secret(name: str, value: str) -> None:
    _check(name)
    value = value.strip()
    if not value or not value.isascii() or not value.isprintable() or any(c.isspace() for c in value):
        raise ValueError("valeur vide ou invalide (ASCII imprimable sans espace : un seul token collé une fois ?)")
    if name in ("mail_sig_key", "agent_key") and len(value) < MAIL_KEY_MIN:  # clé HMAC : une courte se devine hors ligne
        raise ValueError(f"{name} : {MAIL_KEY_MIN} caractères au moins")
    keyring.set_password(SERVICE, name, value)


def get_secret(name: str) -> str | None:
    _check(name)
    cred = os.environ.get("CREDENTIALS_DIRECTORY")
    if cred and (f := Path(cred) / name).is_file():  # le nom a passé _check : pas de traversée de dossier
        return f.read_text(encoding="ascii").strip() or None
    return keyring.get_password(SERVICE, name)  # sans coffre (Linux headless) : NoKeyringError, une KeyringError


def export_all(dest: Path) -> list[str]:
    """Écrit chaque secret présent dans `dest/<nom>` (0600) pour `systemd-creds encrypt`. Renvoie les noms, jamais les valeurs."""
    dest = dest.resolve()
    if dest.is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("export refusé : le dossier est dans le dépôt (public)")
    if any(p.lower().startswith("onedrive") for p in dest.parts):  # 0700 sans effet sous Windows : le cloud recevrait tout
        raise ValueError("export refusé : dossier synchronisé par OneDrive (utiliser %LOCALAPPDATA%\\Temp)")
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    done = []
    for name in NAMES:
        if value := get_secret(name):
            f = dest / name
            f.unlink(missing_ok=True)  # un fichier préexistant garderait ses droits
            fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as out:
                out.write(value)
            done.append(name)
    return done
