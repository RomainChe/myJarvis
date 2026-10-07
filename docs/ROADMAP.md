# JARVIS — Roadmap

Règle : aucune phase ne démarre sans le feu vert de l'Expert Sécurité **et** du propriétaire.

## État actuel (à lire en reprise de session)
- Phase en cours : **Phase 1**, étapes 1 à 3 faites ; Ollama 0.40.0 (127.0.0.1:11434) ; qwen3:8b, ministral-3:8b et qwen3:14b téléchargés le 2026-10-07.
- F1–F12 (docs/SECURITY_REVIEW_PHASE_1.md) et BUG-01..06 (docs/QA_REPORT_PHASE_1.md) corrigés le 2026-10-07, puis la contre-revue (C1–C7, C2bis). Veto N2/N3 levé pour le Core ; écart C1 (pas de HMAC) accepté par le propriétaire (ARCHITECTURE §6.5).
- Branche `routeur` (routeur + 3 outils N0 sur le nouveau Core, CLI en phrase) : QA validé avec réserve (QA-R5 : `list_processes` > 500 ms sous charge, bloque la sortie de Phase 1 ; QA-R6, R7 mineurs). Sécurité : feu vert sous conditions, fusion bloquée tant que les constats 1–3 ne sont pas corrigés (racine autorisée pour `search_files`, jonctions non suivies, `folder` du routeur en liste blanche) ; constats 4–6 et 9 dans la même branche si possible, constat 7 (résultats d'outils = données) bloquant pour l'étape 5.
- Benchmark fait (docs/MODEL_BENCHMARK.md) : qwen3:14b choisi.
- Prochaine action : corriger les constats Sécurité de `routeur`, fusionner, puis brancher le LLM (étape 5).
- Décidé le 2026-10-07 : tutoiement ; clims option A (MELCloud) ; 1 volet ; réponses domotique dans docs/DOMOTIQUE_PLAN.md §7 ; Jarvis peut lire `.env` ; LLM = qwen3:14b sans réflexion, veille automatique pendant un jeu, déchargement après 15–30 min d'inactivité (ARCHITECTURE §6.6).
- Décisions propriétaire en attente : destination des sauvegardes, reste de DOMOTIQUE_PLAN §7.
- Droits : commit, push et merge dans `main` autorisés sans confirmation (hooks de blocage retirés le 2026-10-07) ; `rebase` et `reset` autorisés en local, push forcé interdit.

## Phase 0 — Cadrage ✅
- [x] Inventaire du matériel (PC, smartphone, budget)
- [x] Architecture : `docs/ARCHITECTURE.md`
- [x] Marques et modèles : TV, barre de son, clims, box ; volets filaires → modules Shelly
- [x] Validation des 4 décisions (ARCHITECTURE §6)

## Phase 1 — Core + outils PC
Ordre imposé par l'Expert Sécurité : socle d'abord, outils ensuite.

1. [x] Squelette : `pyproject.toml`, CLI texte (`python -m jarvis`). FastAPI arrive avec son premier client (voix ou PWA).
2. [x] Interface `Tool` + registre + garde de permissions N0–N3 + confirmations.
3. [x] Journal d'audit SQLite (ajout seul, protégé par triggers) et `python -m jarvis audit`.
4. [ ] Routeur d'intentions (YAML + `difflib`) et mesure de latence.
5. [ ] Ollama : benchmark fait, qwen3:14b choisi (docs/MODEL_BENCHMARK.md). Reste : tool calling branché, mode jeu, prompt au tutoiement, protection anti-injection.
6. [ ] Les 15 premiers outils PC (tests : cas nominal, entrée invalide, permission refusée) :

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

Rallumage du PC : Wake-on-LAN (Ethernet). Réglages : BIOS « Power On by PCI-E » activé et ErP désactivé ; Windows : carte réseau « Wake on Magic Packet », démarrage rapide désactivé. Depuis le téléphone : appli Wake-on-LAN sur le réseau local ; à distance, à étudier (Bbox ou serveur dédié, Phase 5).

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
