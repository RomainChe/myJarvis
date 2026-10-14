"""Conseils de consommation : règles déterministes sur les totaux quotidiens (N0). Aucun LLM : chaque phrase est construite
ici et cite le chiffre qui la justifie. Une période partielle ne déclenche jamais de règle de comparaison."""
from jarvis.core import conso

RISE_HOME_PCT, RISE_HOME_KWH = 15, 5.0  # logement : hausse d'au moins 15 % ET 5 kWh sur 7 jours
RISE_PC_PCT, RISE_PC_KWH = 25, 1.0
PC_SHARE_MIN, PC_DAYS_MIN = 0.25, 5  # la part du PC exige 5 jours mesurés des deux côtés


def _kwh(v: float) -> str:
    return f"{v:.1f}".replace(".", ",") + " kWh"


def _rise(p: dict, pct: int, min_kwh: float) -> float | None:
    """Hausse en kWh si la période et la précédente sont complètes et dépassent les deux seuils, sinon None."""
    if p["kwh"] is None or p["prev_kwh"] is None or p["partial"] or p.get("prev_partial") or p["prev_kwh"] <= 0:
        return None
    now, before = round(p["kwh"], 1), round(p["prev_kwh"], 1)  # on juge les chiffres tels qu'ils sont cités
    delta = round(now - before, 1)
    return delta if before > 0 and delta >= min_kwh and delta / before * 100 >= pct else None


def advice(home: dict, pc: dict, price: float | None = None) -> list[dict]:
    """[{id, text}] ; liste vide = rien d'anormal sur les chiffres disponibles (ou aucune donnée)."""
    out = []
    h, c = home["periods"]["semaine"], pc["periods"]["semaine"]
    if (d := _rise(h, RISE_HOME_PCT, RISE_HOME_KWH)) is not None:
        cost = f", soit environ {d * price:.2f} €".replace(".", ",") if price else ""
        out.append({"id": "hausse_logement", "text": f"Ta consommation a augmenté de {_kwh(d)} sur 7 jours{cost} : "
                                                       f"{_kwh(h['kwh'])} contre {_kwh(h['prev_kwh'])} les 7 jours d'avant."})
    if (h["pc_share"] is not None and h["pc_share"] >= PC_SHARE_MIN and h["pc_days"] >= PC_DAYS_MIN
            and not h["pc_capped"]):
        least = "au moins " if h.get("pc_partial") else ""
        pct = int(h["pc_share"] * 100 + 0.5)
        out.append({"id": "part_pc", "text": f"Le PC représente {least}{pct} % de ta consommation sur {h['pc_days']} jours "
                                              f"mesurés ({_kwh(h['pc_base_kwh'])} au total). "
                                              "Mets-le en veille quand tu ne t'en sers pas."})
    if (d := _rise(c, RISE_PC_PCT, RISE_PC_KWH)) is not None:
        out.append({"id": "hausse_pc", "text": f"Le PC a consommé {_kwh(c['kwh'])} sur 7 jours contre {_kwh(c['prev_kwh'])} "
                                                f"les 7 jours d'avant (+{_kwh(d)})."})
    return out


def snapshot(db=None, now=None, config=None) -> dict:
    home, pc = conso.home_snapshot(db, now, config), conso.snapshot(db, now, config)
    h, c = home["periods"]["semaine"], pc["periods"]["semaine"]

    def complete(p):
        return p["kwh"] is not None and p["prev_kwh"] is not None and not p["partial"] and not p.get("prev_partial")

    # `evaluable` : au moins une règle a pu être jugée ; sinon « rien d'anormal » serait un faux rassurant
    evaluable = complete(h) or complete(c) or h["pc_days"] >= PC_DAYS_MIN
    return {"available": home["configured"] or pc["configured"], "evaluable": evaluable,
            "items": advice(home, pc, home["price_kwh"])}
