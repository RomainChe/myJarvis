"""Mesure reproductible (stdlib seule) du démarrage et du Core de Jarvis.

    python bench/measure_startup.py [essais]

Affiche des médianes en ms. N'écrit que dans un dossier temporaire.
"""
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def median_ms(fn, runs):
    samples = []
    for _ in range(runs):
        t = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t) * 1000)
    return statistics.median(samples)


def wall(args, env):
    return lambda: subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True, check=False)


def top_imports(env, n=8):
    """Imports les plus lents (temps cumulé) d'après -X importtime."""
    err = subprocess.run([sys.executable, "-X", "importtime", "-m", "jarvis", "audit", "1"],
                         cwd=ROOT, env=env, capture_output=True, text=True).stderr
    rows = re.findall(r"import time:\s+\d+ \|\s+(\d+) \|\s+(.+)", err)
    return sorted(((int(us), name.rstrip()) for us, name in rows), reverse=True)[:n]


def main(runs: int) -> None:
    tmp = tempfile.mkdtemp(prefix="jarvis-bench-")
    env = dict(os.environ, JARVIS_DB=os.path.join(tmp, "bench.db"))

    print(f"Python {sys.version.split()[0]}, {runs} essais, médianes en ms\n")
    print("== Processus complets ==")
    print(f"python -c pass              {median_ms(wall(['-c', 'pass'], env), runs):7.1f}")
    print(f"python -m jarvis (aide)     {median_ms(wall(['-m', 'jarvis'], env), runs):7.1f}")
    print(f"python -m jarvis audit 1    {median_ms(wall(['-m', 'jarvis', 'audit', '1'], env), runs):7.1f}")

    print("\n== Imports les plus lents (cumulé, ms) ==")
    for us, name in top_imports(env):
        print(f"{name:28s}{us / 1000:7.1f}")

    from jarvis.__main__ import parse_args
    from jarvis.core.audit import Audit
    from jarvis.core.permissions import execute
    from jarvis.core.tools import REGISTRY, Level, tool

    if "bench.noop" not in REGISTRY:
        tool("bench.noop", "outil vide", Level.N1, x=int)(lambda x: x)
    noop = REGISTRY["bench.noop"]

    def yes(_tool, _args):
        return True

    n = runs * 20
    disk = Audit(os.path.join(tmp, "disk.db"))
    mem = Audit(":memory:")

    def log(a):
        return lambda: a.log("bench", "x", {"x": 1}, 1, "auto", 1)

    print(f"\n== Fonctions du Core ({n} appels) ==")
    print(f"parse_args(3 paires)        {median_ms(lambda: parse_args(['a=1', 'b=true', 'c=txt']), n):7.3f}")
    print(f"Tool.check_args             {median_ms(lambda: noop.check_args({'x': 1}), n):7.3f}")
    print(f"Audit() ouverture + schéma  {median_ms(lambda: Audit(os.path.join(tmp, 'open.db')).db.close(), runs):7.3f}")
    print(f"Audit.log (disque, défaut)  {median_ms(log(disk), n):7.3f}")
    print(f"Audit.log (mémoire)         {median_ms(log(mem), n):7.3f}")
    disk.db.execute("PRAGMA journal_mode=WAL")
    disk.db.execute("PRAGMA synchronous=NORMAL")
    print(f"Audit.log (disque, WAL)     {median_ms(log(disk), n):7.3f}")
    print(f"execute N1 (disque, WAL)    "
          f"{median_ms(lambda: execute('bench.noop', {'x': 1}, source='bench', audit=disk, confirm=yes, strong_auth=yes), n):7.3f}")
    print(f"Audit.last(20)              {median_ms(lambda: disk.last(20), n):7.3f}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 15)
