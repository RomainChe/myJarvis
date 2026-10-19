"""Inventaire des branches et worktrees pour l'agent garde-branches (phases A et C), en JSON, sans rien modifier.

`python scripts/etat_branches.py [dépôt]` : ne fait pas de fetch, l'agent lance `git fetch --prune` avant.
États d'une branche : bloquee, neuve, fusionnee, squash, en_retard, non_poussee, dormante.
"""
import json
import os
import subprocess
import sys
import time

DORMANTE_JOURS = 14


def git(cwd: str, *args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout.strip()


def out(cwd: str, *args: str) -> str:
    return git(cwd, *args)[1]


def compte(cwd: str, rng: str) -> tuple[int, int]:
    """(commits seulement à gauche, seulement à droite) de `gauche...droite`."""
    left, right = out(cwd, "rev-list", "--left-right", "--count", rng).split()
    return int(left), int(right)


def worktrees(root: str) -> list[dict]:
    found, cur = [], None
    for line in out(root, "worktree", "list", "--porcelain").splitlines():
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur = {"chemin": val, "branche": None, "detache": False, "verrouille": False, "prunable": False}
            found.append(cur)
        elif key == "branch":
            cur["branche"] = val.removeprefix("refs/heads/")
        elif key in ("detached", "locked", "prunable"):
            cur[{"detached": "detache", "locked": "verrouille", "prunable": "prunable"}[key]] = True
    return found


def operation_en_cours(path: str) -> str | None:
    for marker in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if os.path.exists(os.path.join(path, out(path, "rev-parse", "--git-path", marker))):
            return marker
    return None


def conflits(root: str, a: str, b: str) -> list[str]:
    """Fichiers en conflit si on fusionnait a et b (vide si le merge passe)."""
    code, text = git(root, "merge-tree", "--write-tree", "--name-only", a, b)
    if code != 1:
        return []
    files = []
    for line in text.splitlines()[1:]:
        if not line:
            break
        files.append(line)
    return files


def inventaire(root: str) -> dict:
    wts = worktrees(root)
    principal = wts[0]["chemin"]
    for wt in wts:
        exists = os.path.isdir(wt["chemin"])
        wt["propre"] = exists and not out(wt["chemin"], "status", "--porcelain")
        wt["operation"] = operation_en_cours(wt["chemin"]) if exists else None
        wt["hors_convention"] = wt["chemin"] != principal and "/.claude/worktrees/" not in wt["chemin"].replace("\\", "/")
    par_branche = {wt["branche"]: wt for wt in wts if wt["branche"]}
    has_origin_main = git(root, "rev-parse", "-q", "--verify", "refs/remotes/origin/main")[0] == 0

    branches = []
    refs = out(root, "for-each-ref", "refs/heads", "--format=%(refname:short)\t%(upstream:short)\t%(committerdate:unix)")
    for line in refs.splitlines():
        name, upstream, date = line.split("\t")
        if name == "main":
            continue
        retard, avance = compte(root, f"main...{name}")
        wt = par_branche.get(name)
        b = {"nom": name, "avance": avance, "retard": retard, "worktree": wt["chemin"] if wt else None,
             "propre": wt["propre"] if wt else None, "jours": int((time.time() - int(date)) // 86400),
             "upstream": upstream or None, "etats": []}
        if upstream and git(root, "rev-parse", "-q", "--verify", upstream)[0] == 0:
            b["vs_upstream"] = dict(zip(("avance", "retard"), compte(root, f"{name}...{upstream}")))
        if wt and (wt["operation"] or wt["detache"]):  # verrouillé est normal : Claude Code verrouille ses worktrees
            b["etats"].append("bloquee")
        if avance == 0:
            # aucun commit jamais fait sur la branche (reflog) : une session qui démarre, pas un travail fini
            reflog = out(root, "reflog", "show", "--format=%gs", f"refs/heads/{name}").splitlines()
            b["etats"].append("fusionnee" if any(e.startswith("commit") for e in reflog) else "neuve")
        else:
            if "+" not in out(root, "cherry", "main", name).split():
                b["etats"].append("squash")
            if retard:
                b["etats"].append("en_retard")
                b["conflit_main"] = conflits(root, "main", name)
            if not upstream or b.get("vs_upstream", {}).get("avance"):
                b["etats"].append("non_poussee")
            if b["jours"] > DORMANTE_JOURS:
                b["etats"].append("dormante")
        branches.append(b)

    locales = {b["nom"] for b in branches} | {"main"}
    orphelines = []
    for name in out(root, "for-each-ref", "refs/remotes/origin", "--format=%(refname:short)").splitlines():
        short = name.removeprefix("origin/")
        if short not in locales and short != "HEAD" and name != "origin":
            orphelines.append({"nom": short, "fusionnee": compte(root, f"main...{name}")[1] == 0})

    actives = [b["nom"] for b in branches if b["worktree"] and b["avance"]]
    contamination, paires = [], []
    for i, a in enumerate(actives):
        for b in actives[i + 1:]:
            if set(out(root, "rev-list", f"main..{a}").split()) & set(out(root, "rev-list", f"main..{b}").split()):
                contamination.append([a, b])
            if files := conflits(root, a, b):
                paires.append({"a": a, "b": b, "fichiers": files})

    return {
        "principal": {"chemin": principal, "branche": wts[0]["branche"], "propre": wts[0]["propre"],
                      "vs_origin": dict(zip(("avance", "retard"), compte(root, "main...origin/main"))) if has_origin_main else None},
        "worktrees": wts, "branches": branches, "orphelines": orphelines,
        "contamination": contamination, "conflits": paires,
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(inventaire(sys.argv[1] if len(sys.argv) > 1 else os.getcwd()), ensure_ascii=False, indent=1))
