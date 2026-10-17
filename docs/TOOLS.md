# Outils de Jarvis

Chaque outil passe par la garde de permissions (`jarvis/core/permissions.py`) et chaque appel est
écrit dans le journal d'audit. Le niveau indiqué est celui par défaut.

Essai en ligne de commande : `python -m jarvis run <outil> [clé=valeur ...]`.

## Routeur d'intentions

`jarvis/core/router.py` reconnaît les commandes simples sans LLM, à partir du catalogue
`jarvis/intents.json` :

- `phrases` : phrases sans paramètre, reconnues de façon approchée (`difflib`, seuil 0,8), après
  normalisation (minuscules, accents et ponctuation retirés, « Jarvis » retiré) et retrait des mots
  vides (« quel est l'état du PC » → « etat pc »). Un verbe d'action (« tue », « ferme »…) absent de
  la phrase reconnue annule la correspondance.
- `patterns` : expressions régulières, insensibles à la casse, sur le texte presque brut (seuls
  « Jarvis » en tête et la ponctuation finale sont retirés) : les slots gardent accents,
  parenthèses et chemins. `{slot}` devient un paramètre (texte).
- `defaults` : paramètres par défaut, complétés par les slots.

Depuis la CLI : `python -m jarvis "cherche facture dans mes documents"`. Phrase non reconnue :
message clair, aucune action.
Le routeur renvoie `(outil, paramètres)` ou `None` (la demande ira au LLM). Il propose
seulement : c'est la garde de permissions qui décide. Latence mesurée par un test : < 50 ms.

## game_running

- **Description** : un jeu tourne-t-il sur le PC ? Sert au mode jeu (le LLM évite la carte graphique).
- **Niveau** : N0 (lecture). **Paramètres** : aucun. **Retour** : `true` / `false`.
- **Exemple** : `python -m jarvis run game_running`.
- **Notes** : Core sur le mini-PC : `games.detect` interroge l'agent par cet outil (cache 5 s ; agent injoignable =
  `false`, nouvel essai après 30 s). Même détection que sur le PC (`jarvis/core/games.py`).

## system_status

- **Description** : état du PC (CPU, RAM, disque système, GPU NVIDIA si présent).
- **Niveau** : N0 (lecture).
- **Paramètres** : aucun.
- **Retour** : `cpu_percent` (mesuré sur 0,2 s), `ram` (`total_gb`, `used_gb`, `percent`),
  `disk` (`drive`, `total_gb`, `free_gb`, `percent`), `gpu` (`name`, `percent`, `vram_used_mb`,
  `vram_total_mb`, `temperature_c`) ou `null` si `nvidia-smi` est absent ou ne répond pas.
- **Exemple** : « Jarvis, état du système » ou `python -m jarvis run system_status`.
- **Notes** : API Windows via `ctypes` ; `nvidia-smi` est appelé par son chemin absolu dans
  `System32` (pas de recherche dans le `PATH`), avec un délai maximal de 5 s. Core sur le mini-PC : l'encart
  Système du tableau de bord l'appelle par l'agent (délai 3 s, vide si le PC est éteint).

## pc_bienetre / pc_social

- **Description** : onglets Bien-être et Réseaux pour le Core du mini-PC, lus sur le PC par l'agent.
- **Niveau** : N0, `owner_only` (jamais proposés au LLM, appelés seulement par `/api/bienetre` et `/api/social`).
- **Paramètres** : aucun.
- **Retour** : `pc_bienetre` = `core.bienetre.snapshot()` ; `pc_social` = `core.social.snapshot()` + compteurs YouTube
  (le jeton de lol-clipper reste sur le PC).
- **Exemple** : ouvrir l'onglet Réseaux de la PWA.
- **Notes** : PC éteint, Bien-être affiche « PC éteint » ; Réseaux affiche le dernier relevé gardé par le Core
  (`~/.jarvis/social-cache.json`) avec sa date. Après ajout : `python -m jarvis.agent catalog` et relance de l'agent.

## list_processes

- **Description** : les 50 processus qui utilisent le plus de mémoire.
- **Niveau** : N0 (lecture).
- **Paramètres** : aucun.
- **Retour** : `total` (nombre de processus) et `processes` : liste de `name`, `pid`, `mem_mb`,
  triée par mémoire décroissante.
- **Exemple** : « liste les processus » ou `python -m jarvis run list_processes`.
- **Notes** : lit la liste par l'API Toolhelp (`system.all_processes`, ~10 ms, réutilisée par le mode jeu de `games.py`). Les noms de processus sont des
  données externes : ils ne doivent jamais être interprétés comme des ordres.

## search_files

- **Description** : cherche les fichiers et dossiers dont le nom contient `name` sous `folder`.
- **Niveau** : N0 (lecture). Drapeau `external` : après son appel, le LLM ne peut plus lancer d'action N2/N3 dans la même demande.
- **Paramètres** :
  - `name` (texte, non vide) : comparaison sans casse ni accents (« ecran » trouve « Écran.png »).
  - `folder` (texte) : dossier existant ; `~` est le dossier utilisateur, un chemin relatif part
    du dossier utilisateur ; les noms français sont traduits (« téléchargements » → Downloads,
    « images » → Pictures, « bureau » → Desktop…). Le dossier doit être sous le dossier utilisateur
    (une autre racine viendra d'un réglage N3). Depuis une phrase, seuls les noms français de la
    liste blanche sont acceptés ; un chemin libre passe par `run`.
- **Retour** : `results` (chemins, 50 au plus) et `complete` (`false` si la recherche a été
  coupée par la limite de 50 résultats ou par le délai de 5 s).
- **Exemple** : « cherche le fichier facture dans mes documents » ou
  `python -m jarvis run search_files name=facture folder=documents`.
- **Notes** : refusés avant tout accès disque : chemins réseau (`\\hôte\...`), `\\?\`, `\\.\`,
  flux ADS (`fichier:flux`), « C: » seul et noms réservés Windows (`CON`, `NUL`, `COM1`…). Le dossier
  est résolu (liens et jonctions suivis) puis doit rester sous le dossier utilisateur. Pendant le
  parcours, les liens symboliques et les jonctions ne sont pas suivis. Un dossier introuvable ou un
  nom vide lève une erreur, journalisée. R3 (Phase 5) : chaque dossier est lu par handle (`GetFileInformationByHandleEx`),
  ouvert sans partage « suppression » et vérifié après l'ouverture (dossier réel, pas de point d'analyse, chemin final sous
  le dossier utilisateur) : un dossier ne peut pas être remplacé par une jonction pendant la lecture.

## Listes blanches (`~/.jarvis`)

`open_app`, `close_app` et `run_script` ne reçoivent jamais un chemin ni une commande : un nom
qui doit figurer dans une liste que le propriétaire édite à la main. Un fichier de configuration est
une donnée : chaque entrée est revalidée à chaque appel.

- `~/.jarvis/apps.json` : `{"navigateur": "C:\Program Files\...\chrome.exe"}`. Nom (sans casse ni
  accents) → exécutable. Entrée ignorée si le chemin n'est pas absolu sur un lecteur local (`X:\`),
  n'est pas un `.exe`, ou est un chemin réseau. Fichier limité à 64 Ko.
- `~/.jarvis/scripts/` : dossier des scripts lançables (`.ps1`, `.bat`, `.cmd`).

## open_app

- **Description** : ouvre une application de la liste blanche, par son nom.
- **Niveau** : N1.
- **Paramètres** : `name` (texte) : un nom de `apps.json`.
- **Retour** : `opened` (nom normalisé). Erreur si le nom est inconnu (la liste des noms autorisés est rappelée).
- **Exemple** : `python -m jarvis run open_app name=navigateur`.
- **Notes** : `subprocess.Popen([exécutable])`, jamais de shell, jamais d'argument, processus détaché.

## close_app

- **Description** : ferme proprement une application de la liste blanche (message `WM_CLOSE` à ses fenêtres visibles : l'application peut proposer d'enregistrer).
- **Niveau** : N1.
- **Paramètres** : `name` (texte) : un nom de `apps.json`.
- **Retour** : `closed_windows` (nombre de fenêtres sollicitées). Les fenêtres retenues sont celles dont le processus est exactement l'exécutable listé.
- **Exemple** : `python -m jarvis run close_app name=navigateur`.
- **Notes** : ne tue aucun processus ; pour un processus bloqué, `kill_process`.

## run_script

- **Description** : lance un script du dossier `~/.jarvis/scripts`, désigné par son nom, sans argument.
- **Niveau** : N2 (confirmation). Drapeaux `private` (sortie jamais journalisée) et `external` (la sortie est du contenu tiers : pas d'action N2/N3 ensuite dans la même demande).
- **Paramètres** : `name` (texte) : `[A-Za-z0-9_-]+` suivi de `.ps1`, `.bat` ou `.cmd` ; ni chemin, ni espace, ni nom réservé Windows.
- **Retour** : `exit_code` et `output` (stdout + stderr, 2 000 caractères au plus). Délai maximal 60 s.
- **Exemple** : `python -m jarvis run run_script name=sauvegarde.bat`.
- **Notes** : le fichier doit se trouver directement dans le dossier une fois les liens résolus. `.ps1` : `powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\nom` ; `.bat`/`.cmd` : `cmd /d /c .\nom`. Interpréteurs par chemin absolu `System32`, `shell=False`, aucun autre argument.

## kill_process

- **Description** : termine de force un processus.
- **Niveau** : N2 (confirmation).
- **Paramètres** : `pid` (entier, > 4) et `name` (texte, ex. `notepad.exe`) : le nom doit être celui de l'image du processus au moment de l'arrêt.
- **Retour** : `killed` (pid) et `name`.
- **Exemple** : `python -m jarvis run kill_process pid=4242 name=notepad.exe`.
- **Notes** : un seul handle sert à vérifier le nom puis à terminer (un PID réattribué est refusé). Refusés : PID ≤ 4, le processus Jarvis lui-même, tout exécutable situé sous le dossier Windows (donc Hyper-V : `vmwp`, `vmms`), et par nom d'image réel (S8 minimal) `tailscaled`, `tailscale`, `tailscale-ipn` et tout `ollama*`. S8 complet (Phase 5) : le chemin de l'image est ramené à sa forme longue (`GetLongPathNameW`, donc `PROGRA~1` ne contourne rien), `vmwp`, `vmms` et `vmcompute` sont refusés par leur nom même hors du dossier Windows, et les ancêtres de Jarvis (terminal, lanceur) sont refusés. L'aperçu de confirmation affiche le chemin réel de l'image. Test réel limité à un PID inexistant ; l'arrêt est testé avec un mock.

## set_volume

- **Description** : règle le volume principal du PC.
- **Niveau** : N1.
- **Paramètres** : `level` (entier 0 à 100).
- **Retour** : `volume`. Un volume > 0 lève aussi la sourdine.
- **Exemple** : « mets le volume à 30 » ou `python -m jarvis run set_volume level=30`.
- **Notes** : Core Audio (`IAudioEndpointVolume`) via `ctypes`, sortie par défaut. Le routeur ne transmet que des chiffres ASCII (« à fort » part au LLM).

## mute

- **Description** : coupe le son du PC ou le rétablit.
- **Niveau** : N1.
- **Paramètres** : `muted` (booléen).
- **Exemple** : « coupe le son », « remets le son » ou `python -m jarvis run mute muted=true`.

## media_control

- **Description** : touche multimédia envoyée au lecteur actif.
- **Niveau** : N1.
- **Paramètres** : `action` : `play_pause`, `next`, `previous` ou `stop`.
- **Exemple** : « pause », « morceau suivant » ou `python -m jarvis run media_control action=next`.
- **Notes** : touches `VK_MEDIA_*` (`keybd_event`) ; pas de retour sur l'état du lecteur.

## screen_off

- **Description** : éteint les écrans ; le PC reste allumé, un mouvement de souris les rallume.
- **Niveau** : N1.
- **Paramètres** : aucun.
- **Exemple** : « éteins l'écran » ou `python -m jarvis run screen_off`.
- **Notes** : `WM_SYSCOMMAND / SC_MONITORPOWER` posté (`PostMessageW`, non bloquant). Testé avec un mock, jamais en réel.

## lock_session

- **Description** : verrouille la session Windows.
- **Niveau** : N1 (se déverrouille avec le code de l'utilisateur).
- **Paramètres** : aucun.
- **Exemple** : « verrouille le PC » ou `python -m jarvis run lock_session`.
- **Notes** : `LockWorkStation`. Testé avec un mock, jamais en réel.

## power

- **Description** : veille, redémarrage ou arrêt du PC.
- **Niveau** : N2 (confirmation). Le redémarrage et l'arrêt coupent Jarvis et Home Assistant.
- **Paramètres** : `action` : `sleep`, `restart` ou `shutdown` (valeurs exactes).
- **Retour** : `power` (l'action). Veille : l'appel ne rend la main qu'au réveil.
- **Exemple** : `python -m jarvis run power action=sleep`.
- **Notes** : veille par `SetSuspendState` ; arrêt et redémarrage par `System32\shutdown.exe /s|/r /t 10` (liste d'arguments, sans `/f` : les applications peuvent réclamer l'enregistrement ; `shutdown /a` annule pendant les 10 s : outil `power_cancel`, utilisable depuis le téléphone). Aucune intention du routeur : « éteins le PC » passe par le LLM puis la confirmation. Testé avec des mocks, jamais en réel.

## power_cancel

- **Description** : annule un redémarrage ou un arrêt en attente (les 10 s de délai de `power`).
- **Niveau** : N1 (annuler ne détruit rien).
- **Paramètres** : aucun.
- **Retour** : `power` : `cancelled`, ou `nothing_pending` si aucun arrêt n'était en cours (code 1116 de `shutdown /a`, pas une erreur).
- **Exemple** : `python -m jarvis run power_cancel`.
- **Notes** : `System32\shutdown.exe /a` par chemin absolu. Sans intention du routeur. Testé avec des mocks.

## driverwatch_accept

- **Description** : accepte la proposition de mise à jour de pilotes que DriverWatch affiche au démarrage du PC (équivaut à Entrée dans sa console).
- **Niveau** : N1, `taint_blocked`. L'installation reste protégée par DriverWatch (point de restauration, signature) et par l'UAC de Windows.
- **Paramètres** : aucun.
- **Retour** : `driverwatch` : `accepté`.
- **Exemple** : « accepte la mise à jour des pilotes », « oui, vas-y mets à jour » (routeur, sans LLM, voix comprise).
- **Notes** : `jarvis/tools/pc/drivers.py` lance `python -m driverwatch accept` ; le dossier se règle par `JARVIS_DRIVERWATCH_DIR`. Sans console en attente, le signal est ignoré. Testé avec des mocks.

## driverwatch_update_all

- **Description** : demande à DriverWatch de mettre à jour tout de suite tous les pilotes en retard (`python -m driverwatch update-all`).
- **Niveau** : N2 (confirmation dans l'app ; refusé à la voix, plafond N0/N1).
- **Paramètres** : aucun.
- **Retour** : `driverwatch` : `mise à jour lancée` (le travail continue en arrière-plan, UAC demandé).
- **Exemple** : « mets à jour tous les pilotes » (LLM, puis confirmation) ou `python -m jarvis run driverwatch_update_all`.
- **Notes** : aucune règle du routeur (le catalogue ne vise aucun N2, S12/C4). Un échec sur un pilote n'arrête pas les suivants ; le résultat est dans l'historique de DriverWatch. Testé avec des mocks.

## pc_plug_on

- **Description** : remet sous tension la multiprise du PC et des écrans (prise Tapo) ; le PC démarre seul si son BIOS est sur « Power On ».
- **Niveau** : N1 (réversible).
- **Paramètres** : aucun.
- **Retour** : `prise` : `on`.
- **Exemple** : « allume la prise du PC », « rallume le PC » (routeur, sans LLM) ou `python -m jarvis run pc_plug_on`.
- **Notes** : `jarvis/tools/home/pcplug.py`, entité `switch.prise_pc`. Prise `unavailable` = erreur explicite, rien n'est envoyé. Utile PC éteint seulement si le Core tourne ailleurs que sur ce PC. Testé avec des mocks, jamais en réel.

## pc_off_plug

- **Description** : éteint le PC proprement par l'agent PC, attend qu'il soit éteint, puis coupe la multiprise du PC et des écrans (prise Tapo P110 via Home Assistant). Jarvis reste en ligne sur le mini-PC.
- **Niveau** : N2 (confirmation).
- **Paramètres** : aucun.
- **Retour** : `power` : `shutdown`, `prise` : `coupure planifiée` (la coupure vient ensuite, en tâche de fond).
- **Exemple** : « éteins la prise du PC » (LLM puis confirmation) ou `python -m jarvis run pc_off_plug`.
- **Notes** : `jarvis/tools/home/pcplug.py`, entités `switch.prise_pc` et `sensor.prise_pc_consommation_actuelle` (plus de script HA). Avant tout : prise joignable et puissance lisible, sinon rien n'est lancé ; refusé si ce Core tourne sur le PC (il s'arrêterait avec lui) ou si `power` est relevé au-dessus de cet outil. L'arrêt passe par l'agent (échec = rien n'est coupé). Puis, en fond : attend la chute de puissance sous `JARVIS_PC_IDLE_W` (défaut 10 W, bornes 5-100 ; mesure de veille : INSTALL_SERVEUR_HA §10.2) pendant 5 min au plus, laisse 30 s, revérifie, coupe ; l'issue (« prise coupée » ou « prise conservée : … ») est écrite au journal (source `pcplug`). Sans intention du routeur (S12/C4). Testé avec des mocks, jamais en réel.

## clipboard_write

- **Description** : copie un texte dans le presse-papiers (remplace son contenu).
- **Niveau** : N1.
- **Paramètres** : `text` (texte, 1 000 caractères au plus).
- **Retour** : `chars`.
- **Exemple** : `python -m jarvis run clipboard_write text=bonjour`.
- **Notes** : `CF_UNICODETEXT` via `ctypes`. Option `hidden=("text",)` : le journal écrit `<n car.>` à la place du texte (mot de passe dicté), y compris en cas d'erreur ou d'entrée invalide. Drapeau `taint_blocked` : le LLM ne peut pas l'appeler après la lecture de contenu externe dans la même demande (une page piégée ne peut pas déposer une commande dans le presse-papiers).

## clipboard_read

- **Description** : lit le texte du presse-papiers (peut contenir un mot de passe).
- **Niveau** : N2 (confirmation). Drapeaux `private` (contenu jamais journalisé, ni dans une erreur) et `external` (contenu tiers : pas d'action N2/N3 ensuite dans la même demande).
- **Paramètres** : aucun.
- **Retour** : `text` (4 000 caractères au plus), `chars` (longueur réelle), `truncated`. Texte vide si le presse-papiers est vide ou non textuel.
- **Exemple** : `python -m jarvis run clipboard_read`.
- **Notes** : le LLM reçoit le contenu encadré par `<data>` et tronqué à 2 000 caractères (`as_data`) : c'est une donnée, jamais un ordre.

## mail_recent

- **Description** : liste les mails reçus ces dernières heures (expéditeur, objet, début du texte) pour que le LLM les résume.
- **Niveau** : N2 (confirmation, lecture des mails §4). Drapeaux `private` (contenu jamais journalisé) et `external` (mails = données non fiables : pas d'action N2/N3 ensuite dans la même demande). Refusé à la voix (plafond N0/N1).
- **Paramètres** : `hours` (1 à 72).
- **Retour** : `total` et `mails` (8 au plus, les plus récents d'abord : `de`, `objet`, `extrait` de 120 caractères).
- **Exemple** : `python -m jarvis run mail_recent hours=24`.
- **Notes** : IMAP/SSL en lecture seule (`BODY.PEEK`, rien n'est marqué lu, aucun envoi ni suppression). Compte dans `~/.jarvis/mail.json` (`{"host": "imap.gmail.com", "user": "..."}`), mot de passe d'application dans le coffre : `python -m jarvis secret set mail_password`.

## claude_code (`jarvis/tools/dev.py`)

- **Description** : fait modifier le code de JARVIS par Claude Code (`claude -p`), sur une branche `jarvis/claude-<horodatage>` placée dans un worktree de `%LOCALAPPDATA%\jarvis-claude-work`. La fusion `--ff-only` dans `main` n'a lieu que si tous les contrôles passent (voir DECISIONS.md, 2026-10-08) ; JARVIS redémarre ensuite. Sinon, le statut est « revue requise » et la branche est gardée.
- **Niveau** : N1 (décision du propriétaire, CLAUDE.md §4). L'outil est `owner_only` : il n'est jamais proposé au LLM, et seules les sources `cli` et `pwa:<id>` sont acceptées. La voix est refusée. Depuis la PWA, la demande exige la signature d'une clé d'accès (WebAuthn, comme une confirmation N3, `permissions.execute`) ; le terminal local ne l'exige pas.
- **Paramètres** : `request` (5 à 500 caractères au routeur).
- **Retour** : PWA : « C'est lancé », puis le travail tourne en arrière-plan, un seul à la fois. CLI : le travail est synchrone et l'outil renvoie le statut.
- **Exemple** : « code : ajoute un bouton pause dans la console », « modifie ton code pour afficher l'heure en gros ».
- **Notes** :
  - Claude tourne en `--restricted --strict-mcp-config`, sans git ni web ; en Bash, il n'a droit qu'à `python -m unittest`.
  - Chemins protégés (`dev.PROTECTED`) : un diff qui y touche n'est jamais fusionné automatiquement.
  - Rien n'est poussé vers GitHub.
  - Compte rendu dans `~/.jarvis/claude_last.json` ; audit `claude_code_merge` (« en cours » avant la fusion, puis le statut).

## claude_code_status

- **Description** : compte rendu du dernier travail Claude Code : `status`, `summary` (sortie de Claude), `diffstat`, `at`.
- **Niveau** : N0, `external` (texte produit hors de JARVIS).
- **Exemple** : « où en est le code ? ».

## screenshot

- **Description** : capture tous les écrans dans un PNG de `~/.jarvis/captures` (hors OneDrive, supprimé après 7 jours par `python -m jarvis purge`) et renvoie le chemin.
- **Niveau** : N2 (confirmation, vie privée). Drapeau `private` : le chemin n'est pas journalisé (seulement le type et la taille du résultat).
- **Paramètres** : aucun.
- **Retour** : `path` et `bytes`. L'image n'est jamais renvoyée au LLM.
- **Exemple** : `python -m jarvis run screenshot`.
- **Notes** : GDI (`BitBlt`) via `ctypes`, PNG encodé avec `zlib` ; bureau virtuel entier, sans mise à l'échelle DPI. Fichier `capture-AAAAMMJJ-HHMMSS.png`, jamais écrasé. Le dossier est supprimable avec `delete_file`.

## move_file

- **Description** : déplace ou renomme un fichier ou dossier du dossier utilisateur.
- **Niveau** : N2 (confirmation).
- **Paramètres** : `src` (existant) et `dst` : un dossier existant (on déplace dedans) ou un nouveau chemin (parent existant, nom libre).
- **Retour** : `moved` (chemin final).
- **Exemple** : `python -m jarvis run move_file src=documents/a.txt dst=documents/b.txt`.
- **Notes** : mêmes règles de chemin que `search_files` (`_allowed_root` : sous le dossier utilisateur, UNC, `\?\`, ADS, noms réservés refusés avant tout accès disque ; liens et jonctions résolus puis revérifiés). Refusés en plus : écraser une destination existante, déplacer un dossier dans lui-même, noms contenant `<>:"|?*` ou finissant par un point ou une espace, le dossier utilisateur et ses dossiers standard (Documents, Bureau…) eux-mêmes, tout ce qui est sous `~/.jarvis` (journal d'audit, listes blanches, scripts) en source comme en destination. Refusés aussi, en source comme en destination, tout chemin passant par `AppData`, `.ssh`, `.gnupg`, `.git` ou le dossier Démarrage (persistance, destruction). La confirmation affiche le chemin **résolu** (`Tool.describe`), pas la saisie brute.

## delete_file

- **Description** : envoie un fichier ou dossier du dossier utilisateur à la corbeille (récupérable).
- **Niveau** : N2 (confirmation).
- **Paramètres** : `path` (existant, mêmes règles que `move_file`).
- **Retour** : `recycled` (chemin résolu). Erreur si l'élément existe encore après l'opération.
- **Exemple** : `python -m jarvis run delete_file path=documents/brouillon.txt`.
- **Notes** : `IFileOperation` (COM via `ctypes`, `CoInitializeEx`/`CoUninitialize` équilibrés, objets relâchés) avec `FOF_SILENT | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOFX_RECYCLEONDELETE` : aucune boîte de dialogue, et si la corbeille est désactivée pour le lecteur ou pleine (quota), l'opération **échoue** au lieu de supprimer définitivement. Lecteur non fixe refusé (`GetDriveTypeW`) ; plus de limite de taille (la corbeille elle-même tranche). Testé par mocks dans la suite ; essai réel sur fichier et dossier temporaires : OK.

## Outils TV (`jarvis/tools/home/tv.py`)

Home Assistant via `jarvis/core/ha.py` (token dans le coffre Windows, utilisateur `jarvis` non administrateur, `JARVIS_HA_URL`). Entités : `media_player.salon_tv` et `remote.salon_tv` (Android TV Remote). Un seul appareil par appel ; pas de valeur absolue de volume sur cette intégration. HA injoignable ou token refusé : erreur journalisée, sans le token.

| Outil | Niveau | Paramètres | Retour | Exemple |
|---|---|---|---|---|
| `tv_status` | N0, `external` (le nom de l'appli est une donnée tierce) | aucun | `state`, `app` (nom connu, `accueil` ou `autre` : jamais le texte brut), `muted`, `volume_percent` | `python -m jarvis run tv_status` |
| `tv_on` / `tv_off` | N1 | aucun | `tv` | « allume la télé », « éteins la TV » (motifs exacts du routeur, jamais approximatifs : « éteins tout » ne les déclenche pas) |
| `tv_volume` | N1 | `direction` (`up`/`down`), `steps` (1 à 5) | `volume`, `steps` | `run tv_volume direction=down steps=2` |
| `tv_mute` | N1 | `muted` (bool) | `muted` | `run tv_mute muted=true` |
| `tv_key` | N1, `taint_blocked` | `button` : `home back up down left right ok play_pause` | `button` | `run tv_key button=back` |
| `tv_open_app` | N1, `taint_blocked` (un achat peut se valider avec `ok`) | `app` : `youtube`, `netflix`, `twitch`, `spotify` (liste blanche de liens propres aux applis, vérifiés sur la TV ; Disney+ et Prime Video : aucun lien ne les a lancées) | `app` | `run tv_open_app app=youtube` |

## scene_cinema (`jarvis/tools/home/scenes.py`)

- **Description** : mode cinéma. Allume la TV du salon (la barre de son suit en HDMI-CEC) si elle ne l'est pas, lance l'appli demandée, puis **vérifie l'état réel** (jusqu'à 15 s par étape). Une TV non confirmée n'ouvre pas d'appli.
- **Niveau** : N1, `taint_blocked` (lance une appli, comme `tv_open_app`). Les sous-outils (`tv_on`, `tv_open_app`) sont appelés sans repasser par la garde, donc non journalisés à part : si le propriétaire en relève un au-dessus de N1, **toute la scène est refusée** avant la première action. Bloquante : échéance de 15 s par étape, soit ~1 min au pire avec un HA lent (+5 s par lecture).
- **Paramètres** : `app` : `youtube`, `netflix`, `twitch`, `spotify`, ou chaîne vide (aucune appli). Une appli inconnue est refusée avant toute action.
- **Retour** : `tv` (`allumée` / `non confirmée`), `app` (nom / `non confirmée` / `null`), `erreur` (présent seulement si HA a échoué : 401, 403, injoignable), `non_traité` : ce que la scène ne fait pas encore (volets, lumière du salon, volume préréglé : matériel absent ou volume absolu indisponible).
- **Exemples** : « mets le mode cinéma », « lance le mode cinéma sur Netflix » (motifs exacts du routeur) ; `python -m jarvis run scene_cinema app=netflix`.
- **Notes** : écart au plan (script HA) : l'utilisateur `jarvis` n'est pas administrateur et ne peut pas créer de script HA ; à migrer quand les volets (Shelly) seront posés.

## say (`jarvis/tools/pc/say.py`)

- **Description** : lit un court texte à voix haute sur le PC (Piper, sortie `JARVIS_AUDIO_OUT` de l'agent).
- **Niveau** : N1.
- **Paramètres** : `text` (texte, 1 000 caractères au plus, 500 lus).
- **Retour** : `say` = `ok` ou `occupé` (déjà en train de parler : rien n'est lu, rien n'est mis en file).
- **Exemple** : `python -m jarvis run say text="Minuteur terminé."`.
- **Notes** : exécuté par l'agent PC. Le Core du mini-PC l'appelle pour les minuteurs, rappels et le briefing (`_reminders`) ; PC éteint ou agent muet, seul le push part. `hidden=("text",)` : le journal écrit `<n car.>`.

## POST /api/voice (client voix du PC, `jarvis/voice_client.py`)

- **Rôle** : le client `python -m jarvis voice` (PC) garde micro, Whisper et Piper en local et n'envoie que le texte reconnu. Le Core appelle `Voice.handle` : routeur puis LLM, source `voix`, journal d'audit côté Core.
- **Plafond** : N0 et N1 seulement. N2 : « Action sensible : fais-la depuis l'application » (aucune demande créée). N3 : refusé. Texte = donnée, jamais un ordre.
- **Authentification** : clé d'appareil (`Bearer`, `python -m jarvis device add` sur le Core). Côté PC elle est dans le coffre Windows : `python -m jarvis secret set voice_key`. Jamais dans un fichier ni `.env`.
- **Requête** : `{"text": 1 à 1 000 car., "client": "pc"}` ; `client` (a-z, 0-9, `_`, `-`, 32 au plus) identifie le micro et est journalisé `appareil/client`. **Réponse** : `{"answer": ...}` (4 000 car. au plus). Limite : 20 phrases par minute et par appareil (429), en plus du quota général.
- **Réglages du client** : `JARVIS_CORE_URL` (`https://<nom>.ts.net`, https obligatoire), `JARVIS_VOICE_CLIENT` (défaut `pc`), `JARVIS_AUDIO_IN` / `JARVIS_AUDIO_OUT` (casque), `JARVIS_WAKE_WORD`. Core injoignable : « Le Core ne répond pas. », rien d'autre.

## Minuteurs, rappels et briefing (`jarvis/tools/assist.py`, `jarvis/core/reminders.py`)

Table `reminders` dans la base du journal. À l'échéance : annonce Piper sur le PC (sauf voix « hors ligne ») et push **sans le texte** à tous les appareils. Le texte d'un rappel est supprimé de la base une fois annoncé et n'entre jamais dans le journal (id et longueur seulement : `args` masqués, résultats sans texte). 50 rappels en attente au plus, 24 h au plus.

| Outil | Niveau | Paramètres | Retour | Exemple |
|---|---|---|---|---|
| `timer_set` | N1, `taint_blocked` | `duration` (« 20 minutes », « 1h30 », « une demi-heure »), `label` (peut être vide) | heure de fin | « mets un minuteur de 10 minutes pour les pâtes », « rappelle-moi de sortir le linge dans 20 minutes » |
| `reminder_set` | N1, `taint_blocked` | `when` (« dans 2 heures », « à 7h30 », « demain à 8h »), `label` | heure du rappel | « réveille-moi à 7h », « rappelle-moi à 18h30 d'appeler Paul » |
| `reminder_list` | N0 | aucun | une ligne par rappel : `#id à HH:MM : minuteur/rappel` (jamais le texte, qui reste journal-safe et lisible à la voix) | « mes rappels » |
| `reminder_cancel` | N1, `taint_blocked` | `id` (0 = le plus proche) | id annulé | « annule le minuteur », « annule le rappel 3 » |
| `briefing` | N0, `external` | aucun | date, météo, rappels du jour (nombre et heure, jamais le texte), publications lol-clipper du jour, 2 titres de la veille IA | « briefing du matin » |

| `memory_set` | N1, `taint_blocked` | `text` (une phrase, 200 car. au plus ; 30 souvenirs au plus) | « C'est noté (souvenir N) » | « souviens-toi que je suis allergique aux noix » |
| `memory_list` | N0, privé | aucun | `#id texte` par souvenir (résultat jamais journalisé en clair) | « que sais-tu sur moi » |
| `memory_forget` | N1, `taint_blocked` | `about` (un mot du souvenir ou son numéro) | nombre oublié | « oublie les noix » |

- **Mémoire** (`jarvis/core/memory.py`, table `memory` de la base du journal) : les souvenirs sont ajoutés au prompt système entre `<data>` (donnée, jamais un ordre). Le texte n'est jamais journalisé (paramètres masqués, liste privée). Écriture refusée au LLM après lecture de contenu externe. **Donnée personnelle** : base locale, sauvegardes comprises. Pas d'écran PWA pour l'instant.

- **Briefing sans mails ni finances** : `mail_recent` est N2 et privé, les finances sont privées ; lus à voix haute, ils sortiraient devant la TV ou un visiteur. Une source en panne est omise, le reste est dit.
- **Briefing automatique** : `JARVIS_BRIEFING_AT=07:30` (HH:MM, `.env`). Un rappel de type `briefing` se réarme chaque jour ; lu par la voix du PC + push « ton briefing est prêt ». Un briefing manqué de plus de 2 h (PC éteint) n'est pas lu.
- Annonce : le journal dit ce qui a été fait (`voix + push`, `push`, `non remis`). Voix hors ligne, muette ou occupée > 20 s : push seul, le texte est perdu (supprimé avant l'annonce). Les sauvegardes de la base contiennent les rappels en attente (texte inclus) : base locale, propriétaire seul.
- Analyse des durées et heures : `parse_duration`, `parse_when` (« 7h » déjà passé = demain ; pas de « midi » ni de jours de semaine).

## voyage_prix (`jarvis/tools/voyages.py`)

- **Description** : meilleur prix de la recherche la plus récente de flight-price-tracker : prix, ville de départ, dates, escales, hausse ou baisse depuis le relevé précédent, plus bas observé. Même lecture que l'onglet Voyages (`voyages.snapshot`).
- **Niveau** : N0, `external` (le CSV vient d'un dépôt public : le texte est une donnée). Routeur sans LLM : « prix des vols », « où en sont les vols ».
- **Paramètres** : aucun. **Exemple** : « Jarvis, prix des vols » → « Japon 2027-05-05 : 870 € depuis Paris, du 05/05 au 22/05, 1 escale(s) (relevé du 04/10). Baisse de 30 € … ».
- **Notes** : changer de destination reste `voyage_destination` (N2) : par le chat avec confirmation dans la PWA, jamais à la voix.

## conso_pc (`jarvis/tools/conso.py`)

- **Description** : énergie consommée par le PC, mesurée par sa prise Tapo P110 (`sensor.prise_pc_consommation_actuelle` via Home Assistant), en kWh et en € (prix saisi par le propriétaire), avec la période d'avant. Même lecture que l'onglet « Consommation » et le carré « Conso · PC » (`/api/conso`).
- **Niveau** : N0 (lecture du cache local `~/.jarvis/conso.db`). Pas `external` : seuls des nombres calculés par le Core en sortent. Routeur sans LLM : « combien consomme le PC », « combien le PC a consommé aujourd'hui / cette semaine / ce mois-ci », « la consommation du PC ».
- **Paramètres** : `periode` = `jour`, `semaine` (7 jours glissants) ou `mois` (30 jours glissants) ; alias « aujourd'hui ». Autre valeur : refusée. **Exemple** : « Jarvis, combien le PC a consommé aujourd'hui ? » → « Le PC a consommé 1,50 kWh aujourd'hui (environ 0,38 €), contre 2,00 kWh hier. »
- **Notes** : un fil du Core échantillonne la puissance chaque minute et l'intègre par jour (trapèze, intervalle > 3 min ignoré) ; Core éteint ou prise illisible = trou, jamais comblé : « Mesuré sur N h seulement : le total est sous-estimé ». Rétention 65 jours, un total par jour (aucune courbe fine : RGPD). Sans mesure : « donnée indisponible ». Prix du kWh : `~/.jarvis/conso.json`, modifiable par `PUT /api/conso/tarif` (0 < prix ≤ 5 €, une ligne au journal sans le montant). Le total du logement (Enedis) et les conseils viennent aux étapes 2 et 3.

## conso_conseils (`jarvis/tools/conso.py`)

- **Description** : conseils pour consommer moins, construits par des règles déterministes (`jarvis/core/conseils.py`) sur les totaux quotidiens du logement et du PC. Aucun appel au LLM : chaque phrase cite le chiffre qui la justifie.
- **Niveau** : N0 (lecture du cache local). Aucune action automatique : un conseil ne déclenche rien. Routeur sans LLM : « des conseils pour consommer moins », « comment réduire ma conso ».
- **Paramètres** : aucun. **Exemple** : « Jarvis, des conseils pour consommer moins ».
- **Règles** (7 jours, seuils en constantes) : hausse du logement ≥ 15 % et ≥ 5 kWh ; PC ≥ 25 % du total sur au moins 5 jours mesurés des deux côtés (« au moins » si le PC est mesuré partiellement, jamais si la part est plafonnée à 100 %) ; hausse du PC ≥ 25 % et ≥ 1 kWh. Une période ou une période précédente partielle ne déclenche jamais de comparaison. Sans aucune règle évaluable, la réponse est « pas assez de relevés complets », jamais « rien d'anormal ».
- **Notes** : « talon nocturne » et « PC allumé la nuit » exigent une répartition horaire, non conservée aujourd'hui (totaux quotidiens, RGPD) : non codées, décision du propriétaire en attente.

## conso_totale (`jarvis/tools/conso.py`)

- **Description** : énergie consommée par tout le logement (compteur Linky), relevé de la veille, via la passerelle hébergée MyElectricalData (Enedis n'ouvre pas Data Connect aux particuliers). kWh et € (prix saisi), période d'avant, part du PC calculée sur les seuls jours mesurés des deux côtés.
- **Niveau** : N0 (lecture du cache `~/.jarvis/conso.db`, table `home_energy`). Pas `external` : seuls des nombres calculés par le Core en sortent. Routeur sans LLM : « combien j'ai consommé chez moi », « la conso de la maison cette semaine ».
- **Paramètres** : `periode` = `jour` (hier), `semaine` (7 jours) ou `mois` (30 jours), fenêtres de jours complets finissant hier. Autre valeur : refusée. **Exemple** : « Jarvis, combien j'ai consommé chez moi hier ? »
- **Notes** : le Core appelle l'API au plus une fois par 24 h, jusqu'à 3 fois si le relevé de la veille n'est pas encore publié (à partir de 8 h), et pas avant 6 h après un échec (`jarvis/core/enedis.py`, 10 s de délai, une tentative, réponse bornée : 0 à 500 kWh/jour, jours hors fenêtre ignorés). Jeton `med_token` et PDL `med_pdl` dans le coffre (`python -m jarvis secret set med_token`), jamais dans un fichier. Source absente ou en panne : « donnée indisponible », rien n'est estimé ni écrit. Une ligne `conso_enedis_fetch` au journal à chaque changement d'état, sans valeur. Totaux quotidiens seulement (pas de courbe 30 min), 65 jours gardés.

## voyage_destination (`jarvis/tools/voyages.py`)

- **Description** : change la destination suivie par flight-price-tracker : nouvelle recherche en tête de `searches` dans `config.yaml`, les recherches actives commentées (en pause, historique gardé), commit `config : …` puis push sur `main`.
- **Niveau** : N2 (confirmation), `taint_blocked`. Refusé à la voix (plafond N1).
- **Paramètres** : `destination` (ville, pays ou IATA), `depart_from` / `depart_to` (AAAA-MM-JJ, début au plus tôt demain, fin dans les 400 jours), `stay_days` (ex. `"10,14"`, 1 à 5 durées de 1 à 90 j) **ou** `return_date` (l'autre vide), `origins` (villes séparées par des virgules, 1 à 10), `alert_below` (€, 0 = aucun).
- **Retour** : phrase avec le nom de la recherche (`<destination> <depart_from>`) et le commit poussé.
- **Exemple** : onglet Voyages → « Changer de destination » (route `POST /api/voyages/destination`, confirmation N2 dans la PWA).
- **Notes** : `git fetch`, puis `config.yaml` lu dans `origin/main` ; commit par la plomberie (`hash-object`, index temporaire, `commit-tree`) et `push origin <sha>:refs/heads/main` sans `--force` : ni la copie de travail ni la branche locale du propriétaire ne bougent. Validation avant le commit par le `load_config` du projet (son `.venv`) : départs hors France/Barcelone et destinations inconnues refusés avec le message du projet. Champs bornés par des motifs (lettres, espaces, tirets, apostrophes) : ni e-mail ni secret dans le dépôt public ; valeurs écrites en chaînes JSON (YAML entre guillemets). Push refusé (le workflow a commité entre-temps) : une seconde tentative sur le nouvel `origin/main`. Ne recopie pas les filtres de l'ancienne recherche (escales, durée des escales).

## voyage_recherche (`jarvis/tools/voyages.py`)

- **Description** : recherche de vols ponctuelle : lance le workflow `search.yml` de flight-price-tracker (`gh workflow run`), qui envoie le résultat par e-mail. Ni `config.yaml` ni l'historique ne sont touchés : le suivi en cours ne change pas.
- **Niveau** : N1, `taint_blocked` (refusé au LLM après un contenu externe : un mail ou une page ne peut pas déclencher d'envoi d'e-mail).
- **Paramètres** : les mêmes que `voyage_destination`, avec les mêmes validations (`_spec`).
- **Exemple** : « cherche aussi la Thaïlande du 1er au 10 février, retour le 20 » → « Recherche Thaïlande lancée sur GitHub : le résultat arrivera par e-mail… ».
- **Notes** : `gh` lancé dans le clone (dépôt déduit de son `origin`, jeton de `gh auth`, jamais lu par JARVIS), `GH_PROMPT_DISABLED=1`, timeout 30 s, une recherche par minute au plus ; champs passés en `-f clé=valeur` (aucune valeur ne peut devenir une option), le workflow les reçoit en variables d'environnement. Pas d'intention au routeur : il faut des dates, donc le LLM. Les filtres avancés du workflow (escales, classe, bagage) gardent leurs valeurs par défaut. **Dépôt public** : destination et dates de la recherche sont lisibles dans les journaux Actions (et l'e-mail en artefact 7 jours).

## Commande `say` (voix, Phase 4 étape 3)

- **Commande** : `python -m jarvis say "texte"` (pas un outil du registre, aucune route HTTP). Lit le texte avec Piper (`fr_FR-tom-medium`, `length_scale` 1,05), source `voix`, texte tronqué à `ANSWER_MAX`.
- **Garde** : voix chargée seulement si son SHA-256 correspond à `models/MANIFEST.json` ; synthèse en mémoire par phrase, aucun fichier ni cache ; sortie : `JARVIS_AUDIO_OUT` (nom ou index, vide = défaut).
- **Journal** : une ligne `voix` / `tts` avec `{"len": n}` et le résultat (`ok`, `interrompu`, `erreur`), jamais le texte. Erreur : « Synthèse vocale indisponible. ».
- **Anti-écho** : `Speaker.is_speaking()`, `Speaker.ignore_until()` (`time.monotonic`, infini pendant la lecture, fin + 0,4 s ensuite), `Speaker.stop()`.
