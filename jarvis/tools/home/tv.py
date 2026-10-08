"""TV du salon (Google TV) via Home Assistant : Android TV Remote (`media_player.salon_tv`, `remote.salon_tv`).

Le volume n'a pas de valeur absolue sur cette intégration : montée/descente par pas. La barre de son suit en HDMI-CEC.
"""
from jarvis.core import ha
from jarvis.core.tools import Level, tool

PLAYER = "media_player.salon_tv"
REMOTE = "remote.salon_tv"
STEPS_MAX = 5
# Paquets Android des applis lançables ; une appli absente de la liste n'est pas lançable (nom = donnée, pas commande).
APPS = {"youtube": "com.google.android.youtube.tv", "netflix": "com.netflix.ninja",
        "prime video": "com.amazon.amazonvideo.livingroom", "disney+": "com.disney.disneyplus"}
LAUNCHER = "com.google.android.apps.tv.launcherx"
KEYS = {"home": "HOME", "back": "BACK", "up": "DPAD_UP", "down": "DPAD_DOWN", "left": "DPAD_LEFT",
        "right": "DPAD_RIGHT", "ok": "DPAD_CENTER", "play_pause": "MEDIA_PLAY_PAUSE"}


@tool("tv_status", "État de la TV du salon : allumée, appli en cours, volume, muet.", Level.N0, external=True)
def tv_status() -> dict:
    s = ha.state(PLAYER)
    a = s.get("attributes", {})
    volume = a.get("volume_level")
    # Le nom d'appli vient d'un tiers : on ne renvoie qu'un nom connu (constat S3).
    raw = a.get("app_id") or a.get("app_name")
    app = next((n for n, pkg in APPS.items() if pkg == raw), "accueil" if raw == LAUNCHER else None if raw is None else "autre")
    return {"state": s["state"], "app": app, "muted": a.get("is_volume_muted"),
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
    package = APPS.get(app.casefold().strip())
    if package is None:
        raise ValueError(f"appli inconnue (attendu : {', '.join(APPS)})")
    ha.call_service("remote", "turn_on", REMOTE, activity=f"market://launch?id={package}")
    return {"app": app}
