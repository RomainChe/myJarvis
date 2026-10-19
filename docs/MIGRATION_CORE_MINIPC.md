# Migration du Core sur le mini-PC (option A, décidée le 2026-10-13)

Objectif : le **Core tourne en permanence sur le mini-PC** ; le PC principal garde ce qui exige Windows ou le GPU.
Détail des lots finis (procédures pas à pas, mesures, ACL complète) : historique git de ce fichier (avant le 2026-10-19).

| | Mini-PC (Debian, Pentium G4400T 2 cœurs sans AVX, 7,8 Go, toujours allumé) | PC principal (Windows, GPU) |
|---|---|---|
| Logiciels | Core (FastAPI, PWA, routeur, domotique, mémoire, rappels, audit), Home Assistant (Docker), Tailscale, Vosk + Piper (salon) | Ollama, micro, mot de réveil, Whisper, Piper, **agent PC**, Claude Code |
| PC éteint | Core en ligne : règles, domotique, PWA, rappels, `pc_plug_on`, voix du salon | LLM, voix PC, outils PC indisponibles (erreur claire) |

## Principes (non négociables)
1. Aucun niveau de permission ne baisse : garde et confirmations N2/N3 restent dans le Core ; l'agent PC n'exécute qu'une liste blanche et journalise aussi.
2. Ollama n'écoute jamais sur `0.0.0.0` : IP Tailscale du PC + pare-feu limité au mini-PC (D15).
3. Un seul Core actif à la fois (un seul `jarvis.db`).
4. Aucun secret, IP ou nom de machine dans le dépôt public.
5. Chaque lot : branche, tests, revue Sécurité si une frontière réseau ou un secret bouge.

## Lots : état
- **0 Installation mini-PC** ✅ : guide docs/INSTALL_SERVEUR_HA.md. Restauration manuelle de la sauvegarde HAOS (§7.3) : faite.
- **1 Core portable** ✅ : `jarvis/core/host.py` (`HAS_PC_TOOLS`, `JARVIS_PC_TOOLS=0`), imports conditionnels ; suite verte sous Linux (outils Windows et extra `voice` sautés).
- **2 Réglages par environnement** ✅ : `JARVIS_OLLAMA_URL` (boucle locale / Tailscale seulement), `doctor` → systemd, secrets par `$CREDENTIALS_DIRECTORY` (D14), `python -m jarvis secret export`.
- **3 Agent PC** ✅ : `jarvis/agent.py`, `jarvis/core/agentlink.py` (HMAC + horodatage + nonce), `jarvis/pc_catalog.json` ; proxys côté Core, PC injoignable = erreur claire. Mode jeu via l'outil N0 `game_running`. `claude_code` reste sur le PC via l'agent.
- **4b Voix du PC** ✅ : `python -m jarvis voice` → `POST /api/voice` (plafond N0/N1, 20 phrases/min/appareil, clé `voice_key`). Rappels parlés par l'outil `say` de l'agent.
- **4c Voix du salon** ✅ déployée : Voice PE → pipeline Assist HA → Vosk (Wyoming) → composant HA `jarvis_voice` → `POST /api/voice` (appareil `voix-salon`, clé de portée voix, `client=salon`) → Piper.
- **5 Bascule** ✅ : unités systemd utilisateur `deploy/systemd/` (`jarvis-core`, `-doctor`, `-backup`, `-purge`, `-banque`, `-update`), `deploy/creds.sh`, `deploy/windows/agent-task.ps1`. Le mini-PC porte l'ancien nom Tailscale du PC (passkeys, push et appareils conservés, D16). ACL : tags `tag:jarvis` / `tag:pc` / `tag:minipc` ; mini-PC → PC sur 8788 et 11434 seulement ; téléphones → `tag:jarvis:443`.
- **6 Règles d'alimentation** : `pc_off_plug` orchestré par le Core (N2 → arrêt par l'agent → chute de puissance Tapo → 30 s → revérification → coupure), codé.

## Reste à faire
- **Lot 5, C** : vérifier `jarvis-backup` et `jarvis-banque` (`systemctl --user list-timers`), puis après une semaine sans retour arrière (timers du 2026-10-18) supprimer la VM Hyper-V et les tâches Windows désactivées (« JARVIS - garde-fou », « - core », « - banque », « - sauvegarde »).
- **Lot 6** : revue Sécurité de `pc_off_plug`, test à blanc de la prise Tapo (INSTALL_SERVEUR_HA §10.3).
- **Lot 4c** : Voice PE à recevoir, adopter dans HA (mot de réveil `hey_jarvis`, sensibilité la plus basse), compter les faux réveils TV allumée sur une journée. Vérifier au premier essai : l'entité `JarvisConversation` apparaît, une réponse vide ne plante pas Assist, pas d'audio conservé dans HA.
- **Lot 4c, reportés Sécurité** : conteneurs `voice-salon` sans `read_only` ni utilisateur non-root (à essayer : `read_only: true` + `tmpfs: [/tmp]`) ; images épinglées par version, pas par condensat ; modèles Vosk/Piper téléchargés sans somme de contrôle (télécharger une fois, vérifier le SHA-256, monter en lecture seule) ; `cap_drop: ALL` non vérifié (si un conteneur ne démarre pas, le retirer et le dire).
- **Le Core sur le mini-PC** : pas de Whisper, donc `/api/stt` (bouton « parler » de la PWA) répond 503 ; à relayer vers le PC si voulu.

## Faits à retenir (lot 4c)
- **Vosk `vosk-model-small-fr-0.22`** choisi (mesuré le 2026-10-17, voix synthétique, plafond de précision) : 0,06 s après la fin de phrase en flux, 18 %/22 % d'erreurs propre/bruit, 0,36 Go. Whisper `small` : 7,3 s (CPU sans AVX), `base` : 2,5 s et 40 % d'erreurs, `tiny` inutilisable ; whisper.cpp non testé, pas de gain attendu. Avec un CPU AVX2 (ex. N100) : refaire la mesure.
- Les erreurs Vosk sont des homophones (« éteint », « mais la TV », « très fin » pour TF1) : `router.voice_fix` (appelée par `Voice.handle`) les corrige en début de phrase.
- Conteneurs `deploy/voice-salon/docker-compose.yml` : `rhasspy/wyoming-vosk:1.5.1` (10300) et `rhasspy/wyoming-piper:2.5.2` (10200, voix `fr_FR-tom-medium`), publiés sur `127.0.0.1` seulement, aucune règle ufw.
- Composant HA `deploy/homeassistant/custom_components/jarvis_voice/` : `http` refusé hors `127.0.0.1`, clé dans le stockage de HA. Tout le texte passe par le Core et son journal (un agent YAML laisserait les intentions intégrées de HA exécuter « allume le salon » hors journal).
- Mot de réveil du boîtier : modèles officiels `hey_jarvis`, `okay_nabu`, `hey_mycroft`, `stop` (anglais). Pas de « Jarvis » seul ni de modèle français ; l'entraîner = `kahrendt/microWakeWord` + micrologiciel ESPHome recompilé (plus tard). Faux réveils annoncés pour `hey_jarvis` : 0,56/h (seuil 0,97) à 1,5/h (0,83).
- « Jarvis, hors ligne » : le Core répond « Je me mets hors ligne. » puis ignore tout sauf « en ligne » ; état en mémoire, perdu au redémarrage (décision du propriétaire). Le vrai silence est l'interrupteur matériel du boîtier.
- Garde au salon : tous les outils N1 acceptés (décision du propriétaire) sauf `VOICE_BLOCKED` (`memory_set`, `memory_forget`, `clipboard_write`, `driverwatch_accept`) ; N2/N3 refusés. Risque accepté : une phrase entendue (TV, voisin) déclenche `open_app`, `close_app`, `lock_session`, `screen_off` ; ne pas abaisser `power`, `delete_file`, `move_file`, `kill_process`, `run_script` en N1.
- Vie privée : audio local (boîtier, HA, Vosk, Piper) ; journal du Core = longueur + SHA-256 de la phrase.
- Retour arrière salon : `python -m jarvis device revoke <id de voix-salon>` (effet immédiat), `docker compose down` dans `/srv/voice-salon`, retirer `custom_components/jarvis_voice`, redémarrer HA.

## Retour arrière de la bascule (lot 5)
`systemctl --user disable --now` des six unités et `sudo tailscale serve reset` sur le mini-PC ; rendre son nom Tailscale et `tag:jarvis` au PC ; recopier `~/.jarvis` du mini-PC sur le PC après `scripts.backup --verify` ; réactiver les quatre tâches Windows et relancer `tailscale serve`. `agent-task.ps1 -Remove` ramène Ollama et l'agent sur `127.0.0.1` (puis retirer la variable Windows `JARVIS_OLLAMA_URL`). Maintenance : arrêter `jarvis-doctor.timer` avant d'arrêter le Core.

## Décisions
D14 secrets = identifiants systemd chiffrés · D15 Ollama par Tailscale + ACL · D16 nom Tailscale conservé · D17 pas de raccourci routeur pour « éteins le PC » (S12/C4) · D18 Vosk, pas Whisper, sur le mini-PC.
