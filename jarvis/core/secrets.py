"""Secrets dans le coffre Windows (Gestionnaire d'identification), jamais dans un fichier."""
import keyring

SERVICE = "jarvis"
NAMES = ("ha_token",)  # liste blanche : une faute de frappe ne crée pas un secret orphelin


def _check(name: str) -> None:
    if name not in NAMES:
        raise ValueError(f"secret inconnu : {name} (attendu : {', '.join(NAMES)})")


def set_secret(name: str, value: str) -> None:
    _check(name)
    if not value.strip():
        raise ValueError("valeur vide")
    keyring.set_password(SERVICE, name, value.strip())


def get_secret(name: str) -> str | None:
    _check(name)
    return keyring.get_password(SERVICE, name)
