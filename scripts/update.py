"""Mise à jour automatique du Core sous Windows (équivalent de deploy/systemd/jarvis-update.service).

`python -m scripts.update` : `git pull --ff-only` sur `main`, puis redémarre le Core si le commit courant n'est pas celui
déjà déployé (mémorisé dans ~/.jarvis/deployed-head, donc une fusion locale redémarre aussi). Au premier passage, le commit
est seulement mémorisé. Hors `main` ou pull impossible (conflit, hors ligne) : rien ne bouge."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MARK = Path.home() / ".jarvis" / "deployed-head"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
    if r.returncode:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def main(restart=None) -> bool:
    """True si le Core a été redémarré."""
    if git("branch", "--show-current") != "main":
        return False
    try:
        git("pull", "--ff-only", "-q")
    except RuntimeError:
        pass  # hors ligne ou arbre en conflit : on garde le code actuel
    head = git("rev-parse", "HEAD")
    seen = MARK.read_text().strip() if MARK.exists() else None
    if head == seen:
        return False
    MARK.parent.mkdir(exist_ok=True)
    MARK.write_text(head)
    if seen is None:
        return False
    if restart is None:
        from jarvis.core.doctor import restart_task as restart
    restart()
    return True


if __name__ == "__main__":
    main()
