# Migration du Core sur le mini-PC (option A, décidée le 2026-10-13)

Objectif (propriétaire) : le **Core tourne en permanence sur le mini-PC** ; le PC principal est déchargé. Le PC garde
ce qui exige du matériel Windows ou du GPU.

| | Mini-PC (Debian, 2 cœurs, sans GPU, toujours allumé) | PC principal (Windows, GPU) |
|---|---|---|
| Logiciels | Core (serveur FastAPI, PWA, routeur, outils domotique, mémoire, rappels, journal d'audit), Home Assistant (Docker), Tailscale | Ollama (LLM), micro, mot de réveil, Whisper, Piper, **agent PC**, Claude Code |
| PC éteint | Core en ligne : règles, domotique, PWA, rappels, `pc_plug_on` | LLM, voix, outils PC indisponibles |

Résultat de l'audit du code (2026-10-13) : le Core **ne démarre pas** sur Linux en l'état. `jarvis/core/chat.py:19`
importe `jarvis.tools.pc`, dont les modules appellent `ctypes.WinDLL` à l'import.

## Principes (non négociables)

1. Aucun niveau de permission ne baisse : la garde et les confirmations N2/N3 restent dans le Core ; l'agent PC
   n'exécute que des outils connus, avec une liste blanche, et journalise de son côté.
2. Ollama n'écoute jamais sur toutes les interfaces (INSTALL §3). Si le Core l'atteint par réseau : adresse
   Tailscale ou pare-feu limité au mini-PC, validé par l'Expert Sécurité (veto).
3. Un seul Core actif à la fois (un seul `jarvis.db`). Retour arrière = relancer `serve` sur le PC.
4. Aucun secret, IP ou nom de machine dans le dépôt public.
5. Chaque lot : branche, tests, revue Sécurité si une frontière réseau ou un secret bouge, merge si vert.

## Lots

### Lot 0 : installation du mini-PC (guide à réécrire : Linux + Docker, plus HAOS)
- Debian (installation minimale, SSH par clé, mises à jour automatiques de sécurité), Docker, Home Assistant
  Container, Tailscale. Sauvegarde HA de la VM actuelle : restauration à vérifier sur Container (pas de Supervisor).
- IP fixe Bbox, BIOS « Power On ». Capteur Tapo, script `pc_prise_off` devient inutile au lot 6.

### Lot 1 : le Core démarre sans outils Windows
- `chat.py`, `__main__.py`, `server.py`, `games.py`, `pcplug.py` : import de `tools.pc` conditionnel ; `system_status`
  du dashboard et `games.detect` deviennent des appels optionnels (valeur « indisponible » si le PC est éteint).
- Tests : `skipUnless(sys.platform == "win32")` sur les ~12 fichiers d'outils PC ; ~18 fichiers redeviennent verts
  une fois l'import corrigé.
- **Critère : `python -m unittest discover -s tests` vert sous Linux (WSL ou le mini-PC).**
- **Fait le 2026-10-13** (branche `feat/core-portable`) : `jarvis/core/host.py` (`HAS_PC_TOOLS`, `JARVIS_PC_TOOLS=0` pour
  forcer), imports conditionnels dans `chat.py`, `__main__.py`, `server.py`, `games.py`, `pcplug.py` ;
  `tests/test_core_portable.py` simule un Core sans `jarvis.tools.pc` (import bloqué) ; 8 fichiers de tests d'outils PC
  sautés hors Windows. 919 tests verts sous Windows. **Essai réel sous Linux fait le 2026-10-13** (WSL2 Debian 13, Python 3.13) : suite verte (724 tests, 22 sautés : outils Windows et extra `voice`), `serve` démarre, PWA en 200, API protégée. Corrigés : `JARVIS_BRIEFING_AT` absente plantait le thread des rappels ; proxys désormais toujours enregistrés (`host.load_pc_tools`) pour que le catalogue du routeur reste valide ; `.pyc` périmé masquant un drapeau affaibli dans le contrôle de l'outil Claude Code (`-B`). À noter :
  `test_chat`, `test_levels`, `test_llm`, `test_router`, `test_scenes_qa` importent `jarvis.tools.pc` et risquent de
  réclamer les outils PC : à trancher à ce premier essai.

### Lot 2 : réglages par environnement
- `JARVIS_OLLAMA_URL` (aujourd'hui `llm.py:15`, en dur), `doctor.py` (schtasks → systemd), uptime `/proc/uptime`.
- Secrets : `keyring` sans bureau Linux → backend fichier chiffré ou variables d'environnement d'un service systemd
  (`LoadCredential`), décision de sécurité. Script d'export/import des secrets (valeurs jamais affichées).
- **Fait le 2026-10-13** (branche `feat/core-env`) : `JARVIS_OLLAMA_URL` (`llm.ollama_url`, schéma http(s) exigé) ;
  `doctor.restart_task` relance `jarvis-core.service` (`systemctl --user`) hors Windows ; `dashboard.uptime_s` lit
  `/proc/uptime` ; `secrets.get_secret` lit d'abord `$CREDENTIALS_DIRECTORY/<nom>` (D14 : identifiants systemd
  chiffrés), sinon le coffre de l'OS (sans coffre : `NoKeyringError`, déjà gérée). `python -m jarvis secret export
  <dossier>` écrit un fichier 0600 par secret pour `systemd-creds encrypt` (noms seuls affichés ; dossier hors dépôt, à supprimer après le chiffrement ; sous Windows 0600 est sans effet : dossier privé de l'utilisateur). Revue Sécurité : URL Ollama limitée à boucle locale / Tailscale. Pas d'import :
  sous Linux, le dossier d'identifiants est le coffre. **Reste** : unités systemd (`jarvis-core`, `doctor --watch`,
  `backup`, `purge`) au lot 5, essai réel sous Linux.

### Lot 3 : agent PC (service Windows sur le PC principal)
- Expose les outils `jarvis/tools/pc/*` en HTTP authentifié (signature HMAC + horodatage + nonce, secret dans le
  coffre Windows), écoute limitée à l'interface Tailscale, pare-feu vers le seul mini-PC.
- Côté Core : un proxy enregistre les mêmes noms d'outils, niveaux et schémas ; PC injoignable = erreur claire,
  jamais une action « supposée faite ».
- Le journal d'audit du Core fait foi ; l'agent garde sa trace locale.
- **Revue Sécurité obligatoire avant tout essai réel** (nouvelle surface réseau, exécution de commandes).

- **Fait le 2026-10-13** (branche `feat/agent-pc`) : `jarvis/agent.py` (`serve`, `catalog`), `jarvis/core/agentlink.py`
  (signature, rejeu, proxys), `jarvis/pc_catalog.json`. Le Core sans outils PC enregistre les proxys si
  `JARVIS_AGENT_URL` est posé. Essai réel sur boucle locale OK ; revue Sécurité soldée (docs/DECISIONS.md).
  **Reste** : service Windows de l'agent, pare-feu limité au mini-PC, essai entre deux machines (lot 5).

### Lot 4 : voix, jeu, Claude Code
- Micro, réveil, Whisper, Piper restent sur le PC (agent) : voix indisponible PC éteint.
- Mode jeu : le Core interroge l'agent (outil N0 `game_running`, cache 5 s, échec = pas de jeu) ; pas de push de
  l'agent vers le Core. **Fait le 2026-10-13** (`feat/jeu-agent`).
- Outil `claude_code` : reste sur le PC (CLI et dépôt locaux), via l'agent, `owner_only` inchangé.
- Option plus tard : petit Whisper sur le mini-PC pour la voix PC éteint (plus lent, moins précis).

### Lot 5 : données et bascule
- Copie à froid de `~/.jarvis` (`scripts/backup.py --verify` avant et après : chaîne d'audit et ancre).
- Nom Tailscale : donner au mini-PC **l'ancien nom du PC** (renommer le PC d'abord) pour garder la même origine
  `*.ts.net` : passkeys WebAuthn, abonnements push et appareils enrôlés en dépendent. Sinon : ré-enrôler les appareils.
- Services systemd : `serve`, `doctor --watch`, `backup`, `purge`. Retour arrière documenté.
- **Préparé le 2026-10-13** (`feat/systemd`, `deploy/`), essai réel sous systemd 257 (WSL Debian 13) : unités
  utilisateur `jarvis-core`, `jarvis-doctor` (+ timer 1 min), `jarvis-backup` (+ timer 03:30, sauvegarde puis
  `--verify`), `jarvis-purge` (+ timer 04:00) ; `deploy/env.example` (réglages sans secret) ; `deploy/windows/agent-task.ps1`
  (tâche de l'agent + pare-feu limité au mini-PC, syntaxe vérifiée, jamais exécuté).
  **Identifiants** : `LoadCredentialEncrypted=` échoue en service utilisateur (« Failed to determine local credential
  key: Permission denied », clé hôte en lecture root) ; `deploy/creds.sh` déchiffre via `systemd-creds decrypt --user`
  vers un dossier 0700 de `$XDG_RUNTIME_DIR`, supprimé à l'arrêt. Vérifié : le Core reçoit `ha_token`, arrêt propre.
  **Reste** : revue Sécurité (script de pare-feu, `creds.sh`), essai sur le mini-PC et entre deux machines.
- Installation (mini-PC, dépôt dans `~/jarvis`, venv dans `~/venv`) :
  1. Sur le PC : `python -m jarvis secret export <dossier hors dépôt>` ; copier le dossier sur le mini-PC (Tailscale/scp).
  2. `deploy/creds.sh import <dossier>` (chiffre puis supprime les fichiers), `cp deploy/env.example ~/.config/jarvis/env`
     et le remplir (`chmod 600`).
  3. `cp deploy/systemd/* ~/.config/systemd/user/ && systemctl --user daemon-reload`, `loginctl enable-linger $USER`,
     `systemctl --user enable --now jarvis-core.service jarvis-doctor.timer jarvis-backup.timer jarvis-purge.timer`.
  4. Vérifier : `python -m jarvis doctor`.
- Maintenance : arrêter `jarvis-doctor.timer` avant d'arrêter le Core (le garde-fou le relance sinon en < 1 min).
- Retour arrière : `systemctl --user disable --now` des quatre unités sur le mini-PC, puis relancer la tâche
  « JARVIS - core » sur le PC (un seul Core actif à la fois, principe 3) ; `jarvis.db` du mini-PC, plus récent,
  est à recopier sur le PC après `scripts.backup --verify`.

### Lot 6 : règles d'alimentation (remplace le script HA)
- `pc_off_plug` orchestré par le Core : confirmation N2 → arrêt par l'agent → attente de chute de puissance
  (capteur Tapo) → 30 s → revérification → coupure. Plus de script HA ; si l'arrêt échoue, rien n'est coupé.
- `pc_plug_on` (N1, déjà codé) devient pleinement utile PC éteint.

## Points ouverts (décisions du propriétaire / Sécurité)

| # | Question | Recommandation |
|---|---|---|
| D14 | Backend de secrets sur le mini-PC | Identifiants systemd chiffrés par service |
| D15 | Accès d'Ollama par le Core | Tailscale, pas de port LAN ; ACL Tailscale limitée mini-PC → PC |
| D16 | Nom Tailscale conservé ou appareils ré-enrôlés | Conserver (renommer le PC) |
| D17 | Raccourci routeur pour « éteins le PC » | Non (S12/C4), garder LLM + confirmation |
| D18 | Whisper sur le mini-PC (voix PC éteint) | Plus tard, après mesure de latence |

## Ordre et dépendances

0 → 1 → 2 (les lots 1 et 2 peuvent se faire sur le PC actuel, sans acheter ni installer) → 3 → 4 → 5 → 6.
Le lot 1 est la condition de tout le reste : il se fait en premier, avant même l'arrivée du mini-PC.
