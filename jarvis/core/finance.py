"""Onglet Finances de la PWA (Phase 6 point 4, étape 1, lecture seule).

Lit les rapports « [Dépenses] Semaine NN » (.eml) déposés par la tâche planifiée dans `~/.jarvis/finance/` (ou le dossier de
`~/.jarvis/finance.json` : `{"dir": "..."}`). Seuls des montants et quelques libellés de catégorie en sortent : ni expéditeur,
ni texte libre, ni libellé bancaire. Données très sensibles : aucun outil LLM, la route exige l'authentification et chaque
lecture est journalisée (N2). Le format du rapport n'est pas garanti : un champ introuvable vaut `None`, jamais une erreur.
"""
import email
import json
import re
from email import policy
from html import unescape
from itertools import islice
from pathlib import Path

CONFIG = Path.home() / ".jarvis" / "finance.json"
DEFAULT_DIR = Path.home() / ".jarvis" / "finance"
MAX_BYTES, MAX_FILES, MAX_WEEKS, MAX_CATS, MAX_SEGMENT = 200_000, 24, 12, 8, 20_000  # 24 fichiers récents ≤ 4,8 Mo lus
SPACES = "\\s\u00a0\u202f"
AMOUNT = rf"([+-]?\d[\d{SPACES}]{{0,12}}(?:,\d{{1,2}})?)\s*€"


def finance_dir(path: Path = CONFIG) -> Path:
    try:
        return Path(json.loads(Path(path).read_text(encoding="utf-8"))["dir"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_DIR


def _num(s: str | None) -> float | None:
    try:
        return round(float(re.sub(rf"[{SPACES}]", "", s).replace(",", ".")), 2)
    except (TypeError, ValueError, AttributeError):
        return None


def _tokens(html: str) -> str:
    """HTML → texte, blocs séparés par « | » (les emojis de mise en forme sont ignorés par les motifs)."""
    return re.sub(r"(\|\s*)+", "|", unescape(re.sub(r"<[^<>]{0,2000}>", "|", html)))  # borné : pas de quadratique sur « <<<< »


def _after(text: str, label: str) -> float | None:
    m = re.search(rf"\|{label}\|≈?\s*{AMOUNT}", text)
    return _num(m.group(1)) if m else None


def _card(text: str, label: str) -> dict | None:
    """Carte de synthèse : « |💸 Dépenses|604,77 €|+247,82 € (+69 %) vs S39 »."""
    m = re.search(rf"\|[^|]*{label}\|{AMOUNT}(?:\|[^|]*?\(([+-]?\d+)[{SPACES}]?%\))?", text)
    if not m:
        return None
    return {"amount": _num(m.group(1)), "vs_pct": int(m.group(2)) if m.group(2) else None}


def _categories(text: str) -> list[dict]:
    start = text.find("Consommation de la semaine")
    end = text.find("Total consommation", start) if start >= 0 else -1
    seg = text[start:end][:MAX_SEGMENT] if end > start >= 0 else ""
    out = []
    for m in re.finditer(rf"\|[^|\w]*([^|]{{2,40}})\|(\d{{1,3}})[{SPACES}]?%\|{AMOUNT}", seg):
        amount = _num(m.group(3))
        if amount is not None:
            out.append({"name": " ".join(m.group(1).split()), "pct": int(m.group(2)), "amount": amount})
    return out[:MAX_CATS]


def parse(raw: bytes) -> dict | None:
    msg = email.message_from_bytes(raw, policy=policy.default)
    wk = re.search(r"^\[Dépenses\]\s*Semaine\s+(\d{1,2})", str(msg["Subject"] or ""))  # objet exact : la recherche IMAP est plus large
    try:
        body = msg.get_body(("html",))
        text = _tokens(body.get_content() if body else "")
        year = msg["Date"].datetime.year
    except Exception:  # Date ou MIME hostile : le rapport est ignoré
        return None
    if not wk or not 1 <= int(wk.group(1)) <= 53:
        return None
    period = re.search(r"\|(Du lundi[^|]{0,60}?)(?: ·|\|)", text)
    per_day = re.search(r"≈\s*(\d[\d,]*)\s*€/jour", text)
    return {
        "week": int(wk.group(1)), "year": year, "period": " ".join(period.group(1).split()) if period else None,
        "spent": _card(text, "Dépenses"), "saved": _card(text, "dont épargne"), "consumed": _card(text, "Consommation"),
        "income": _card(text, "Entrées"), "left_to_live": _after(text, "Reste à vivre"),
        "per_day": _num(per_day.group(1)) if per_day else None,
        "balance": _after(text, "Total disponible"), "categories": _categories(text),
    }


def _recent(root: Path) -> list[Path]:
    """Les MAX_FILES .eml les plus récents (par date de modification), fichiers réguliers dans `root` seulement."""
    base, found = root.resolve(), []
    for f in islice(root.glob("*.eml"), 500):
        try:
            if not f.is_symlink() and f.resolve().parent == base:
                found.append((f.stat().st_mtime, f))
        except OSError:
            continue
    return [f for _, f in sorted(found, reverse=True)[:MAX_FILES]]


def snapshot(root: Path | None = None) -> dict:
    root = Path(root) if root else finance_dir()
    weeks = []
    for f in _recent(root) if root.is_dir() else []:
        try:
            with f.open("rb") as h:
                raw = h.read(MAX_BYTES + 1)
        except OSError:
            continue
        report = parse(raw) if len(raw) <= MAX_BYTES else None
        if report:
            weeks.append(report)
    weeks.sort(key=lambda w: (w["year"], w["week"]), reverse=True)
    return {"configured": root.is_dir(), "latest": weeks[0] if weeks else None,
            "trend": [{"week": w["week"], "year": w["year"], "spent": (w["spent"] or {}).get("amount"),
                       "saved": (w["saved"] or {}).get("amount"), "consumed": (w["consumed"] or {}).get("amount")}
                      for w in weeks[:MAX_WEEKS]][::-1]}
