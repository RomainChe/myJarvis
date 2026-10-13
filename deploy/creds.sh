#!/bin/sh
# Identifiants chiffrés de JARVIS sur le mini-PC (D14). Utilisation :
#   creds.sh import <dossier>   chiffre chaque fichier du dossier (python -m jarvis secret export) puis le supprime
#   creds.sh run <commande...>  déchiffre vers $CREDENTIALS_DIRECTORY (tmpfs, 0700), lance la commande, nettoie
# Pourquoi pas LoadCredentialEncrypted= : le gestionnaire --user ne peut pas lire la clé hôte (essai Debian 13).
set -eu
store="${JARVIS_CREDS:-$HOME/.config/jarvis/creds}"
case "${1:-}" in
import)
    src="${2:?dossier d'export requis}"
    mkdir -p "$store" && chmod 700 "$store"
    for f in "$src"/*; do
        [ -f "$f" ] || continue
        n=$(basename "$f")
        systemd-creds encrypt --user --name="$n" "$f" "$store/$n.cred" && rm -f "$f"
        echo "chiffré : $n"
    done
    rmdir "$src" 2>/dev/null || true ;;
run)
    shift
    d=$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/jarvis-creds.XXXXXX")  # mktemp : 0700
    trap 'rm -rf "$d"' EXIT
    trap 'exit 143' TERM INT
    for f in "$store"/*.cred; do
        [ -e "$f" ] || continue
        n=$(basename "$f" .cred)
        systemd-creds decrypt --user --name="$n" "$f" "$d/$n"
    done
    CREDENTIALS_DIRECTORY="$d" "$@" ;;
*) echo "usage : creds.sh import <dossier> | run <commande...>" >&2; exit 2 ;;
esac
