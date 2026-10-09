"""Bilan de cycle de paie pour l'onglet Finances : classe les opérations bancaires lues (banking.view) selon les règles
du propriétaire. Crédit Mutuel est reconnu par libellé ; Trade Republic n'en fournit aucun : date, jour et montant.
Pur calcul, rien n'est écrit ni gardé. Les libellés bancaires sont du contenu externe : ils ne servent qu'à comparer."""
from collections import defaultdict
from datetime import date, timedelta

CM, TR = "Crédit Mutuel", "Trade Republic"
PAY_MIN = 1000  # un crédit Crédit Mutuel ≥ 1 000 € hors virement interne = la paie
PLANS = (10, 15, 13, 7)  # plans d'épargne du mercredi ; 60–75 € = PEA
# (mot du libellé, emoji, nom, catégorie) pour les marchands reconnaissables ; le reste va en Loisirs
MERCHANTS = (
    ("CARREFOUR", "🛒", "Courses", "Courses"), ("LECLERC", "🛒", "Courses", "Courses"), ("LIDL", "🛒", "Courses", "Courses"),
    ("AUCHAN", "🛒", "Courses", "Courses"), ("UBER EATS", "🍔", "Uber Eats", "Restaurants"), ("MCDO", "🍔", "McDonald's", "Restaurants"),
    ("RESTAURANT", "🍽️", "Restaurant", "Restaurants"), ("SHELL", "⛽", "Essence", "Transport"), ("TOTAL", "⛽", "Essence", "Transport"),
    ("SNCF", "🚆", "SNCF", "Transport"), ("TICKETMASTER", "🎟️", "Ticketmaster", "Loisirs"), ("BILLETWEB", "🎫", "Billetweb", "Loisirs"),
    ("BASIC", "🏋️", "Basic Fit", "Sport"), ("PHARMACIE", "💊", "Pharmacie", "Santé"), ("AMAZON", "📦", "Amazon", "Shopping"),
)


def _row(emoji, name, amount, cat=None, detail="", bank="", day=""):
    return {"emoji": emoji, "name": name, "amount": round(amount, 2), "cat": cat, "detail": detail, "bank": bank, "date": day}


def _fr(day: str) -> str:
    return f"{day[8:10]}/{day[5:7]}"


def classify(t: dict) -> tuple[str, dict]:
    """(genre, ligne) : income, internal, refund, ignore, fixed, saving, conso. `t` = {date, amount, label, bank}."""
    label, amount, bank, day = (t.get("label") or "").upper(), t["amount"], t["bank"], t["date"]
    d = date.fromisoformat(day)
    out = -amount
    mk = lambda *a, **k: _row(*a, bank=bank, day=day, **k)  # noqa: E731
    if amount > 0:
        if bank == TR:
            return ("ignore", mk("💹", "Dividendes reçus", amount)) if amount < 5 else ("internal", mk("🔁", "Virement interne", amount))
        if "NEWORCH" in label:
            return "ignore", mk("🧾", "Remboursement employeur", amount)
        if "ROMAIN" in label and "CHEVALIER" in label or "TRADE" in label:
            return "internal", mk("🔁", "Virement interne", amount)
        if label.startswith("VIR INST") and any(f" {p} " in f"{label} " for p in ("M.", "MLE", "MLLE", "MME")):
            return "refund", mk("🤝", " ".join(t["label"].split()[3:]).title() or "Ami", amount)
        return ("income", mk("💰", "Paie", amount)) if amount >= PAY_MIN else ("ignore", mk("➕", "Entrée", amount))
    if "ECH PRET" in label:
        return "fixed", mk("🏠", "Crédit", out, "Logement")
    if "ASSURANCE HABITATION" in label:
        return "fixed", mk("🛡️", "Assurance habitation", out, "Logement")
    if "CONSEIL INVEST" in label:
        return "fixed", mk("🏢", "Charges de copropriété", out, "Logement")
    if "COTIS EUROCOMPTE" in label:
        return "fixed", mk("🏦", "Cotisation compte", out, "Frais bancaires")
    if "LIVRET DE DEVELOPPEMENT" in label:
        return "saving", mk("🐷", "Livret LDDS", out, "Épargne")
    if "VEDENE" in label or "ASF-" in label:
        return "conso", mk("🛣️", "Péages ASF", out, "Transport")
    if "DIRECTION GENERALE" in label:
        return "conso", mk("🏛️", "Impôt sur le revenu", out, "Impôts")
    if "TRADE" in label or "ROMAIN" in label and "CHEVALIER" in label:
        return "internal", mk("🔁", "Virement interne", out)
    for word, emoji, name, cat in MERCHANTS:
        if word in label:
            return "conso", mk(emoji, name, out, cat)
    if bank == CM:
        return "conso", mk("🎲", "Loisirs divers (déduits)", out, "Loisirs")
    # Trade Republic sans libellé : jour, montant, centimes
    cents = round(out * 100) % 100 != 0
    if out == 24.99:
        return ("fixed", mk("🌐", "Internet", out, "Abonnements")) if d.day < 19 else ("fixed", mk("🏋️", "Basic Fit", out, "Sport"))
    if out in (1, 16):
        return "conso", mk("❤️", "Dons Fondation de France", out, "Dons")
    if 200 <= out <= 230 and d.month == 9 and d.day >= 22:
        return "conso", mk("🤖", "Claude Code Pro", out, "Abonnements")
    if d.weekday() == 2 and out in PLANS or d.weekday() == 2 and 60 <= out <= 75:
        return "saving", mk("📈", "Épargne programmée", out, "Épargne")
    if cents and (d.day <= 3 and out < 5 or d.weekday() == 2 and out <= 22):
        return "saving", mk("💸", "Saveback + arrondis", out, "Épargne")
    if 80 <= out <= 90:
        return "conso", mk("⛽", "Essence", out, "Transport")
    if 60 <= out <= 130:
        return "conso", mk("🛒", "Courses", out, "Courses")
    return "conso", mk("🎲", "Loisirs divers (déduits)", out, "Loisirs")


def _merge(rows: list[dict], name: str, note) -> dict:
    """Plusieurs lignes d'un même nom → une seule (crédit, péages, dons, épargne programmée...)."""
    rows = sorted(rows, key=lambda r: r["date"])
    return dict(rows[0], amount=round(sum(r["amount"] for r in rows), 2), detail=note(rows), date=rows[0]["date"] if len(rows) == 1 else rows[-1]["date"])


def _group(rows: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for r in rows:
        by[r["name"]].append(r)
    out = []
    for name, rs in by.items():
        if len(rs) == 1 and name not in ("Crédit",):
            out.append(rs[0])
            continue
        amounts = " + ".join(f"{r['amount']:.2f}".replace(".", ",") + " €" for r in sorted(rs, key=lambda r: -r["amount"]))
        notes = {
            "Crédit": lambda x: f"{len(x)} prêts : {amounts}",
            "Épargne programmée": lambda x: f"{len({r['date'] for r in x})} mercredis · plans {sum(r['amount'] for r in x if r['amount'] in PLANS):.0f} € + PEA "
                                           f"{sum(r['amount'] for r in x if r['amount'] not in PLANS):.0f} €",
        }
        note = notes.get(name, lambda x: f"{len(x)} paiements · " + ", ".join(_fr(r["date"]) for r in x[:3]) + (" …" if len(x) > 3 else ""))
        out.append(_merge(rs, name, note))
    return sorted(out, key=lambda r: (r["date"], r["name"]))


def _pct(a: float, b: float) -> int:
    return round(a / b * 100) if b else 0


def report(txs: list[dict], today: date | None = None) -> dict | None:
    """Bilan du cycle en cours (depuis la dernière paie). None si aucune paie n'est visible dans l'historique."""
    today = today or date.today()
    kinds = [(k, r) for k, r in (classify(t) for t in txs if t.get("date") and t.get("bank") in (CM, TR)) if r["date"] <= today.isoformat()]
    pays = [r for k, r in kinds if k == "income" and r["bank"] == CM]
    if not pays:
        return None
    pay = max(pays, key=lambda r: r["date"])
    cyc = [(k, r) for k, r in kinds if r["date"] >= pay["date"]]
    by = lambda kind: [r for k, r in cyc if k == kind]  # noqa: E731
    fixed, saving, conso, refunds, internal = _group(by("fixed")), _group(by("saving")), _group(by("conso")), by("refund"), by("internal")
    pay_amount = sum(r["amount"] for r in by("income") if r["date"] == pay["date"])
    fixed_total, saved_total = round(sum(r["amount"] for r in fixed), 2), round(sum(r["amount"] for r in saving), 2)
    gross = round(sum(r["amount"] for r in conso), 2)
    refunded = round(sum(r["amount"] for r in refunds), 2)
    consumed = round(gross - refunded, 2)
    left = round(pay_amount - fixed_total - saved_total - consumed, 2)
    cats = defaultdict(float)
    for r in conso:
        cats[r["cat"]] += r["amount"]
    cats = [{"name": n, "amount": round(a, 2)} for n, a in sorted(cats.items(), key=lambda x: -x[1])]
    rate = _pct(saved_total, pay_amount)
    covered = [r for r in internal if r["amount"] > 0 and r["bank"] == CM]
    points = [{"icon": "✅", "text": f"Taux d'épargne de {rate} % — {saved_total:.2f} € mis de côté sur {pay_amount:.2f} € de paie.".replace(".", ",")}]
    if cats and gross and cats[0]["amount"] / gross >= .3 and cats[0]["name"] not in ("Loisirs",):
        points.append({"icon": "💡", "text": f"{cats[0]['name']} pèse {_pct(cats[0]['amount'], gross)} % de la consommation ({cats[0]['amount']:.2f} €).".replace(".", ",")})
    if left < 0:
        points.append({"icon": "⚠️", "text": f"Sorties supérieures à la paie de {-left:.2f} €".replace(".", ",") + (f" — couvert par ton autre compte ({sum(r['amount'] for r in covered):.2f} €).".replace(".", ",") if covered else ".")})
    target = round(pay_amount - fixed_total - saved_total, -1)
    recos = []
    if left < 0 and target > 0:
        recos.append(f"🎯 Viser une consommation sous {target:.0f} € par cycle pour ne plus puiser dans ton autre compte.")
    if rate < 20:
        recos.append("🌱 Remonter le taux d'épargne vers le repère de 20 %.")
    if any(r["name"] == "Cotisation compte" for r in fixed):
        recos.append("🏦 Comparer la cotisation Crédit Mutuel (≈ 99 €/an) avec une offre gratuite.")
    subs = [r for r in fixed if r["name"] in ("Charges de copropriété", "Assurance habitation", "Internet", "Basic Fit", "Cotisation compte")]
    subs += [r for r in conso if r["name"] == "Claude Code Pro"]
    week = None
    if today.weekday() == 0:
        mon = today - timedelta(days=7)
        sun = today - timedelta(days=1)
        wk = [r for k, r in kinds if k in ("fixed", "conso") and mon.isoformat() <= r["date"] <= sun.isoformat()]
        week = {"spent": round(sum(r["amount"] for r in wk), 2), "top": sorted(wk, key=lambda r: -r["amount"])[:2],
                "internal": [r for r in internal if mon.isoformat() <= r["date"] <= sun.isoformat()]}
    return {
        "start": pay["date"], "pay": {"amount": round(pay_amount, 2), "date": pay["date"]},
        "fixed": {"total": fixed_total, "pct": _pct(fixed_total, pay_amount), "items": fixed},
        "saving": {"total": saved_total, "rate": rate, "items": saving},
        "conso": {"total": consumed, "gross": gross, "cats": cats, "refunds": {"total": refunded, "items": refunds},
                  "detail": sorted(conso, key=lambda r: -r["amount"])},
        "left": left, "covered": {"total": round(sum(r["amount"] for r in covered), 2), "items": covered},
        "points": points, "subs": subs, "recos": recos[:3], "week": week,
    }
