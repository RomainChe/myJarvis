# Décisions et risques acceptés

## 2026-10-08 — Planchers de niveau abaissés de N2 à N1
- Demande du propriétaire : tous les outils peuvent être réglés en N1. `power`, `delete_file`, `move_file`, `kill_process`, `run_script` : plancher N1 (N0 reste interdit). Abaisser reste une action N3 (clé d'accès).
- Risque accepté : un outil abaissé en N1 s'exécute sans confirmation depuis la PWA ou la CLI (ex. suppression, arrêt du PC).
- Garde-fous maintenus (revue Sécurité : feu vert sous conditions, conditions remplies) : après du contenu externe, le LLM ne peut pas lancer un outil dont le niveau du registre est ≥ N2 (`llm.py`) ; à la voix, le niveau du registre s'applique toujours (`permissions.execute`, source `voix`), car le micro entend aussi la TV ou un visiteur.

## 2026-10-08 — Phase 4 : modèles de la voix
- Téléchargés par `scripts/fetch_models.py` depuis des révisions épinglées, SHA-256 au manifeste. Licences non permissives, usage personnel seulement : openWakeWord CC BY-NC-SA 4.0, voix `tom` AGPL-3.0. Poids jamais commités. Silero VAD déjà dans faster-whisper.

## 2026-10-08 — Phase 4 : dépendances de la voix
- Approuvées par le propriétaire : `faster-whisper` 1.2.1 (MIT), `openwakeword` 0.6.0 (Apache 2.0, licence des modèles à vérifier), `piper-tts` 1.8.0 (**GPL-3.0**), `sounddevice` 0.5.6 (MIT). Déclarées dans l'extra `voice` de `pyproject.toml` ; `pip-audit` propre.
- Risque GPL-3.0 de Piper accepté : usage personnel local, rien n'est redistribué, le dépôt public n'embarque ni Piper ni les voix ni les poids de modèles. La licence de chaque voix `fr_FR` est à vérifier avant son choix.
- A7 (test d'un appareil hors ACL Tailscale) non fait en Phase 3, accepté ; à lever en Phase 5.

## 2026-10-08 — Phase 4 étape 3 : revue Sécurité de la synthèse vocale
- Condition 20 : si un outil `private` a tourné pendant un tour vocal (routeur ou LLM), la réponse est remplacée par « Fait, voir l'application. » (`voice.py`, suivi par un relais du journal). `Speaker.say` est interne : seul `Voice.say` doit l'appeler.
- Condition 23 : la voix et sa config `.json` doivent figurer au manifeste et être vérifiées (SHA-256), sinon `TTSError`. `sha256_of`/`is_good` vivent dans `jarvis/core/modelcheck.py` (plus de chargement dynamique de scripts/).
- `gpu.py` : site-packages du Python courant seulement (pas le site utilisateur), dossiers ajoutés en fin de PATH et via `os.add_dll_directory`. Limite acceptée : les sous-processus des outils (apps, scripts, nvidia-smi...) héritent de ce PATH ; les épurer demanderait un `env=` à chaque `subprocess`, non fait. Risque faible : dossiers en fin de PATH, dans le Python de l'utilisateur.
- Risque accepté (TOCTOU) : un fichier de `models/` pourrait être remplacé entre la vérification et le chargement ; `models/` n'est inscriptible que par l'utilisateur lui-même (même niveau de confiance que le code du dépôt).
- `say` (commande de lecture) n'est pas un canal de commande : elle lit un texte, ne déclenche aucun outil ni aucune action.

## 2026-10-08 — Phase 4 étape 5 : Whisper branché
- Constat 10 (étape 4) consigné, risque accepté : TOCTOU des modèles (vérifiés puis chargés, `models/` inscriptible par l'utilisateur seul, même confiance que le code) ; le modèle Silero VAD est embarqué dans le paquet `faster-whisper` et n'est pas au manifeste (protégé par le pin de version et `pip-audit`).
- `stt.py` : tous les fichiers `whisper-large-v3-turbo/*` du manifeste vérifiés avant chargement ; hors ligne ; l'audio reste en mémoire (tableau float32), jamais de fichier temporaire. Le texte reconnu n'est pas journalisé (seul `Voice.handle` écrit longueur + SHA-256). La commande `mic listen` l'affiche dans le terminal du propriétaire seulement.
- La voix reste plafonnée à N0/N1 : une phrase reconnue ne peut pas confirmer un N2 (pas d'empreinte vocale).

## 2026-10-08 — Phase 6 : bouton micro, tableau de bord
- **Micro** : `serve` lance l'écoute ; la PWA coupe librement (journalisé `pwa:<id>`). Réarmer depuis la PWA : voir l'entrée du 2026-10-08 « Réarmer le micro » (remplace le risque accepté d'origine). Journal écrit AVANT le réarmement.
- **Tableau de bord** (`/api/dashboard`, N0) : non journalisé (rafraîchi toutes les 5 s, lecture seule, données fixes) ; jamais exposé comme outil au LLM.
- **Sorties réseau** : Open-Meteo (HTTPS, coordonnées arrondies à ~1 km, toutes les 15 min, avec l'IP du foyer ; échec mis en cache 60 s) et ping TCP vers 1.1.1.1:443. Coordonnées dans `~/.jarvis/dashboard.json`, hors dépôt.

## 2026-10-08 — Réarmer le micro : clé d'accès obligatoire (revue Sécurité de l'étape 6, constat haut)
- Décision du propriétaire : **couper** le micro reste libre (PWA, CLI) ; **réarmer** depuis la PWA est traité comme un N3 : signature d'une clé d'accès sur un défi `mic:on` (usage unique, lié à l'appareil), sans repli sur le token seul. Un appareil sans clé d'accès reçoit un 403 journalisé « refusé ». `GET /api/mic` n'expose plus `strong`.
- Assouplit la règle d'origine « réarmer exige un terminal » : le terminal (`python -m jarvis mic on`) reste possible et sert de repli, la PWA l'est aussi, mais seulement avec WebAuthn. Sans `JARVIS_TS_HOST` (pas d'adresse HTTPS Tailscale), WebAuthn ne marche pas : réarmer se fait alors au terminal.
- Remplace le risque accepté du 2026-10-08 « Phase 6 : bouton micro » (réarmement au token seul). Tests : `tests/test_mic_web.py` (sans clé, signature invalide, assertion sans clé enregistrée, signature valide, journal en échec).

## 2026-10-08 — Connecteur mail : actions N1 encore permises après lecture d'un mail (revue Sécurité, constat 6)
- `mail_recent` est N2 + `external` : après lui le LLM ne peut plus lancer de N2/N3 ni d'outil `taint_blocked`. Restent permis `lock_session`, `screen_off`, `set_volume`, `mute`, `media_control`, `open_app` (liste blanche), `power_cancel` : un mail piégé pourrait verrouiller la session ou couper l'écran, sans exfiltration ni destruction.
- **Risque accepté en attendant la décision du propriétaire** : passer `taint_blocked` sur `lock_session`, `screen_off` et `power_cancel` si ce n'est pas souhaité.
- Le `Date:` d'un mail est contrôlé par l'expéditeur : l'ordre de la liste n'est pas une preuve de fraîcheur.

## 2026-10-08 — Onglet Réseaux : appel sortant vers Google et jeton de lol-clipper (revue Sécurité étape 2)
- Premier flux sortant de Core vers un compte personnel : `oauth2.googleapis.com` (renouvellement) et `googleapis.com/youtube/v3` (abonnés, vues), N0, non audité comme le reste de l'onglet. L'adresse de renouvellement est fixe : le `token_uri` du fichier est ignoré.
- Le renouvellement demande `scope=youtube.readonly` : le jeton d'accès en mémoire ne peut pas publier.
- **Risque accepté** : Jarvis lit `youtube_token.json` de lol-clipper, dont le `refresh_token` porte aussi le droit d'envoi de vidéos. Idéal à terme : un jeton `youtube.readonly` séparé.
- Constat 2 (redirections HTTP) laissé : hôtes Google seulement. Constat 6 (cache sans les ids récents) cosmétique.

## 2026-10-08 — Finances et Veille IA : risques acceptés par le propriétaire
- **Finances, constat 7** : l'onglet s'ouvre sans clé d'accès WebAuthn (token d'appareil seul). Risque accepté.
- **Finances, constat 1** et **Veille IA, constat 1** : l'expéditeur d'un mail est falsifiable (pas de contrôle `Authentication-Results`). Risque accepté : faux chiffres en Finances ; en Veille, liens https cliquables posés par un mail usurpé (le domaine réel reste affiché sous chaque lien).
- **Test manuel S6** (corbeille, gros fichier) retiré par le propriétaire ; `delete_file` reste couvert par les tests automatiques.

## 2026-10-08 — Gel de la Phase 5 levé pour l'outil Claude Code (Phase 6 étape 9)
- Le propriétaire a demandé de coder l'étape 9 pendant l'audit de la Phase 5 : le gel des fonctions est levé pour cette seule étape.
- Revue Sécurité : veto sur les garde-fous (pas sur le niveau N1). Correctifs apportés :
  - **Garde (a)** : l'outil est `owner_only`, donc jamais proposé au LLM. `execute` ne l'accepte que de la liste blanche `cli` et `pwa:<id>` : ni LLM, ni voix, ni automatisme. Seul le routeur le déclenche, sur le préfixe « code : » ou « modifie ton code ».
  - **Session de Claude isolée** : `--restricted --strict-mcp-config`, sans connecteurs claude.ai, sans web. Le seul Bash autorisé est `python -m unittest`. Le worktree est dans `%LOCALAPPDATA%\jarvis-claude-work`, hors de `~/.jarvis`.
  - **Garde (b)**, la fusion `--ff-only` exige :
    - un dépôt propre et sur `main` ;
    - aucun chemin protégé touché (`dev.PROTECTED` : garde, routeur, serveur, audit, appareils, CLAUDE.md, `.claude/`…) ;
    - aucun test existant modifié ;
    - aucune IP, adresse mail ou secret ajouté ;
    - une suite verte, signée par un jeton passé sur stdin, sans moins de tests ni plus de tests sautés ;
    - un import sain du serveur.
  - Sinon : « revue requise », la branche est gardée.
  - **Commit** : le message est générique, la demande reste dans `~/.jarvis/claude_last.json`. Une ligne d'audit précède la fusion (échec fermé), avec le hash du commit.
  - **Contre-revue** :
    - Les niveaux et drapeaux de chaque outil existant sont comparés entre `main` et la branche. Un outil abaissé, affaibli ou retiré donne « revue requise » ; les nouveaux outils sont listés dans le compte rendu et l'audit.
    - `jarvis/web/app.js`, `index.html`, `sw.js`, `mic.py`, `scenes.py` et `tests/__init__.py` sont protégés.
    - Les fichiers ajoutés sous `tests/` doivent s'appeler `test_*.py`.
    - `credential.helper` est vidé.
- **Décisions du propriétaire (2026-10-08)** :
  - **Voix refusée** pour `claude_code` : la demande se tape dans la PWA ou au terminal.
  - **Constat 8, risque accepté** : tout appareil enrôlé peut lancer l'outil, sans clé d'accès. Un token d'appareil volé suffit donc à faire exécuter du code sur le PC.
  - **Constats 9 et 5, risque accepté jusqu'à la Phase 5** :
    - Le code lancé par les tests tourne avec les droits de l'utilisateur ; il peut lire le keyring et le réseau. Le push est neutralisé (`pushurl=disabled://`, pas d'identifiants).
    - Le verdict des tests protège contre une erreur de bonne foi, pas contre un code malveillant : un module de test tourne dans le processus du lanceur.
    - Correctif prévu en Phase 5 : un compte Windows dédié ou un bac à sable sans réseau.
- **Suivis** :
  - Les fichiers non suivis du dépôt ne sont pas contrôlés (constat 7 de la contre-revue).
  - Le nouveau serveur ne réessaie pas de prendre le port, et aucun retour au dernier commit sain n'est prévu (constat 10, partiel).
  - Au délai dépassé, l'arbre de processus n'est pas tué (constat 13). Sans effet aujourd'hui : `claude.exe` est natif.
