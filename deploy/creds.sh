#!/bin/sh
# Identifiants chiffrés de JARVIS sur le mini-PC (D14). Utilisation :
#   creds.sh import <dossier>   chiffre chaque fichier du dossier (python -m jarvis secret export) puis le supprime
#   creds.sh run <commande...>  déchiffre vers $CREDENTIALS_DIRECTORY (tmpfs, 0700), lance la commande, nettoie
# Pourquoi pas LoadCredentialEncrypted= : le gestionnaire --user ne peut pas lire la clé hôte (essai Debian 13).
set -eu
store="${JARVIS_CREDS:-$HOME/.config/jarvis/creds}"
case "${1:-}" in
import)
    src="${2:?dossier requis (python -m jarvis secret export)}"
    mkdir -p "$store" && chmod 700 "$store"
    for f in "$src"/*; do
        [ -f "$f" ] || continue
        n=$(basename "$f")
        if systemd-creds encrypt --user --name="$n" "$f" "$store/$n.cred"; then
            rm -f "$f"; echo "chiffré : $n"
        else
            echo "échec : $n (fichier en clair laissé, à supprimer)" >&2; exit 1
        fi
    done
    rmdir "$src" 2>/dev/null || true ;;
run)
    shift
    run="${XDG_RUNTIME_DIR:-/tmp}"
    # Dossiers laissés par un run tué (SIGKILL : pas de trap) : le PID du nom n'existe plus.
    for o in "$run"/jarvis-creds.*.*; do
        [ -d "$o" ] || continue
        p=${o#"$run"/jarvis-creds.}; p=${p%%.*}
        kill -0 "$p" 2>/dev/null || rm -rf "$o"
    done
    d=$(mktemp -d "$run/jarvis-creds.$$.XXXXXX")  # mktemp : 0700
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
