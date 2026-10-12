"""Météo du lieu configuré (`~/.jarvis/dashboard.json`) : même source et même cache que le bandeau du dashboard."""
import time

from jarvis.core import dashboard
from jarvis.core.tools import Level, tool

_cache: tuple[float, dict] | None = None


def _weather() -> dict:
    global _cache
    if _cache is None or time.monotonic() - _cache[0] > dashboard.WEATHER_TTL_S:
        cfg = dashboard.load_config()
        if cfg is None:
            raise ValueError("lieu non configuré (~/.jarvis/dashboard.json)")
        try:
            _cache = (time.monotonic(), dashboard.fetch_weather(cfg["lat"], cfg["lon"]))
        except Exception:  # réseau, JSON, hors bornes : le détail pourrait contenir l'URL (donc les coordonnées)
            raise ValueError("météo indisponible") from None
    return _cache[1]


def _fmt(w: dict) -> str:
    parts = [f"{w['temp_c']} °C" + (f" (ressenti {w['feels_c']})" if w["feels_c"] is not None else ""), w["sky"].lower()]
    if w["wind_kmh"] is not None:
        parts.append(f"vent {w['wind_kmh']} km/h" + (f", rafales {w['gust_kmh']}" if w["gust_kmh"] else ""))
    if w["min_c"] is not None and w["max_c"] is not None:
        parts.append(f"aujourd'hui {w['min_c']} à {w['max_c']} °C")
    if w["rain_chance"] is not None:
        parts.append(f"{w['rain_chance']:.0f} % de risque de pluie")
    parts.append("signaux : " + ", ".join(w["alerts"]) if w["alerts"] else "aucun signal d'alerte")
    return ", ".join(parts) + " (signaux calculés, pas la vigilance officielle)."


@tool("weather_now", "Météo actuelle et du jour au lieu de la maison : température, ressenti, ciel (pluie, orage, beau), "
      "vent, rafales, risque de pluie, min/max et signaux d'alerte calculés. Ce ne sont pas les vigilances officielles.", Level.N0)
def weather_now() -> str:
    return _fmt(_weather())
