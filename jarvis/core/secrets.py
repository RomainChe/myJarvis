"""Secrets dans le coffre Windows (Gestionnaire d'identification), jamais dans un fichier."""
import keyring

SERVICE = "jarvis"
NAMES = ("ha_token", "vapid_key", "mail_password", "bank_key")  # liste blanche : une faute de frappe ne crée pas un secret orphelin


def _check(name: str) -> None:
    if name not in NAMES:
        raise ValueError(f"secret inconnu : {name} (attendu : {', '.join(NAMES)})")


def set_secret(name: str, value: str) -> None:
    _check(name)
    value = value.strip()
    if not value or not value.isascii() or not value.isprintable() or any(c.isspace() for c in value):
        raise ValueError("valeur vide ou invalide (ASCII imprimable sans espace : un seul token collé une fois ?)")
    keyring.set_password(SERVICE, name, value)


def get_secret(name: str) -> str | None:
    _check(name)
    return keyring.get_password(SERVICE, name)
