"""Consommation électrique (N0, lecture du cache local `~/.jarvis/conso.db`, voir jarvis/core/conso.py)."""
from jarvis.core import conseils, conso
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
        if p.get("prev_partial"):
            out += f" (mesurés sur {p['prev_hours']:.1f} h seulement)"
    out += "."
    if p["partial"]:
        out += f" Mesuré sur {p['hours']:.1f} h seulement : le total peut être sous-estimé (PC éteint ou Core arrêté)."
    return out


def _period(periode: str) -> str:
    key = ALIASES.get(fold(periode.strip()).replace("'", " ").replace("’", " "))  # apostrophes droite et typographique
    if key is None:
        raise ValueError("période invalide : jour, semaine ou mois")
    return key


HOME_WHEN = {"jour": "hier", "semaine": "sur les 7 jours jusqu'à hier", "mois": "sur les 30 jours jusqu'à hier"}
HOME_BEFORE = {"jour": "la veille", "semaine": "les 7 jours d'avant", "mois": "les 30 jours d'avant"}


def home_summary(snap: dict, periode: str) -> str:
    """Phrase parlable du total logement ; la part du PC n'est dite que sur des jours mesurés des deux côtés."""
    p = snap["periods"][periode]
    if snap.get("configured") is False:
        return "Le compteur n'est pas encore relié (MyElectricalData non configuré ou aucun relevé reçu) : donnée indisponible."
    out = ""
    if snap.get("stale") and snap.get("last_day"):
        out = f"Dernier relevé du compteur : {snap['last_day'][8:]}/{snap['last_day'][5:7]}. "
    if p["kwh"] is None:
        return out + "Je n'ai pas de relevé du compteur pour cette période : donnée indisponible."
    out += f"Le logement a consommé {_n(p['kwh'], 'kWh')} {HOME_WHEN[periode]}"
    if p["eur"] is not None:
        out += f" (environ {_n(p['eur'], '€')})"
    if p["prev_kwh"] is not None:
        out += f", contre {_n(p['prev_kwh'], 'kWh')} {HOME_BEFORE[periode]}"
        if p.get("prev_partial"):
            out += f" ({p['prev_days']} jour{'s' if p['prev_days'] > 1 else ''} seulement)"
    out += "."
    if p["partial"]:
        out += f" {p['days']} jours relevés seulement : le total est partiel."
    if p["pc_share"] is not None:
        out += f" Le PC en représente {round(p['pc_share'] * 100)} %."
        if p.get("pc_partial"):
            out += " (mesure du PC partielle : part minimale)"
    return out


def advice_summary(adv: dict) -> str:
    """Phrase parlable : les conseils déjà construits par jarvis/core/conseils.py, jamais reformulés par le LLM."""
    if not adv["available"]:
        return "Je n'ai pas encore de mesure de consommation pour te conseiller : donnée indisponible."
    if not adv["items"] and not adv.get("evaluable"):
        return "Pas assez de relevés complets sur 7 jours pour te conseiller : donnée insuffisante."
    if not adv["items"]:
        return "Rien d'anormal sur tes chiffres de la semaine : pas de conseil pour le moment."
    return " ".join(a["text"] for a in adv["items"])


@tool("conso_conseils", "Conseils pour consommer moins d'électricité, déduits des chiffres du logement et du PC "
                        "(hausse sur 7 jours, part du PC). Chaque conseil cite son chiffre.", Level.N0, private=True)
def conso_conseils() -> str:
    return advice_summary(conseils.snapshot())


@tool("conso_pc", "Consommation électrique du PC mesurée par sa prise connectée : kWh, € et comparaison à la période "
                  "précédente. `periode` : jour, semaine (7 jours) ou mois (30 jours).", Level.N0, private=True, periode=str)
def conso_pc(periode: str) -> str:
    return summary(conso.snapshot(), _period(periode))


@tool("conso_totale", "Consommation électrique totale du logement (compteur Linky, relevé de la veille) : kWh, € et "
                      "comparaison à la période précédente. `periode` : jour (hier), semaine (7 jours) ou mois (30 jours).",
      Level.N0, private=True, periode=str)
def conso_totale(periode: str) -> str:
    return home_summary(conso.home_snapshot(), _period(periode))
