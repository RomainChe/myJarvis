"""Onglet Veille IA de la PWA (Phase 6 point 5, lecture seule).

Lit les envois du projet veille-ia (« [Veille IA] Semaine NN », « [Veille Plugins] Semaine NN ») copiés en .eml dans
`~/.jarvis/veille/` par `python -m jarvis veille fetch` (ou le dossier de `~/.jarvis/veille.json` : `{"dir": "..."}`).
Le contenu a été écrit par un agent qui lit le web : c'est une DONNÉE non fiable. Il n'est jamais montré au LLM, n'est
affiché qu'en texte (jamais en HTML), et seuls les liens https sortent, avec leur domaine. Le format du mail n'étant pas
garanti, l'extraction est générique : titre, blocs de texte, sources ; chaque <li> devient une actu (`items` : lignes + lien).
"""
import email
import json
import re
from email import policy
from html.parser import HTMLParser
from itertools import islice
from pathlib import Path
from urllib.parse import urlsplit

CONFIG = Path.home() / ".jarvis" / "veille.json"
DEFAULT_DIR = Path.home() / ".jarvis" / "veille"
MAX_BYTES, MAX_FILES, MAX_ISSUES, MAX_BLOCKS, MAX_LINKS, BLOCK, LABEL = 200_000, 24, 12, 14, 12, 260, 80
MAX_ITEMS, ITEM_LINES = 10, 4
KINDS = {"IA": "actus", "Plugins": "plugins"}
SUBJECT = re.compile(r"^\[Veille (IA|Plugins)\]\s*Semaine\s+(\d{1,2})\b")
SKIP = {"style", "script", "title", "head"}
BLOCK_TAGS = {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "table", "ul", "ol"}


def veille_dir(path: Path = CONFIG) -> Path:
    try:
        return Path(json.loads(Path(path).read_text(encoding="utf-8"))["dir"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_DIR


def _clean(text: str, n: int) -> str:
    return " ".join("".join(c if c.isprintable() else " " for c in text).split())[:n]


class _Page(HTMLParser):
    """Texte en blocs et liens https (HTMLParser est linéaire : pas de regex sur du HTML hostile)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.links, self.items, self._buf, self._skip, self._href, self._label = [], [], [], [], 0, None, []
        self._item = None

    def _flush(self):
        text = _clean("".join(self._buf), BLOCK)
        if len(text) > 2 and len(self.blocks) < MAX_BLOCKS:
            self.blocks.append(text)
        if len(text) > 2 and self._item is not None and len(self._item["lines"]) < ITEM_LINES:
            self._item["lines"].append(text)
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self._skip += 1
        if tag in BLOCK_TAGS:
            self._flush()
        if tag == "li" and not self._skip:
            self._item = {"lines": [], "link": None}
        if tag == "a" and self._href is None:
            self._href, self._label = dict(attrs).get("href"), []

    def handle_endtag(self, tag):
        if tag in SKIP and self._skip:
            self._skip -= 1
        if tag in BLOCK_TAGS:
            self._flush()
        if tag == "li" and self._item is not None:
            if self._item["lines"] and len(self.items) < MAX_ITEMS:
                self.items.append(self._item)
            self._item = None
        if tag == "a" and self._href is not None:
            link = self._add_link(self._href, "".join(self._label))
            if link and self._item is not None and not self._item["link"]:
                self._item["link"] = link
            self._href = None

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)
            if self._href is not None:
                self._label.append(data)

    def _add_link(self, href: str, label: str):
        try:
            parts = urlsplit(href.strip()[:500])
            host = parts.hostname
        except ValueError:
            return None
        if parts.scheme != "https" or not host or parts.username or parts.password:
            return None
        url = href.strip()[:500]
        if len(self.links) >= MAX_LINKS and all(url != l["url"] for l in self.links):
            return None
        if not (url.isascii() and url.isprintable() and not {"\\", " "} & set(url) and re.fullmatch(r"[a-z0-9.-]+", host)):
            return None  # « https://evil.com\.bon.com » : le navigateur ne va pas où le domaine affiché le laisse croire
        for l in self.links:
            if l["url"] == url:
                return l
        self.links.append({"url": url, "host": host[:80], "label": _clean(label, LABEL) or host[:LABEL]})
        return self.links[-1]


def parse(raw: bytes) -> dict | None:
    msg = email.message_from_bytes(raw, policy=policy.default)
    m = SUBJECT.match(str(msg["Subject"] or ""))
    try:
        body = msg.get_body(("html",))
        page = _Page()
        page.feed(body.get_content() if body else "")
        page.close()
        year = msg["Date"].datetime.year
    except Exception:  # MIME, Date ou HTML hostile : le mail est ignoré
        return None
    if not m or not 1 <= int(m.group(2)) <= 53:
        return None
    page._flush()
    return {"kind": KINDS[m.group(1)], "week": int(m.group(2)), "year": year, "blocks": page.blocks, "links": page.links,
            "items": page.items}


def name(issue: dict) -> str:
    return f"veille-{issue['kind']}-{issue['year']}-{issue['week']:02}.eml"


def snapshot(root: Path | None = None) -> dict:
    root = Path(root) if root else veille_dir()
    found, base = [], root.resolve() if root.is_dir() else None
    for f in islice(root.glob("*.eml"), 500) if base else []:
        try:
            if not f.is_symlink() and f.resolve().parent == base:
                found.append((f.stat().st_mtime, f))
        except OSError:
            continue
    issues = []
    for _, f in sorted(found, reverse=True)[:MAX_FILES]:
        try:
            with f.open("rb") as h:
                raw = h.read(MAX_BYTES + 1)
        except OSError:
            continue
        issue = parse(raw) if len(raw) <= MAX_BYTES else None
        if issue:
            issues.append(issue)
    issues.sort(key=lambda i: (i["year"], i["week"], i["kind"]), reverse=True)
    return {"configured": base is not None, "issues": issues[:MAX_ISSUES]}
