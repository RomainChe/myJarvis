"""AdGuard Home du mini-PC (DNS anti-pub de la TV, voir docs/TV_NETTOYAGE.md §6)."""
from jarvis.core import adguard
from jarvis.core.tools import Level, tool


@tool("adguard_stats", "Statistiques du blocage de pubs et de pistage (AdGuard Home) : requêtes DNS, part bloquée, "
                       "domaines les plus bloqués.", Level.N0, external=True)
def adguard_stats() -> dict:
    s = adguard.stats()
    return {"requetes": s["total"], "bloquees": s["blocked"],
            "part_bloquee_pct": round(100 * s["blocked"] / s["total"], 1) if s["total"] else 0.0,
            "top_bloques": [f"{d} ({n})" for d, n in s["top"]]}


@tool("adguard_pause", "Coupe le blocage de pubs d'AdGuard Home pour `minutes` minutes (1 à 15) : un site ou une appli "
                       "bloqués par erreur. Le blocage revient seul à la fin.", Level.N1, taint_blocked=True, minutes=int)
def adguard_pause(minutes: int) -> dict:
    adguard.pause(minutes)
    return {"blocage": f"coupé {minutes} min"}
