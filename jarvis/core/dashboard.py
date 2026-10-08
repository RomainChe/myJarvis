"""Bandeau d'état et encart Système de la PWA (Phase 6, N0, lecture seule).

Ville et coordonnées : `~/.jarvis/dashboard.json` (`{"city": "...", "lat": 0.0, "lon": 0.0}`), jamais dans le dépôt, pas de
géolocalisation. Météo : Open-Meteo (sans clé), mise en cache 15 min ; seuls des nombres en sortent (rien de la réponse
n'est relayé tel quel). Réseau : durée d'une connexion TCP vers 1.1.1.1:443. Pas de ligne d'audit : lecture N0 rafraîchie
toutes les quelques secondes.
"""
import json
import math
import socket
import threading
import time
import urllib.request
from pathlib import Path

CONFIG = Path.home() / ".jarvis" / "dashboard.json"
WEATHER_TTL_S, NET_TTL_S, SYSTEM_TTL_S, FAIL_TTL_S = 900, 10, 3, 60  # un échec est mis en cache aussi : pas de nouvel appel à chaque requête
PING_HOST = ("1.1.1.1", 443)
# Codes météo WMO regroupés (Open-Meteo) -> ciel en français.
SKY = ((0, "Dégagé"), (3, "Nuageux"), (48, "Brouillard"), (57, "Bruine"), (67, "Pluie"), (77, "Neige"), (82, "Averses"),
       (86, "Averses de neige"), (99, "Orage"))


def sky(code: int) -> str:
    return next((label for top, label in SKY if code <= top), "Variable")


def load_config(path: Path = CONFIG) -> dict | None:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        city, lat, lon = str(raw["city"])[:60], float(raw["lat"]), float(raw["lon"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return {"city": city, "lat": lat, "lon": lon} if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def fetch_weather(lat: float, lon: float) -> dict:
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat:.2f}&longitude={lon:.2f}&current=temperature_2m,weather_code"
    with urllib.request.urlopen(url, timeout=4) as r:  # ponytail: proxy système éventuel non filtré, ajouter un opener sans proxy si besoin
        cur = json.loads(r.read(4096))["current"]
    temp = float(cur["temperature_2m"])
    if not (math.isfinite(temp) and -90 <= temp <= 70):  # NaN/Infinity feraient échouer la sérialisation JSON
        raise ValueError("température hors bornes")
    return {"temp_c": round(temp, 1), "sky": sky(int(cur["weather_code"]))}


def ping_ms() -> int | None:
    start = time.monotonic()
    try:
        socket.create_connection(PING_HOST, timeout=2).close()
    except OSError:
        return None
    return round((time.monotonic() - start) * 1000)


def uptime_s() -> int | None:
    """Temps écoulé depuis le démarrage de Windows (GetTickCount64), None si indisponible."""
    try:
        import ctypes
        fn = ctypes.windll.kernel32.GetTickCount64
        fn.restype = ctypes.c_ulonglong
        return int(fn() // 1000)
    except (AttributeError, OSError):
        return None


def quality(ms: int | None) -> str:
    return "Hors ligne" if ms is None else "Excellente" if ms < 40 else "Bonne" if ms < 100 else "Moyenne" if ms < 250 else "Faible"


class Dashboard:
    def __init__(self, system, *, config=load_config, weather=fetch_weather, ping=ping_ms, clock=time.monotonic):
        self._system, self._config, self._weather, self._ping, self._clock = system, config, weather, ping, clock
        self._cache: dict[str, tuple[float, object, int]] = {}
        self._lock = threading.Lock()  # plusieurs onglets/appareils ne lancent pas les mêmes appels en parallèle

    def _cached(self, key: str, ttl: int, fn):
        with self._lock:
            hit = self._cache.get(key)
            if hit and self._clock() - hit[0] < hit[2]:
                return hit[1]
            try:
                value, keep = fn(), ttl
            except Exception:  # réseau, JSON, hors bornes : champ absent, jamais d'erreur vers l'écran
                value, keep = None, FAIL_TTL_S
            self._cache[key] = (self._clock(), value, keep)
            return value

    def snapshot(self) -> dict:
        cfg = self._config()
        ms = self._cached("net", NET_TTL_S, self._ping)
        return {
            "location": cfg["city"] if cfg else None,
            "weather": self._cached("weather", WEATHER_TTL_S, lambda: self._weather(cfg["lat"], cfg["lon"])) if cfg else None,
            "network": {"ms": ms, "quality": quality(ms)},
            "system": self._cached("system", SYSTEM_TTL_S, self._system),
            "uptime_s": uptime_s(),
        }
