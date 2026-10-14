"""Conseils de consommation : règles déterministes sur les totaux quotidiens (N0). Aucun LLM : chaque phrase est construite
ici et cite le chiffre qui la justifie. Une période partielle ne déclenche jamais de règle de comparaison."""
from jarvis.core import conso

RISE_HOME_PCT, RISE_HOME_KWH = 15, 5.0  # logement : hausse d'au moins 15 % ET 5 kWh sur 7 jours
RISE_PC_PCT, RISE_PC_KWH = 25, 1.0
PC_SHARE_MIN = 0.25


def _kwh(v: float) -> str:
    return f"{v:.1f}".replace(".", ",") + " kWh"


def _rise(p: dict, pct: int, min_kwh: float) -> float | None:
    """Hausse en kWh si la période et la précédente sont complètes et dépassent les deux seuils, sinon None."""
    if p["kwh"] is None or p["prev_kwh"] is None or p["partial"] or p.get("prev_partial") or p["prev_kwh"] <= 0:
        return None
    delta = p["kwh"] - p["prev_kwh"]
    return delta if delta >= min_kwh and delta / p["prev_kwh"] * 100 >= pct else None


def advice(home: dict, pc: dict, price: float | None = None) -> list[dict]:
    """[{id, text}] ; liste vide = rien d'anormal sur les chiffres disponibles (ou aucune donnée)."""
    out = []
    h, c = home["periods"]["semaine"], pc["periods"]["semaine"]
    if (d := _rise(h, RISE_HOME_PCT, RISE_HOME_KWH)) is not None:
        cost = f", soit environ {d * price:.2f} €".replace(".", ",") if price else ""
        out.append({"id": "hausse_logement", "text": f"Ta consommation a augmenté de {_kwh(d)} sur 7 jours{cost} : "
                                                       f"{_kwh(h['kwh'])} contre {_kwh(h['prev_kwh'])} les 7 jours d'avant."})
    if h["pc_share"] is not None and h["pc_share"] >= PC_SHARE_MIN:
        least = "au moins " if h.get("pc_partial") else ""
        out.append({"id": "part_pc", "text": f"Le PC représente {least}{round(h['pc_share'] * 100)} % de ta consommation "
                                              f"sur 7 jours ({_kwh(h['kwh'])} au total). Éteins-le plutôt que de le laisser en veille."})
    if (d := _rise(c, RISE_PC_PCT, RISE_PC_KWH)) is not None:
        out.append({"id": "hausse_pc", "text": f"Le PC a consommé {_kwh(c['kwh'])} sur 7 jours contre {_kwh(c['prev_kwh'])} "
                                                f"les 7 jours d'avant (+{_kwh(d)})."})
    return out


def snapshot(db=None, now=None, config=None) -> dict:
    home, pc = conso.home_snapshot(db, now, config), conso.snapshot(db, now, config)
    return {"available": home["configured"] or pc["configured"], "items": advice(home, pc, home["price_kwh"])}
