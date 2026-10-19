"""Garde des branches, hook PreToolUse sans modèle : bloque un `git commit`, `merge` ou `push` qui mélangerait
deux sessions parallèles (une branche par worktree). Le rapport complet reste l'agent `garde-branches`, à la demande.

Bloque (code 2, raison sur stderr) seulement si la commande :
- commite sur une branche qui contient déjà des commits propres à une branche active d'un autre worktree ;
- fusionne dans une branche autre que `main` des commits propres à une branche active d'un autre worktree ;
- pousse vers une branche (hors `main`) extraite dans un autre worktree.
"""
import json
import os
import re
import shlex
import subprocess
import sys

VALUE_OPTS = {"-m", "-F", "-s", "-X", "--strategy", "--strategy-option", "--file", "-c", "--cleanup"}


def git(cwd: str, *args: str) -> str | None:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip() if r.returncode == 0 else None


def revs(cwd: str, rng: str) -> set[str]:
    return set((git(cwd, "rev-list", rng) or "").split())


def norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def others(cwd: str, own: str) -> dict[str, str]:
    """Branches actives des autres worktrees, hors `main` et hors la branche courante : {branche: chemin}."""
    here = norm(git(cwd, "rev-parse", "--show-toplevel") or cwd)
    found, path = {}, None
    for line in (git(cwd, "worktree", "list", "--porcelain") or "").splitlines():
        if line.startswith("worktree "):
            path = line[9:]
        elif line.startswith("branch refs/heads/") and path and norm(path) != here:
            name = line[18:]
            if name not in ("main", own):
                found[name] = path
    return found


def segments(command: str):
    """(cwd relatif, sous-commande, arguments) de chaque `git commit|merge|push` d'une commande composée."""
    for part in re.split(r"&&|\|\||[;|\n]", command):
        try:
            words = shlex.split(part, posix=True)
        except ValueError:
            continue
        while words and words[0] != "git":
            words.pop(0)
        if not words:
            continue
        words, where = words[1:], None
        while words[:1] == ["-C"] and len(words) > 1:
            where, words = words[1], words[2:]
        if words and words[0] in ("commit", "merge", "push"):
            yield where, words[0], words[1:]


def positional(args: list[str]) -> list[str]:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in VALUE_OPTS:
            skip = True
        elif not a.startswith("-"):
            out.append(a)
    return out


def check(command: str, cwd: str) -> str | None:
    """Raison du blocage, ou None si la commande est sans risque."""
    for where, sub, args in segments(command):
        here = os.path.join(cwd, where) if where else cwd
        own = git(here, "branch", "--show-current") or ""
        for branch, path in others(here, own).items():
            mine = revs(here, f"main..{branch}")
            if sub == "commit" and mine & revs(here, "main..HEAD"):
                return f"la branche {own or 'HEAD'} contient déjà des commits de {branch} (worktree {path})."
            if sub == "merge" and own != "main":
                for target in positional(args):
                    if mine & revs(here, f"HEAD..{target}"):
                        return f"« git merge {target} » ferait entrer dans {own} des commits de {branch} (worktree {path})."
            if sub == "push":
                if {"--delete", "-d"} & set(args):
                    continue  # supprimer une branche distante ne mélange aucun travail
                for spec in positional(args)[1:]:
                    if spec.startswith(":"):
                        continue
                    if spec.lstrip("+").split(":")[-1].removeprefix("refs/heads/") == branch:
                        return f"{branch} est extraite dans un autre worktree ({path}) : c'est à sa session de la pousser."
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
        command = event.get("tool_input", {}).get("command", "")
        reason = check(command, event.get("cwd") or os.getcwd()) if re.search(r"\bgit\b", command) else None
    except Exception:  # noqa: BLE001 (garde d'hygiène, pas de sécurité : une panne du garde ne bloque pas le travail)
        return 0
    if reason:
        sys.stderr.reconfigure(encoding="utf-8")  # Windows : cp1252 par défaut, accents illisibles pour Claude Code
        print(f"Garde des branches : {reason} Lance l'agent garde-branches pour le rapport complet.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
