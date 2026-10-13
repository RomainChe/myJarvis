"""Consommation électrique (N0, lecture du cache local `~/.jarvis/conso.db`, voir jarvis/core/conso.py)."""
from jarvis.core import conso
from jarvis.core.router import fold
from jarvis.core.tools import Level, tool

WHEN = {"jour": "aujourd'hui", "semaine": "sur les 7 derniers jours", "mois": "sur les 30 derniers jours"}
BEFORE = {"jour": "hier", "semaine": "les 7 jours d'avant", "mois": "les 30 jours d'avant"}
ALIASES = {"jour": "jour", "aujourd hui": "jour", "semaine": "semaine", "mois": "mois"}


def _n(value: float, unit: str) -> str:
    return f"{value:.2f}".replace(".", ",") + f" {unit}"


def summary(snap: dict, periode: str) -> str:
    """Phrase parlable ; chaque chiffre vient de la base, jamais d'une estimation."""
    p = snap["periods"][periode]
    if p["kwh"] is None:
        return "Je n'ai pas encore de mesure de la prise du PC pour cette période : donnée indisponible."
    out = f"Le PC a consommé {_n(p['kwh'], 'kWh')} {WHEN[periode]}"
    if p["eur"] is not None:
        out += f" (environ {_n(p['eur'], '€')})"
    if p["prev_kwh"] is not None:
        out += f", contre {_n(p['prev_kwh'], 'kWh')} {BEFORE[periode]}"
    out += "."
    if p["partial"]:
        out += f" Mesuré sur {p['hours']:.1f} h seulement : le total est sous-estimé."
    return out


@tool("conso_pc", "Consommation électrique du PC mesurée par sa prise connectée : kWh, € et comparaison à la période "
                  "précédente. `periode` : jour, semaine (7 jours) ou mois (30 jours).", Level.N0, periode=str)
def conso_pc(periode: str) -> str:
    key = ALIASES.get(fold(periode.strip()).replace("'", " "))
    if key is None:
        raise ValueError("période invalide : jour, semaine ou mois")
    return summary(conso.snapshot(), key)
