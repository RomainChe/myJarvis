"""Outil Claude Code (Phase 6 étape 9) : « code : ajoute X » fait modifier le code de JARVIS par `claude -p`.

N1 par décision du propriétaire (CLAUDE.md §4), avec deux garde-fous :
(a) `owner_only` : invisible du LLM ; `permissions.execute` ne l'accepte que des sources `cli` et `pwa:<id>` (ni LLM, ni voix,
    ni automatisme). Seul le routeur le déclenche, avec les mots exacts du propriétaire. Claude tourne en `--restricted`,
    sans MCP, sans web et avec le seul Bash `python -m unittest`, dans un worktree hors de `~/.jarvis`.
(b) branche `jarvis/claude-<horodatage>` ; fusion `--ff-only` dans `main` seulement si : dépôt propre, aucun chemin protégé
    touché, aucun test existant modifié, aucune donnée personnelle ajoutée, suite verte (« OK » exact, pas moins de tests ni plus
    de tests sautés qu'avant), imports du serveur sains. Sinon la branche est gardée (« revue requise »). Puis redémarrage.
Un seul travail à la fois ; le compte rendu va dans `~/.jarvis/claude_last.json` (`claude_code_status`).
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from jarvis.core.audit import Audit
from jarvis.core.tools import Level, tool

REPO = Path(__file__).parents[2]
HOME = Path.home() / ".jarvis"
STATE = HOME / "claude_last.json"
WORK = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "jarvis-claude-work"  # hors de ~/.jarvis (mails, finances)
CLAUDE_TIMEOUT_S, TESTS_TIMEOUT_S, GIT_TIMEOUT_S = 1800, 900, 120
SUMMARY_MAX, DIFF_MAX = 1500, 1500
PROMPT = ("Demande du propriétaire de JARVIS :\n{request}\n\n"
          "Tu travailles sur une branche dédiée. Écris les tests de toute nouvelle logique dans de nouveaux fichiers "
          "tests/test_*.py (ne modifie pas les tests existants) et vérifie qu'ils passent avec "
          "`python -m unittest discover -s tests`. Ne fais ni commit ni push : JARVIS fusionne lui-même si les tests "
          "passent. Termine par un résumé de trois lignes au plus, en français.")
CLAUDE_ARGS = ["-p", "--restricted", "--strict-mcp-config", "--tools", "Read,Edit,Write,Glob,Grep,Bash",
               "--permission-mode", "acceptEdits", "--allowedTools", "Bash(python -m unittest:*)"]
ENV = {"ENABLE_CLAUDEAI_MCP_SERVERS": "false",  # ni connecteurs claude.ai, ni push possible depuis le code lancé
       "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "remote.origin.pushurl", "GIT_CONFIG_VALUE_0": "disabled://",
       "GIT_CONFIG_KEY_1": "credential.helper", "GIT_CONFIG_VALUE_1": "", "GIT_TERMINAL_PROMPT": "0"}
# Sécurité de JARVIS et de Claude : un changement ici exige une revue humaine, jamais une fusion automatique.
PROTECTED = ("jarvis/__main__.py", "jarvis/server.py", "jarvis/intents.json", "jarvis/tools/dev.py", "jarvis/core/audit.py",
             "jarvis/core/chat.py", "jarvis/core/devices.py", "jarvis/core/levels.py", "jarvis/core/llm.py",
             "jarvis/core/permissions.py", "jarvis/core/router.py", "jarvis/core/secrets.py", "jarvis/core/tools.py",
             "jarvis/core/voice.py", "jarvis/core/webauthn.py", "jarvis/core/mic.py", "jarvis/tools/home/scenes.py", "jarvis/web/app.js",
             "jarvis/web/index.html", "jarvis/web/sw.js", "tests/__init__.py", ".claude/", ".github/", "CLAUDE.md", ".gitignore",
             "pyproject.toml")
PERSONAL = re.compile(r"\b(?!127\.0\.0\.1\b|0\.0\.0\.0\b)(?:\d{1,3}\.){3}\d{1,3}\b|[\w.+-]+@[\w-]+\.[\w.]+"
                      r"|(?i:password|passwd|secret|token|api_key)\s*[:=]\s*['\"][^'\"]{8,}")
_busy = threading.Lock()


class Review(Exception):
    """La branche est gardée, rien n'est fusionné : le propriétaire relit."""


def _run(cmd: list[str], cwd: Path, timeout: int, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env={**os.environ, **ENV}, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _git(*args: str, cwd: Path | None = None) -> str:
    out = _run(["git", *args], cwd or REPO, GIT_TIMEOUT_S)
    if out.returncode:
        raise RuntimeError(f"git {args[0]} : {out.stderr.strip()[:200]}")
    return out.stdout.strip()


# Verdict signé d'un jeton lu sur stdin : un test qui écrit « Ran 9999 tests / OK » puis quitte ne le connaît pas.
RUNNER = ("import sys, unittest\n"
          "def main(nonce):\n"
          "    r = unittest.TextTestRunner(stream=sys.stderr).run(unittest.defaultTestLoader.discover('tests'))\n"
          "    print(nonce, r.testsRun, len(r.skipped), int(r.wasSuccessful()))\n"
          "main(sys.stdin.readline().strip())\n")
# Fumée + carte des outils : le serveur s'importe, et niveaux/drapeaux comparés entre main et la branche.
SMOKE = [sys.executable, "-c", "import json, jarvis.__main__, jarvis.server\n"
         "from jarvis.core.tools import REGISTRY\n"
         "print(json.dumps({n: [int(t.level), t.private, t.external, t.taint_blocked, sorted(t.hidden), t.owner_only]"
         " for n, t in REGISTRY.items()}))"]
FLAGS = ("private", "external", "taint_blocked", "hidden", "owner_only")


def _registry(cwd: Path) -> dict | None:
    out = _run(SMOKE, cwd, GIT_TIMEOUT_S)
    try:
        tools = json.loads((out.stdout.strip().splitlines() or [""])[-1])
    except ValueError:
        return None
    return tools if out.returncode == 0 and isinstance(tools, dict) else None


def _weakened(old: dict, new: dict) -> list[str]:
    """Outils existants disparus, abaissés ou aux drapeaux affaiblis (§4 : réglage de sécurité, jamais en fusion auto)."""
    found = []
    for name, (level, *flags) in old.items():
        if name not in new:
            found.append(f"{name} retiré")
            continue
        if new[name][0] < level:
            found.append(f"{name} abaissé")
        found += [f"{name}.{f} affaibli" for f, a, b in zip(FLAGS, flags, new[name][1:])
                  if (set(a) - set(b) if f == "hidden" else a and not b)]
    return found


def _tests(cwd: Path) -> tuple[int, int] | None:
    """(lancés, sautés) si la suite est verte, sinon None."""
    nonce = secrets.token_hex(16)
    out = _run([sys.executable, "-c", RUNNER], cwd, TESTS_TIMEOUT_S, stdin=nonce + "\n")
    last = re.fullmatch(rf"{nonce} (\d+) (\d+) 1", (out.stdout.strip().splitlines() or [""])[-1])
    return (int(last.group(1)), int(last.group(2))) if out.returncode == 0 and last else None


def _check_diff(base: str, tree: Path) -> None:
    """Revue requise si le diff touche la sécurité, un test existant, ou ajoute une donnée personnelle (dépôt public)."""
    for line in _git("-c", "core.quotePath=false", "diff", "--name-status", "--no-renames", base, "HEAD", cwd=tree).splitlines():
        status, path = line.split("\t", 1)
        if path.startswith(PROTECTED):
            raise Review(f"chemin protégé modifié : {path}")
        if path.startswith("tests/") and (status != "A" or not re.fullmatch(r"tests/test_\w+\.py", path)):
            raise Review(f"test existant modifié ou fichier hors tests/test_*.py : {path}")
    added = [l[1:] for l in _git("diff", "-U0", base, "HEAD", cwd=tree).splitlines() if l.startswith("+") and not l.startswith("+++")]
    if any(PERSONAL.search(l) for l in added):
        raise Review("possible donnée personnelle ou secret dans le code ajouté")


def _serving() -> bool:
    return sys.argv[1:] == ["serve"]


def _restart() -> None:
    # ponytail: le nouveau serveur se lie au port après ~1 s d'imports, le temps que celui-ci le libère en sortant ;
    # passer par la tâche planifiée « JARVIS - core » (INSTALL §7.2) quand elle sera en place.
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([sys.executable, "-m", "jarvis", "serve"], cwd=REPO, creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os._exit(0)


def _clean() -> bool:
    return not _git("status", "--porcelain", "--untracked-files=no")


def work(request: str, claude: str, audit: Audit) -> dict:
    """Branche, Claude, contrôles, fusion : le compte rendu (statut, résumé, diffstat). Ne redémarre pas."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    branch, tree = f"jarvis/claude-{stamp}", WORK / stamp
    report = {"at": stamp, "request": request, "branch": branch, "status": "erreur", "summary": "", "diffstat": ""}
    if _git("rev-parse", "--abbrev-ref", "HEAD") != "main" or not _clean():
        report["summary"] = "le dépôt n'est pas sur main ou a des changements non commités : rien n'a été lancé"
        return report
    base = _git("rev-parse", "HEAD")
    _git("worktree", "add", "-b", branch, str(tree), base)
    merged = False
    try:
        before = _tests(tree)
        tools = _registry(tree)
        if before is None or before[0] == 0 or not tools:
            report["status"] = "main n'est pas sain (tests rouges ou serveur qui ne s'importe pas) : rien n'a été lancé"
            return report
        out = _run([claude, *CLAUDE_ARGS], tree, CLAUDE_TIMEOUT_S, stdin=PROMPT.format(request=request))
        report["summary"] = (out.stdout.strip() or out.stderr.strip())[-SUMMARY_MAX:]
        if out.returncode:
            report["status"] = "Claude a échoué"
            return report
        _git("add", "-A", cwd=tree)
        if not _git("status", "--porcelain", cwd=tree):
            report["status"] = "aucun changement"
            return report
        _git("commit", "-m", f"Jarvis (claude_code) {stamp}", cwd=tree)  # la demande reste locale (claude_last.json)
        report["diffstat"] = _git("diff", "--stat", base, "HEAD", cwd=tree)[-DIFF_MAX:]
        try:
            _check_diff(base, tree)
            after = _tests(tree)
            if after is None or after[0] < before[0] or after[1] > before[1]:
                raise Review(f"tests en échec ou en baisse (avant : {before[0]} lancés, {before[1]} sautés)")
            new_tools = _registry(tree)
            if new_tools is None:
                raise Review("le serveur ne s'importe plus")
            if weak := _weakened(tools, new_tools):
                raise Review("sécurité des outils affaiblie : " + ", ".join(weak[:5]))
            report["new_tools"] = sorted(new_tools.keys() - tools.keys())
            if not _clean() or _git("rev-parse", "HEAD") != base:
                raise Review("main a changé pendant le travail")
        except Review as e:
            report["status"] = f"revue requise : {e} ; branche {branch} gardée, rien fusionné"
            return report
        commit = _git("rev-parse", "HEAD", cwd=tree)
        audit.log("claude_code", "claude_code_merge", {"branch": branch, "commit": commit, "new_tools": report["new_tools"]}, int(Level.N1), "auto", "en cours")
        _git("merge", "--ff-only", branch)
        merged = True
        report["status"] = f"fusionné dans main ({after[0]} tests verts)"
        return report
    finally:
        _git("worktree", "remove", "--force", str(tree))
        if merged:
            _git("branch", "-d", branch)


def _job(request: str, claude: str) -> dict:
    try:
        audit = Audit(os.environ.get("JARVIS_DB") or str(HOME / "jarvis.db"))  # même base que jarvis.__main__.DB_PATH
        try:
            report = work(request, claude, audit)
        except Exception as e:  # git ou Claude indisponible, délai dépassé
            report = {"at": datetime.now().strftime("%Y%m%d-%H%M%S"), "request": request, "branch": "", "summary": "",
                      "diffstat": "", "status": f"erreur : {type(e).__name__}: {str(e)[:200]}"}
        HOME.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        audit.log("claude_code", "claude_code_merge", {"branch": report["branch"]}, int(Level.N1), "auto", report["status"])
        if report["status"].startswith("fusionné") and _serving():
            _restart()
        return report
    finally:
        _busy.release()


@tool("claude_code", "Fait modifier le code de JARVIS par Claude Code (branche, tests, fusion si verts, redémarrage). "
                     "Demande directe du propriétaire seulement.", Level.N1, owner_only=True, request=str)
def claude_code(request: str) -> str:
    request = request.strip()
    if not 5 <= len(request) <= 1000:
        raise ValueError("demande vide ou trop longue")
    claude = shutil.which("claude")
    if claude is None:
        raise ValueError("Claude Code introuvable sur ce PC")
    if not _busy.acquire(blocking=False):
        raise ValueError("un travail Claude Code est déjà en cours")
    if not _serving():  # CLI : un thread démon mourrait avec le processus et laisserait le worktree en plan
        return f"Terminé : {_job(request, claude)['status']}"
    try:
        threading.Thread(target=_job, args=(request, claude), daemon=True).start()
    except BaseException:
        _busy.release()
        raise
    return "C'est lancé. Demande-moi « où en est le code » pour le compte rendu."


@tool("claude_code_status", "Compte rendu du dernier travail Claude Code : statut, résumé, fichiers modifiés.", Level.N0,
      external=True)
def claude_code_status() -> dict:
    if _busy.locked():
        return {"status": "en cours"}
    try:
        report = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "aucun travail"}
    return {k: report.get(k, "") for k in ("at", "status", "summary", "diffstat", "new_tools")}
