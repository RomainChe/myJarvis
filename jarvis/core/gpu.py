"""Prépare le PATH du processus pour les DLL CUDA installées par pip (nvidia-cublas, cudnn, nvrtc).

`os.add_dll_directory` ne suffit pas pour ctranslate2 : le PATH, oui (mesuré : Whisper GPU 0,12 s/phrase).
Aucun effet si les dossiers sont absents. À appeler avant d'importer faster_whisper.
"""
import os
import site
from pathlib import Path

PACKAGES = ("cublas", "cudnn", "cuda_nvrtc")


def prepare_cuda_path() -> list[str]:
    """Préfixe le PATH du processus (seulement) ; renvoie les dossiers ajoutés."""
    roots = [Path(p) for p in site.getsitepackages() + [site.getusersitepackages()]]
    current = os.environ.get("PATH", "").split(os.pathsep)
    found = []
    for root in roots:
        for pkg in PACKAGES:
            d = str(root / "nvidia" / pkg / "bin")
            if os.path.isdir(d) and d not in current and d not in found:
                found.append(d)
    if found:
        os.environ["PATH"] = os.pathsep.join(found + current)
    return found
