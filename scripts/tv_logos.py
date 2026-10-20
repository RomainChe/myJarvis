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


# Sites sans logo sur Commons : logo publié par le site lui-même (nom de fichier local, URL, hôte attendu).
SITE_LOGOS = {
    "openflix": ("openflix.svg", "https://openflix.pro/opfx-logo-full.svg", "openflix.pro"),
    "bowd": ("bowd.png", "https://bowdtv.com/brand/icon-192.png", "bowdtv.com"),
}
PNG = b"\x89PNG\r\n\x1a\n"


def fetch(filename, url, hosts):
    dest = DEST / filename
    if dest.exists():
        return "déjà là"
    req = urllib.request.Request(url, headers={"User-Agent": "jarvis-tv-maquette/1.0 (usage local)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if urllib.parse.urlsplit(r.geturl()).hostname not in hosts:
            raise ValueError("redirection hors de l'hôte attendu")
        data = r.read(MAX + 1)
    ok = (b"<svg" in data[:4096]) if filename.endswith(".svg") else data.startswith(PNG)
    if len(data) > MAX or not ok:
        raise ValueError("format inattendu ou trop gros")
    dest.write_bytes(data)
    time.sleep(3)  # Wikimedia répond 429 aux rafales
    return "téléchargé"


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    failed = 0
    jobs = [(n, f"{n}.svg", COMMONS + urllib.parse.quote(f), HOSTS) for n, f in LOGOS.items()]
    jobs += [(n, f, url, {host}) for n, (f, url, host) in SITE_LOGOS.items()]
    for name, filename, url, hosts in jobs:
        try:
            print(f"{name} : {fetch(filename, url, hosts)}")
        except Exception as e:  # un logo manquant n'empêche pas les autres (la tuile affiche alors le nom)
            failed += 1
            print(f"{name} : échec ({e})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
