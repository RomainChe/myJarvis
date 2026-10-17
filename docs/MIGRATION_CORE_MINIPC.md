    déplacer `tag:jarvis` du PC vers le mini-PC (PC : `tag:pc` seul ; mini-PC : `tag:minipc` + `tag:jarvis`).
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

### Lot 0 : installation du mini-PC (Debian + Docker, plus HAOS)
- Debian (installation minimale, SSH par clé, mises à jour automatiques de sécurité), Docker, Home Assistant
  Container, Tailscale. Sauvegarde HA de la VM actuelle : restauration à vérifier sur Container (pas de Supervisor).
- IP fixe Bbox, BIOS « Power On ». Capteur Tapo, script `pc_prise_off` devient inutile au lot 6.
- **Guide réécrit le 2026-10-13** : docs/INSTALL_SERVEUR_HA.md §1–9 (Debian minimal, SSH par clé, ufw, mises à jour
  automatiques, Docker, HA Container en réseau host, Tailscale, critères de fin §9.4). **Reste : l'installation réelle,
  et vérifier la restauration manuelle de la sauvegarde HAOS (§7.3).**

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
- Micro, réveil, Whisper, Piper : **pas codé**. La voix tourne dans le processus du Core (`start_mic`) : après la
  bascule (lot 5), plus de voix ni de rappels parlés. Accepté le 2026-10-16 (voix inutilisée pour l'instant).
  **Lot 4b codé le 2026-10-17** (`feat/lot4b-voix`) : `python -m jarvis voice` sur le PC (micro, Whisper GPU et Piper
  en local) envoie le texte à `POST /api/voice` du Core (HTTPS Tailscale, ACL `tag:pc` -> `tag:jarvis:443` déjà en place).
  Plafond N0/N1 (N2 « depuis l'application », N3 refusé), source `voix`, clé d'appareil dans le coffre Windows
  (`secret set voice_key`), 20 phrases/min/appareil, identifiant de micro `client` journalisé (multi-micros : un autre
  processus avec un autre `JARVIS_VOICE_CLIENT`, pas codé). Rappels parlés : le Core appelle l'outil `say` (N1) de l'agent ;
  PC éteint = push seul. `start_mic` ne fait rien sur un Core sans outils PC. **Reste** : QA, revue Sécurité, essai réel
  avec le casque (créer l'appareil `voix-pc` avec `device add`, poser `JARVIS_CORE_URL`).
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
- **Complété le 2026-10-16** (`feat/lot5-bascule`) : `agent-task.ps1` expose aussi Ollama sur l'IP Tailscale du PC
  (D15, `OLLAMA_HOST`, jamais `0.0.0.0`) avec pare-feu limité au mini-PC, signale les règles plus larges, relançable ;
  unités `jarvis-banque` (+ timer 07:00, remplace la tâche Windows « JARVIS - banque »). Procédure ci-dessous.

#### A. Préparation (le Core tourne encore sur le PC, aucune coupure)
Sur le **mini-PC** (SSH, dépôt dans `~/jarvis`, venv dans `~/venv`) :
1. `sudo apt install git python3-venv`, `git clone https://github.com/RomainChe/myJarvis ~/jarvis`,
   `python3 -m venv ~/venv && ~/venv/bin/pip install -e ~/jarvis`.
2. `cd ~/jarvis && ~/venv/bin/python -B -m unittest discover -s tests` : vert (outils Windows et `voice` sautés).

Sur le **PC** (PowerShell administrateur, adresses lues dans `tailscale status`, jamais écrites dans le dépôt) :
3. `python -m jarvis secret set agent_key` si absente (valeur : `python -c "import secrets; print(secrets.token_urlsafe(48))"`).
4. `winget upgrade Ollama.Ollama` (dernière version stable, `ollama --version` ; jamais `OLLAMA_ORIGINS`), puis
   `deploy\windows\agent-task.ps1 -TailscaleHost <IP-TS-PC> -MiniPc <IP-TS-minipc>` ; quitter puis relancer Ollama ;
   si Windows demande « Autoriser l'accès », **refuser** ; **relancer le script** et désactiver toute règle signalée
   « plus large » (`Disable-NetFirewallRule -DisplayName <nom>`, ex. la règle `python.exe` créée par Python). Variable Windows (le Core du PC ne lit pas `.env`) : `setx JARVIS_OLLAMA_URL http://<IP-TS-PC>:11434`
   (Ollama n'est plus sur `127.0.0.1`), relancer « JARVIS - core » et vérifier une question au LLM.
5. Se déconnecter puis se reconnecter (la tâche de l'agent démarre à l'ouverture de session).
6. `python -m jarvis secret export "$env:LOCALAPPDATA\Temp\jarvis-export"` (jamais sous OneDrive : les secrets sont en
   clair et 0600 est sans effet sous Windows ; refusé par le code), `scp -r "$env:LOCALAPPDATA\Temp\jarvis-export"
   jarvis@<IP-minipc>:export`, puis `Remove-Item -Recurse "$env:LOCALAPPDATA\Temp\jarvis-export"`.

Sur le **mini-PC** :
7. `~/jarvis/deploy/creds.sh import ~/export` (chiffre puis supprime), `mkdir -p ~/.config/jarvis`,
   `cp ~/jarvis/deploy/env.example ~/.config/jarvis/env && chmod 600 ~/.config/jarvis/env`, le remplir :
   `JARVIS_HA_URL=http://127.0.0.1:8123`, `JARVIS_OLLAMA_URL=http://<IP-TS-PC>:11434`,
   `JARVIS_AGENT_URL=http://<IP-TS-PC>:8788`, `JARVIS_TS_HOST=<ancien nom du PC>.<tailnet>.ts.net`, le reste
   recopié des variables Windows `JARVIS_*` du PC (`Get-ChildItem env:JARVIS_*`).
8. **ACL Tailscale (D15, exigée par la Sécurité avant B)**, console Tailscale > Access controls, en gardant une session
   SSH ouverte vers le mini-PC par l'IP locale. Un tag par rôle : `tag:jarvis` = machine du Core (PWA, se déplace au 12),
   `tag:pc` = Ollama et agent, `tag:minipc`. Machines > Edit ACL tags : PC `tag:jarvis` + `tag:pc`, mini-PC `tag:minipc`,
   téléphone sans tag. Un appareil étiqueté n'est plus `autogroup:member` : sans règle, il ne joint plus rien.
   ```json
   {"tagOwners": {"tag:jarvis": ["autogroup:admin"], "tag:pc": ["autogroup:admin"], "tag:minipc": ["autogroup:admin"]},
    "acls": [
      {"action": "accept", "src": ["autogroup:member"], "dst": ["tag:jarvis:443"]},
      {"action": "accept", "src": ["tag:minipc"], "dst": ["tag:pc:8788,11434"]},
      {"action": "accept", "src": ["tag:pc"], "dst": ["tag:minipc:22,8123", "tag:jarvis:443"]}],
    "tests": [
      {"src": "tag:minipc", "accept": ["tag:pc:11434", "tag:pc:8788"], "deny": ["tag:pc:22", "tag:pc:443"]},
      {"src": "tag:pc", "accept": ["tag:minipc:22", "tag:minipc:8123"], "deny": ["tag:minipc:8788"]},
      {"src": "<ton e-mail>", "accept": ["tag:jarvis:443"], "deny": ["tag:pc:11434", "tag:pc:8788", "tag:minipc:22"]}]}
   ```
9. Contrôles de frontière, après l'ACL et la relance d'Ollama : `curl -s http://<IP-TS-PC>:11434/api/version` répond
   depuis le mini-PC ; la même URL **échoue** depuis le téléphone (Tailscale actif) et depuis un autre PC du réseau
   local. Idem pour le port 8788. Raison : Ollama n'a pas d'authentification, quiconque l'atteint peut remplacer le
   modèle (`/api/create`, `/api/pull`) par un modèle piégé qui proposerait des outils N1.

#### B. Bascule (coupure de quelques minutes)
Sur le **PC** :
10. `Disable-ScheduledTask` sur « JARVIS - garde-fou » (d'abord, sinon il relance le Core), « JARVIS - core »,
   « JARVIS - banque », « JARVIS - sauvegarde » ; arrêter le processus `serve` restant ; `tailscale serve reset`.
11. `python -m scripts.backup --verify` (chaîne d'audit et ancre), puis `scp -r "$HOME\.jarvis" jarvis@<IP-minipc>:` (PowerShell ne développe pas `~`
    pour `scp`).
12. Console Tailscale : renommer le PC (ex. `pc-bureau`), puis donner au mini-PC **l'ancien nom du PC** (D16).

Sur le **mini-PC** :
13. `cd ~/jarvis && ~/venv/bin/python -m scripts.backup --verify` (même résultat qu'au 11).
14. `sudo tailscale serve --bg --https=443 http://127.0.0.1:8765` (**jamais `funnel`**) ; `tailscale funnel status` vide.
15. `mkdir -p ~/.config/systemd/user && cp ~/jarvis/deploy/systemd/* ~/.config/systemd/user/`,
    `systemctl --user daemon-reload`, `sudo loginctl enable-linger jarvis`,
    `systemctl --user enable --now jarvis-core.service jarvis-doctor.timer jarvis-backup.timer jarvis-purge.timer jarvis-banque.timer`.

#### C. Vérifications (critères de fin du lot 5)
- [x] `doctor` vert sur le mini-PC (2026-10-17), avec les réglages et identifiants du service (sinon Ollama et HA sont KO à tort) :
      `set -a; . ~/.config/jarvis/env; set +a; ~/jarvis/deploy/creds.sh run ~/venv/bin/python -m jarvis doctor`.
- [x] ACL en place, `tailscale funnel status` vide, `agent-task.ps1` relancé sans règle « plus large » signalée.
      2026-10-17 : tags vérifiés (PC `tag:pc`, mini-PC étiqueté), funnel sans entrée publique (`serve` « tailnet only »),
      Ollama et agent n'écoutent que sur l'IP Tailscale ; seules les deux règles « mini-PC seul » ouvrent 8788 et 11434.
- [x] PWA depuis le téléphone : connexion par passkey sans ré-enrôlement, notification push reçue.
      2026-10-17 : appareils enrôlés avant la bascule (`pwa:1`, `pwa:4`) utilisés sans ré-enrôlement ; `push test 1`
      reçu (PWA fermée : elle masque les notifications quand elle est affichée).
- [x] « allume la télé » (routeur + HA local) ; une question au LLM (Ollama du PC) ; un outil PC (ex. volume) via l'agent,
      présent au journal d'audit du Core.
      2026-10-17 : `tv_on` et `set_volume` (`{'volume': 30}`, via l'agent) au journal ; le LLM répond.
- [x] PC éteint : PWA, domotique et rappels OK ; LLM et outils PC renvoient une erreur claire.
      2026-10-17 : règles du routeur et rappels OK, LLM « Ollama ne répond pas » ; outil PC non essayé (même
      chemin d'erreur que le LLM, `chat.py`, message « PC injoignable »).
- [ ] Le lendemain : `jarvis-backup` et `jarvis-banque` ont tourné (`systemctl --user list-timers`).
      2026-10-17 : cinq unités actives, premiers passages prévus le 2026-10-18 (03:30 et 07:00).
- [ ] Une semaine sans retour arrière : supprimer la VM Hyper-V et les tâches Windows désactivées au 10.

- Maintenance : arrêter `jarvis-doctor.timer` avant d'arrêter le Core (le garde-fou le relance sinon en < 1 min).
- Retour arrière : `systemctl --user disable --now` des cinq unités et `sudo tailscale serve reset` sur le mini-PC ;
  rendre son nom Tailscale et `tag:jarvis` au PC ; recopier `~/.jarvis` du mini-PC (plus récent) sur le PC après `scripts.backup --verify` ;
  sur le PC, réactiver les quatre tâches du 10 et relancer `tailscale serve` (un seul Core actif à la fois, principe 3).
  Ollama et l'agent restent sur l'IP Tailscale (`agent-task.ps1 -Remove` pour revenir à `127.0.0.1`, puis retirer
  la variable Windows `JARVIS_OLLAMA_URL` : `[Environment]::SetEnvironmentVariable("JARVIS_OLLAMA_URL", $null, "User")`).

### Lot 6 : règles d'alimentation (remplace le script HA)
- `pc_off_plug` orchestré par le Core : confirmation N2 → arrêt par l'agent → attente de chute de puissance
  (capteur Tapo) → 30 s → revérification → coupure. Plus de script HA ; si l'arrêt échoue, rien n'est coupé.
- `pc_plug_on` (N1, déjà codé) devient pleinement utile PC éteint.
- **Fait le 2026-10-13** (`feat/pc-off-plug`) : `pcplug.py` réécrit. L'outil refuse si la prise ou la mesure est illisible, demande l'arrêt à l'agent (`power`, échec = rien n'est coupé), puis un thread de fond attend la chute de puissance (5 min), 30 s, revérifie, coupe et journalise l'issue. Refusé sur un Core hébergé par le PC. `script.pc_prise_off` peut être supprimé de HA. **Reste** : revue Sécurité, essai réel (HA et agent sur le mini-PC).

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
12. Console Tailscale : renommer le PC (ex. `pc-bureau`), puis donner au mini-PC **l'ancien nom du PC** (D16) ;
