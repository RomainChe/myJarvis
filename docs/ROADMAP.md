# JARVIS — Roadmap

Règle : aucune phase ne démarre sans le feu vert de l'Expert Sécurité **et** du propriétaire.

## Phase 0 — Cadrage ✅
- [x] Inventaire du matériel (PC, smartphone, budget)
- [x] Architecture : `docs/ARCHITECTURE.md`
- [x] Marques et modèles : TV, clims, box (motorisation des volets à préciser avant la Phase 2)
- [x] Validation des 4 décisions (ARCHITECTURE §6)

## Phase 1 — Core + outils PC
Ordre imposé par l'Expert Sécurité : socle d'abord, outils ensuite.

1. Squelette : `pyproject.toml`, FastAPI sur `127.0.0.1`, CLI texte.
2. Interface `Tool` + registre + garde de permissions N0–N3 + confirmations.
3. Journal d'audit SQLite (ajout seul) et sa commande de consultation.
4. Routeur d'intentions (YAML + `difflib`) et mesure de latence.
5. Ollama : benchmark de 2 ou 3 modèles sur 30 commandes, choix, tool calling.
6. Les 15 premiers outils PC (tests : cas nominal, entrée invalide, permission refusée) :

| # | Outil | Niveau |
|---|---|---|
| 1 | `system_status` (CPU, RAM, GPU, disque) | N0 |
| 2 | `list_processes` | N0 |
| 3 | `search_files` (nom, dossier) | N0 |
| 4 | `open_app` | N1 |
| 5 | `close_app` (fermeture propre) | N1 |
| 6 | `set_volume` / `mute` | N1 |
| 7 | `media_control` (lecture, pause, suivant) | N1 |
| 8 | `screen_off` | N1 |
| 9 | `lock_session` | N1 |
| 10 | `clipboard_write` | N1 |
| 11 | `clipboard_read` | N2 (peut contenir des mots de passe) |
| 12 | `screenshot` | N2 (vie privée) |
| 13 | `move_file` / `delete_file` (vers la corbeille) | N2 |
| 14 | `kill_process` | N2 |
| 15 | `power` (veille, redémarrage, arrêt : coupe Jarvis et HA) | N2 |
| 16 | `run_script` (dossier en liste blanche) | N2 |

Sortie de phase : commande simple < 1 s, tous les tests verts, `docs/TOOLS.md` à jour, revue sécurité.

## Phase 2 — Domotique
1. Hyper-V + VM Home Assistant OS, réseau ponté, sauvegarde HA activée.
2. Intégrations des appareils (selon les marques), puis découverte automatique dans Jarvis.
3. Outils `home/*` : état (N0), TV/enceintes/volets (N1), chauffage coupé ou forcé (N2).
4. Scènes : « mode cinéma », « je pars », « bonne nuit ».
5. Les noms d'appareils sont traités comme des données (test d'injection dans un nom).

## Phase 3 — Applications (PWA)
1. Authentification par appareil (enrôlement par QR code, tokens révocables), puis Tailscale + `tailscale serve`.
2. Design system (tokens, thème clair/sombre), puis la PWA : chat, appareils, journal, réglages des niveaux.
3. Confirmations N2 dans l'app, N3 via WebAuthn (empreinte Android).
4. Notifications Web Push.

## Phase 4 — Voix
openWakeWord (« hey jarvis »), faster-whisper sur le GPU, Piper en français ; confirmation vocale pour le N2. Le N3 reste sur mobile.

## Phase 5 — Durcissement
Audit de sécurité complet, tests d'intrusion (injection de prompt, rejeu de token, accès hors Tailscale), sauvegardes automatiques (SQLite + HA), supervision, documentation finale. À reconsidérer : un serveur dédié (un Pi) pour la disponibilité 24 h/24.
