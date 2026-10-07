# JARVIS — Roadmap

Règle : aucune phase ne démarre sans le feu vert de l'Expert Sécurité **et** du propriétaire.

## État actuel (à lire en reprise de session)
- Phase en cours : **Phase 1**, étapes 1 à 4 faites (routeur + 3 outils N0 fusionnés dans `main` le 2026-10-07) ; Ollama 0.40.0 (127.0.0.1:11434) ; qwen3:8b, ministral-3:8b et qwen3:14b téléchargés le 2026-10-07.
- F1–F12 (docs/SECURITY_REVIEW_PHASE_1.md) et BUG-01..06 (docs/QA_REPORT_PHASE_1.md) corrigés le 2026-10-07, puis la contre-revue (C1–C7, C2bis). Veto N2/N3 levé pour le Core ; écart C1 (pas de HMAC) accepté par le propriétaire (ARCHITECTURE §6.5).
- Routeur : constats Sécurité 1–6, 9 et contre-revue R1–R2 corrigés ; R3 (course jonction pendant `search_files`) accepté jusqu'en Phase 5. QA-R6, R7 corrigés. Constat 7 corrigé (`as_data` dans `permissions.py`, à utiliser pour tout résultat d'outil montré au LLM). Reste : QA-R5 (`list_processes` > 500 ms sous charge, bloque la sortie de Phase 1).
- Benchmark fait (docs/MODEL_BENCHMARK.md) : qwen3:14b choisi.
- Étape 5 codée le 2026-10-07 (essai réel sur qwen3:14b OK), revue Sécurité soldée, recette QA à faire.
- Étape 6 codée le 2026-10-07 : les 13 outils PC restants (`apps`, `audio`, `session`, `clipboard`, `screenshot`, `files` dans `jarvis/tools/pc/`), intentions N1 au routeur. Prochaine action : revue Sécurité de l'étape 6 (points ouverts : listes blanches `~/.jarvis` modifiables par tout processus de l'utilisateur, `run_script` en ExecutionPolicy Bypass, `delete_file` et FOF_WANTNUKEWARNING), recette QA ; QA-R5 en parallèle. Config à créer par le propriétaire : `~/.jarvis/apps.json`, `~/.jarvis/scripts/`.
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
4. [x] Routeur d'intentions (YAML + `difflib`) et mesure de latence.
5. [x] Ollama : qwen3:14b (docs/MODEL_BENCHMARK.md), `jarvis/core/llm.py` : tool calling via la garde, résultats par `as_data`, pas de N2/N3 après un outil `external`, prompt au tutoiement, mode jeu (`jarvis/core/games.py` : Steam, LoL, Valorant, Genshin, Minecraft + `~/.jarvis/games.txt`). Revue Sécurité faite : feu vert, constats 1–4 corrigés (docs/SECURITY_REVIEW_PHASE_1.md), 5, 7, 8 reportés en Phase 5.
6. [x] Les 16 outils PC (revue Sécurité et recette QA à faire) (tests : cas nominal, entrée invalide, permission refusée) :

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
Micro : celui du casque d'abord (décidé le 2026-10-07) ; périphérique d'entrée choisi dans les réglages ; micro d'ambiance à décider en Phase 4 ; réponse vocale sur la sortie associée au micro qui a entendu.

## Phase 5 — Durcissement
À faire : `search_files` ouvre les dossiers par handle (risque R3 accepté en Phase 1).
Audit de sécurité complet, tests d'intrusion (injection de prompt, rejeu de token, accès hors Tailscale), sauvegardes automatiques (SQLite + HA), supervision, documentation finale. À reconsidérer : un serveur dédié (un Pi) pour la disponibilité 24 h/24.
