"""Prépare le processus pour les DLL CUDA installées par pip (nvidia-cublas, cudnn, nvrtc).

Seuls les site-packages du Python courant (venv inclus) sont lus, jamais le site utilisateur (écriture sans droits
admin). Les dossiers sont ajoutés en FIN de PATH (ils ne masquent aucune DLL système) et via `os.add_dll_directory`.
Limite : les sous-processus lancés par les outils héritent de ce PATH (voir docs/DECISIONS.md).
À appeler avant d'importer faster_whisper.
"""
import os
import sysconfig
from pathlib import Path

PACKAGES = ("cublas", "cudnn", "cuda_nvrtc")


def prepare_cuda_path() -> list[str]:
    """Complète le PATH du processus (seulement) ; renvoie les dossiers ajoutés."""
    roots = {Path(sysconfig.get_path(k)) for k in ("purelib", "platlib")}
    current = os.environ.get("PATH", "").split(os.pathsep)
    found = []
    for root in sorted(roots):
        for pkg in PACKAGES:
            d = str(root / "nvidia" / pkg / "bin")
            if os.path.isdir(d) and d not in current and d not in found:
                found.append(d)
    if found:
        os.environ["PATH"] = os.pathsep.join(current + found)
        for d in found:
            if hasattr(os, "add_dll_directory"):  # Windows seulement
                os.add_dll_directory(d)
    return found
