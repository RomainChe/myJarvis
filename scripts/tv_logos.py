"""Télécharge les logos des applis de la maquette TV dans tv/logos/ (ignoré par Git : marques déposées, dépôt public).

Usage : python scripts/tv_logos.py
Source : Wikimedia Commons, HTTPS seulement. SVG affichés par <img> (aucun script exécuté). Un logo déjà présent est gardé.
"""
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / "tv" / "logos"
COMMONS = "https://commons.wikimedia.org/wiki/Special:FilePath/"
HOSTS = {"commons.wikimedia.org", "upload.wikimedia.org"}
MAX = 2_000_000
LOGOS = {
    "netflix": "Netflix_2015_logo.svg",
    "youtube": "YouTube_Logo_2017.svg",
    "primevideo": "Amazon_Prime_Video_logo.svg",
    "disneyplus": "Disney+_logo.svg",
    "spotify": "Spotify_logo_with_text.svg",
    "plex": "Plex_logo_2022.svg",
    "playstore": "Google_Play_2022_logo.svg",
    "twitch": "Twitch_logo.svg",
}


def fetch(name, commons_file):
    dest = DEST / f"{name}.svg"
    if dest.exists():
        return "déjà là"
    req = urllib.request.Request(COMMONS + urllib.parse.quote(commons_file),
                                 headers={"User-Agent": "jarvis-tv-maquette/1.0 (usage local)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if urllib.parse.urlsplit(r.geturl()).hostname not in HOSTS:
            raise ValueError("redirection hors de Wikimedia")
        data = r.read(MAX + 1)
    if len(data) > MAX or b"<svg" not in data[:4096]:
        raise ValueError("pas un SVG ou trop gros")
    dest.write_bytes(data)
    time.sleep(3)  # Wikimedia répond 429 aux rafales
    return "téléchargé"


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name, commons_file in LOGOS.items():
        try:
            print(f"{name} : {fetch(name, commons_file)}")
        except Exception as e:  # un logo manquant n'empêche pas les autres (la tuile affiche alors le nom)
            failed += 1
            print(f"{name} : échec ({e})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
