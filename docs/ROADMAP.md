# JARVIS — Roadmap

Règle : aucune phase ne démarre sans le feu vert de l'Expert Sécurité **et** du propriétaire.

## État actuel (à lire en reprise de session)
- Phase en cours : **Phase 1**, étapes 1 à 4 faites (routeur + 3 outils N0 fusionnés dans `main` le 2026-10-07) ; Ollama 0.40.0 (127.0.0.1:11434) ; qwen3:8b, ministral-3:8b et qwen3:14b téléchargés le 2026-10-07.
- F1–F12 (docs/SECURITY_REVIEW_PHASE_1.md) et BUG-01..06 (docs/QA_REPORT_PHASE_1.md) corrigés le 2026-10-07, puis la contre-revue (C1–C7, C2bis). Veto N2/N3 levé pour le Core ; écart C1 (pas de HMAC) accepté par le propriétaire (ARCHITECTURE §6.5).
- Routeur : constats Sécurité 1–6, 9 et contre-revue R1–R2 corrigés ; R3 (course jonction pendant `search_files`) accepté jusqu'en Phase 5. QA-R6, R7 corrigés. Constat 7 corrigé (`as_data` dans `permissions.py`, à utiliser pour tout résultat d'outil montré au LLM). QA-R5 corrigé (`list_processes` via Toolhelp, 11 ms au lieu de 364 ms). `games.py` utilise maintenant la même API (plus de tasklist, ~34 ms).
- Benchmark fait (docs/MODEL_BENCHMARK.md) : qwen3:14b choisi.
- Étape 5 codée le 2026-10-07 (essai réel sur qwen3:14b OK), revue Sécurité soldée, recette QA à faire.
- Étape 6 codée le 2026-10-07 : les 17 outils PC (`apps`, `audio`, `session`, `clipboard`, `screenshot`, `files` dans `jarvis/tools/pc/`), intentions N1 au routeur. Revue Sécurité de l'étape 6 faite : **feu vert sous conditions** (aucun veto), correctifs faits le 2026-10-07 : S1, S2, S4, S6, S7 (C2, C3), C4, S9, S10, S11, S3 (liens physiques seulement) et INSTALL.md §9 (C1). **Prochaine action : recette QA de l'étape 6** (dont le test manuel S6 en fin de docs/QA_REPORT_PHASE_1.md). Config à créer par le propriétaire : `~/.jarvis/apps.json`, `~/.jarvis/scripts/`.
- C5 corrigée le 2026-10-07 (`delete_file` : `IFileOperation` + `FOFX_RECYCLEONDELETE`, échec explicite si corbeille désactivée ou pleine). C6 vérifiée le 2026-10-08 (`Pictures` = dossier local, non redirigé par OneDrive). Reste : test manuel S6 du propriétaire. **Prochaine action : Phase 2 étape 1 (Hyper-V + VM HAOS, docs/DOMOTIQUE_PLAN.md §1.2), qui exige un PowerShell administrateur.**
- Phase 2 étape 1 (2026-10-08) : Hyper-V déjà activé, aucun commutateur externe ni VM. `scripts/haos_vm.ps1 -Vhdx <chemin>` crée commutateur `JarvisLAN` (carte `Ethernet`) + VM ; **à lancer par le propriétaire en PowerShell administrateur** après téléchargement et vérification du VHDX HAOS (home-assistant.io/installation/windows). Ensuite : DOMOTIQUE_PLAN §1.2 étapes 6 à 8.
- Phase 2 étape 1 : VM HAOS en marche (2026-10-08), utilisateur `jarvis` non admin créé. `python -m jarvis secret set ha_token` (jarvis/core/secrets.py, dépendance `keyring`) : le propriétaire y range le token. Client REST codé (`jarvis/core/ha.py`, stdlib, tests OK, `python -m jarvis ha check`) ; URL via `JARVIS_HA_URL` (défaut `http://homeassistant.local:8123`). `ha check` réel OK le 2026-10-08 (HA 2026.10.0, token accepté ; `JARVIS_HA_URL` défini côté PC). TV appairée (Android TV Remote) ; outils `tv_*` codés (jarvis/tools/home/tv.py, docs/TOOLS.md), intentions « allume/éteins la télé » au routeur, essai réel volume OK. Pas de Shelly ni MELCloud chez le propriétaire : volets et clims en attente de matériel. Revue Sécurité des outils TV : feu vert sous conditions, C1–C3 corrigées le 2026-10-08 (taint_blocked sur `tv_key`/`tv_open_app`, nom d'appli non brut, sans proxy, risque HTTP consigné ARCHITECTURE §3.4). `tv_open_app` : `remote.turn_on` + lien propre (YouTube `vnd.youtube://`, Netflix `nflx://`, Twitch `twitch://home`, Spotify `spotify://`), vérifié sur la TV le 2026-10-08 ; Disney+ et Prime Video non lancées (liens à trouver ou applis absentes). Le choix du profil reste à faire à la télécommande. Recette QA des outils TV faite (docs/QA_REPORT_TV.md) : BUG-TV-01..04 corrigés. Revue Sécurité finale des outils TV : **feu vert** (2026-10-08), constats bas 1–2 corrigés. Scène `scene_cinema` créée et vérifiée sur la TV (TV + appli ; volets, lumière, volume préréglé non traités, matériel absent) : revue Sécurité faite le 2026-10-08 : feu vert sous conditions, constats 1–3 corrigés (scène refusée si un sous-outil dépasse N1, échéance en temps réel, HA qui tombe = « non confirmée »). Recette QA faite (docs/QA_REPORT_SCENES.md) : BUG-SC-01..04 corrigés, 366 tests verts. Revue Sécurité finale de la scène : **feu vert** (2026-10-08), constats bas corrigés (`erreur` dans le résultat). **Phase 3 démarrée le 2026-10-08 : étape 1 codée (`jarvis/server.py`, `jarvis/core/devices.py`, `python -m jarvis serve|device`, 387 tests) ; fastapi 0.142.4 et uvicorn 0.54.0 installés (`pip-audit` propre). Pas de Tailscale sur le PC ni le téléphone : étape 2 limitée au local tant qu'il n'est pas installé. Journal du chat : décision RGPD à prendre à l'étape 3 (le journal d'audit est en ajout seul, donc non purgeable : recommandé = longueur + hash, pas le texte). Revue Sécurité de l'étape 1 : feu vert sous conditions (2026-10-08), constats 1–3 et 6 corrigés (Transfer-Encoding refusé, un GET sans `Authorization` ne bloque plus personne, plus de ligne d'audit pendant le verrouillage d'enrôlement, message pour `JARVIS_PORT`), `pip-audit` propre, 392 tests. **Constat 7, bloquant avant toute exposition Tailscale : `Host`/`Origin` sont fixés à `127.0.0.1:port` ; il faudra une liste blanche explicite (nom Tailscale du propriétaire, sans joker, hors dépôt).** Acceptés : verrouillage d'enrôlement global et en mémoire (déni de service par un processus local seulement), 429 non journalisés au-delà de 10 échecs/min, `jarvis.db` modifiable par un processus du même utilisateur. S8 minimal fait (`kill_process` refuse tailscaled, tailscale, tailscale-ipn, ollama* ; Hyper-V déjà couvert par la règle du dossier Windows). **Prochaine action : étape 3 (chat et confirmations N2) après ta décision sur le journal du chat (longueur + hash recommandé), ou étape 2 (QR + Tailscale, à installer).** Plus tard : scènes « je pars » et « bonne nuit » (TV seule pour l'instant)**, ou lien Disney+/Prime Video.
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
| 15b | `power_cancel` (annule l'arrêt pendant les 10 s, constat S11) | N1 |
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
Feu vert Sécurité sous conditions et feu vert propriétaire le 2026-10-08. Chaque étape a sa porte de revue Sécurité ; toutes les conditions (écoute 127.0.0.1 en dur, `Host`/`Origin` vérifiés, token d'appareil seul authentifie, pas de CORS, CSP sans inline, rien d'authentifié en cache, 422 FastAPI remplacé, `pip-audit` propre) sont détaillées dans la revue d'entrée de phase.
1. [x] (codé le 2026-10-08, revue Sécurité à faire) Serveur local minimal + authentification : FastAPI sur 127.0.0.1, table `devices` (hash SHA-256 du token), `python -m jarvis device add|revoke` (CLI interactive, code à usage unique 2 min), audit `pwa:<id>`, `GET /api/ping`, limites de débit et de taille. Aucune route d'outil. Dépendances à faire approuver (fastapi, uvicorn).
2. [ ] Enrôlement par QR (code dans le fragment `#`) + Tailscale (`serve` seulement, jamais `funnel`, ACL `tag:jarvis`). Porte : test depuis un appareil hors ACL.
3. [ ] Chat + confirmations N2 (demandes en attente à usage unique, 60 s, aperçu côté serveur). **Avant : S8 minimal** (`kill_process` refuse tailscaled, ollama, vmms, vmwp, le Core) et **décision RGPD** sur la journalisation du texte des demandes (constat 5 de l'étape 5).
4. [ ] Design system + PWA minimale (chat, journal, appareils, service worker du shell uniquement). Grep XSS en CI.
5. [ ] Réglages des niveaux (surcharges hors registre, baisser = N3, planchers) + N3 WebAuthn (challenge lié à l'action).
6. [ ] Notifications Web Push (VAPID dans le keyring).
Clôture : QA puis feu vert Sécurité sur l'ensemble.
## Phase 4 — Voix
openWakeWord (« hey jarvis »), faster-whisper sur le GPU, Piper en français ; confirmation vocale pour le N2. Le N3 reste sur mobile.
Micro : celui du casque d'abord (décidé le 2026-10-07) ; périphérique d'entrée choisi dans les réglages ; micro d'ambiance à décider en Phase 4 ; réponse vocale sur la sortie associée au micro qui a entendu.

## Phase 5 — Durcissement
Reportés de la revue étape 6 (docs/SECURITY_REVIEW_PHASE_1.md) : S3 (SHA-256 du script affiché à la confirmation puis revérifié avant exécution, exige un état partagé entre confirmation et exécution) ; S5 (captures : `~/Pictures` n'est pas redirigé par OneDrive sur ce PC, donc pas urgent ; à faire : dossier `~/.jarvis/captures`, purge après N jours, mention RGPD) ; S8 (`kill_process` : refuser les ancêtres de Jarvis, Ollama, Tailscale, Home Assistant, afficher le chemin de l'image : demande la table parent/enfant des processus) ; S12 (Phase 4 : mot de réveil ou identification du locuteur ; le test C4 interdit déjà toute intention N2/N3).
À faire : `search_files` ouvre les dossiers par handle (risque R3 accepté en Phase 1).
Audit de sécurité complet, tests d'intrusion (injection de prompt, rejeu de token, accès hors Tailscale), sauvegardes automatiques (SQLite + HA), supervision, documentation finale. À reconsidérer : un serveur dédié (un Pi) pour la disponibilité 24 h/24.

## Pistes OpenJarvis (open-jarvis/OpenJarvis, Apache 2.0, analysé le 2026-10-08)
Rien à reprendre en bloc : c'est un framework généraliste, sans outil Windows ni domotique. À lire comme modèle le moment venu ; toute reprise de code exige un fichier `NOTICE` (attribution Apache 2.0) et une relecture Sécurité.
- **Phase 4 (voix)** : `src/openjarvis/speech/faster_whisper.py` (reconnaissance locale) ; `kokoro_tts.py` (synthèse locale, français, cache de pipeline par langue) comme alternative à comparer avec Piper.
- **Phase 3–4 (tâches et mémoire, ARCHITECTURE §3.8)** : `scheduler/` (≈300 l) et `memory/` (store, extractor) comme modèle.
- **Phase 5 (durcissement)** : `security/injection_scanner.py` en complément de `as_data` (regex en anglais seulement : ajouter les motifs français) ; `ssrf.py`, `credential_stripper.py`, `rate_limiter.py` (petits fichiers, 23 à 160 l).
