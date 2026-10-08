"""TV du salon (Google TV) via Home Assistant : Android TV Remote (`media_player.salon_tv`, `remote.salon_tv`).

Le volume n'a pas de valeur absolue sur cette intégration : montée/descente par pas. La barre de son suit en HDMI-CEC.
"""
import unicodedata

from jarvis.core import ha
from jarvis.core.tools import Level, tool

PLAYER = "media_player.salon_tv"
REMOTE = "remote.salon_tv"
STEPS_MAX = 5
# Applis lançables : nom -> (paquet Android, lien propre à l'appli). Liens vérifiés sur la TV du salon le 2026-10-08 :
# un lien web ouvre un sélecteur « Ouvrir avec », et `market://` ou le nom de paquet ne lancent rien.
# Une appli absente de la liste n'est pas lançable (nom = donnée, pas commande).
APPS = {"youtube": ("com.google.android.youtube.tv", "vnd.youtube://"),
        "netflix": ("com.netflix.ninja", "nflx://www.netflix.com"),
        "twitch": ("tv.twitch.android.app", "twitch://home"),
        "spotify": ("com.spotify.tv.android", "spotify://")}
LAUNCHER = "com.google.android.apps.tv.launcherx"
KEYS = {"home": "HOME", "back": "BACK", "up": "DPAD_UP", "down": "DPAD_DOWN", "left": "DPAD_LEFT",
        "right": "DPAD_RIGHT", "ok": "DPAD_CENTER", "play_pause": "MEDIA_PLAY_PAUSE"}


def app_key(app: str) -> str:
    """Nom d'appli comparé comme le routeur : casse, accents et espaces ignorés (« Nétflix » = netflix)."""
    return "".join(c for c in unicodedata.normalize("NFD", app.casefold()) if not unicodedata.combining(c)).strip()


@tool("tv_status", "État de la TV du salon : allumée, appli en cours, volume, muet.", Level.N0, external=True)
def tv_status() -> dict:
    s = ha.state(PLAYER)
    a = s.get("attributes", {})
    volume = a.get("volume_level") if isinstance(a, dict) else None
    if not isinstance(s.get("state"), str) or not isinstance(a, dict) or not (
            volume is None or isinstance(volume, (int, float)) and not isinstance(volume, bool) and 0 <= volume <= 1):
        raise ha.HAError("réponse inattendue")
    # Le nom d'appli vient d'un tiers : on ne renvoie qu'un nom connu (constat S3).
    raw = a.get("app_id") or a.get("app_name")
    app = next((n for n, pkg in APPS.items() if pkg[0] == raw), "accueil" if raw == LAUNCHER else None if raw is None else "autre")
    muted = a.get("is_volume_muted")
    return {"state": s["state"], "app": app, "muted": muted if isinstance(muted, bool) else None,
            "volume_percent": None if volume is None else round(volume * 100)}


@tool("tv_on", "Allume la TV du salon.", Level.N1)
def tv_on() -> dict:
    ha.call_service("media_player", "turn_on", PLAYER)
    return {"tv": "on"}


@tool("tv_off", "Éteint la TV du salon (la barre de son suit en HDMI-CEC).", Level.N1)
def tv_off() -> dict:
    ha.call_service("media_player", "turn_off", PLAYER)
    return {"tv": "off"}


@tool("tv_volume", "Monte ou baisse le volume de la TV du salon (direction : up ou down, steps : 1 à 5 pas).",
      Level.N1, direction=str, steps=int)
def tv_volume(direction: str, steps: int) -> dict:
    if direction not in ("up", "down"):
        raise ValueError("direction : up ou down")
    if not 1 <= steps <= STEPS_MAX:
        raise ValueError(f"steps : 1 à {STEPS_MAX}")
    for _ in range(steps):
        ha.call_service("media_player", f"volume_{direction}", PLAYER)
    return {"volume": direction, "steps": steps}


@tool("tv_mute", "Coupe (muted=true) ou rétablit (muted=false) le son de la TV du salon.", Level.N1, muted=bool)
def tv_mute(muted: bool) -> dict:
    ha.call_service("media_player", "volume_mute", PLAYER, is_volume_muted=muted)
    return {"muted": muted}


@tool("tv_key", f"Touche de télécommande de la TV du salon : {', '.join(KEYS)}.", Level.N1, taint_blocked=True, button=str)
def tv_key(button: str) -> dict:
    if button not in KEYS:
        raise ValueError(f"touche inconnue (attendu : {', '.join(KEYS)})")
    ha.call_service("remote", "send_command", REMOTE, command=KEYS[button])
    return {"button": button}


@tool("tv_open_app", f"Lance une appli sur la TV du salon : {', '.join(APPS)}.", Level.N1, taint_blocked=True, app=str)
def tv_open_app(app: str) -> dict:
    entry = APPS.get(app_key(app))
    if entry is None:
        raise ValueError(f"appli inconnue (attendu : {', '.join(APPS)})")
    ha.call_service("remote", "turn_on", REMOTE, activity=entry[1])
    return {"app": app_key(app)}
